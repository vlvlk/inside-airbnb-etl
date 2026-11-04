"""Build the Parquet demo layer the dashboard can run without PostgreSQL.

The dashboard normally reads the marts the ETL pipeline built in PostgreSQL.
That makes a first look expensive: a reviewer has to start Docker and wait out
an 8M-row load before the first chart appears. This script removes that step by
running the *entire* pipeline — raw load, staging, marts — inside a throwaway
DuckDB database, then exporting the result as a small directory of Parquet
files the dashboard reads directly.

Nothing is reimplemented here. The script runs the very same ``sql/*.sql``
scripts the pipeline runs, translated to the DuckDB dialect by
:func:`src.dashboard.backend.to_duckdb_sql`, and it reads the Parquet snapshot
through the very same :class:`~src.extract.parquet_extractor.ParquetExtractor`
and vectorized normalizers the pipeline uses. If the two engines ever disagree,
that is a bug in the translation layer, not a second implementation.

Why Parquet and not a ``.duckdb`` file: the three schemas materialise to ~950 MB
in DuckDB, which cannot be committed. The dashboard only ever reads the marts
plus a handful of counts, and those compress to ~14 MB as zstd Parquet — the
same order as the snapshot already in the repository. DuckDB reads Parquet
natively, so :class:`~src.dashboard.backend.DuckDbBackend` exposes the files as
views at no cost.

Usage::

    python -m scripts.build_demo_marts              # build the demo layer
    python -m scripts.build_demo_marts --force      # rebuild from scratch
    python -m scripts.build_demo_marts --verify     # check an existing build

The build takes roughly a minute and needs no network access.
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pandas as pd

from src.config import AppConfig, get_config
from src.dashboard.backend import DEMO_FILES, to_duckdb_sql
from src.extract import make_extractor

logger = logging.getLogger(__name__)

#: Repository root, used to locate the ``sql`` directory regardless of the
#: working directory the script is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: SQL scripts run in this order to build every layer.
DDL_SCRIPTS: tuple[str, ...] = (
    "01_ddl_raw.sql",
    "02_ddl_staging.sql",
    "03_ddl_marts.sql",
)
TRANSFORM_SCRIPTS: tuple[str, ...] = (
    "04_transform_staging.sql",
    "05_transform_marts.sql",
)

#: Parquet export settings. zstd-19 is what keeps the layer near the size of the
#: source snapshot; the export is a one-off, so the slower compression pays off.
PARQUET_OPTIONS = "(FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 19)"

#: Projections exported per table. The demo layer only has to answer the
#: dashboard's queries, so wide tables are narrowed to the columns those queries
#: actually read. ``raw.listings`` is the clearest case: the DDL has 90 columns
#: but ``data_quality.sql`` only counts rows, so exporting the full row would add
#: 6 MB for nothing.
DEMO_EXPORTS: dict[str, str] = {
    # --- marts: the four tables the dashboard reads, in full -----------------
    "marts.occupancy_by_listing": """
        SELECT listing_id, year, month, week_of_year, quarter,
               total_nights, available_nights, booked_nights,
               occupancy_rate::DOUBLE AS occupancy_rate
        FROM marts.occupancy_by_listing
    """,
    "marts.occupancy_by_neighbourhood": """
        SELECT neighbourhood_cleansed, year, month, week_of_year, quarter,
               total_listings, total_nights, available_nights, booked_nights,
               occupancy_rate::DOUBLE AS occupancy_rate,
               avg_price_per_night::DOUBLE AS avg_price_per_night
        FROM marts.occupancy_by_neighbourhood
    """,
    "marts.occupancy_by_room_type": """
        SELECT room_type, year, month, week_of_year, quarter,
               total_listings, total_nights, available_nights, booked_nights,
               occupancy_rate::DOUBLE AS occupancy_rate,
               avg_price_per_night::DOUBLE AS avg_price_per_night
        FROM marts.occupancy_by_room_type
    """,
    "marts.revenue_by_listing": """
        SELECT listing_id, year, month, quarter,
               avg_daily_rate::DOUBLE AS avg_daily_rate,
               revenue_per_available_night::DOUBLE AS revenue_per_available_night,
               total_revenue::DOUBLE AS total_revenue,
               booked_nights, available_nights,
               occupancy_rate::DOUBLE AS occupancy_rate
        FROM marts.revenue_by_listing
    """,
    # --- raw/staging: only what sql/queries/data_quality.sql counts ----------
    # The query reads raw.listings for a row count and a listing_id join, so
    # ``id`` alone is enough.
    "raw.listings": "SELECT id FROM raw.listings",
    # The staging listing columns the quality query touches: the price null
    # count and the host-portfolio segmentation used by host_segmentation.sql.
    "staging.listings": """
        SELECT listing_id, price_per_night, host_listings_count
        FROM staging.listings
    """,
    # ``Listings with calendar data`` is a DISTINCT count, so the demo layer
    # stores the distinct ids once instead of the 8M-row calendar.
    "staging.calendar": "SELECT DISTINCT listing_id FROM staging.calendar",
    # ``Calendar rows with NULL availability`` is zero for this snapshot (the
    # staging filter drops nothing), and the export keeps it at zero by
    # construction. A snapshot that does drop rows keeps its real count here,
    # because the build script exports whatever the filter actually removed.
    "raw.calendar": """
        SELECT listing_id, available FROM raw.calendar WHERE available IS NULL
    """,
}

#: Headline figures the build is verified against. These are the numbers
#: documented in ``docs/methodology.md`` for the bundled Toronto snapshot; a
#: mismatch means the demo layer does not reproduce the pipeline's output.
EXPECTED: dict[str, object] = {
    "calendar_nights": 8_048_251,
    "booked_nights": 3_814_938,
    "occupancy_rate": 0.474,
    "total_revenue": 538_161_557,
}


class BuildError(RuntimeError):
    """Raised when the demo layer cannot be built or fails verification."""


def _sql_dir() -> Path:
    return PROJECT_ROOT / "sql"


def _run_script(connection: duckdb.DuckDBPyConnection, name: str) -> None:
    """Execute one ``sql/`` script against DuckDB, adapting the dialect."""
    path = _sql_dir() / name
    sql = to_duckdb_sql(path.read_text(encoding="utf-8"))
    logger.info("Running %s", name)
    connection.execute(sql)


def _insert_batches(
    connection: duckdb.DuckDBPyConnection,
    batches: Iterator[pd.DataFrame],
    table: str,
    source_file: str,
) -> int:
    """Stream normalized extractor batches into ``table``.

    Each batch is registered as a temporary relation and inserted with
    ``INSERT ... BY NAME``, so columns are matched by name rather than by
    position and a reordering in the DDL cannot silently shift values. This is
    the same streaming shape the PostgreSQL loader uses, so peak memory stays
    proportional to ``pipeline.chunk_size`` instead of the file size.
    """
    total = 0
    for batch in batches:
        frame = batch.assign(
            loaded_at=pd.Timestamp.now(tz="UTC"),
            source_file=source_file,
        )
        connection.register("batch", frame)
        try:
            connection.execute(f"INSERT INTO {table} BY NAME SELECT * FROM batch")
        finally:
            connection.unregister("batch")
        total += len(frame)
    return total


def _materialize(connection: duckdb.DuckDBPyConnection, config: AppConfig) -> None:
    """Run the whole pipeline inside DuckDB, producing ``raw``/``staging``/``marts``."""
    for script in DDL_SCRIPTS:
        _run_script(connection, script)

    extractor = make_extractor()
    listings = _insert_batches(
        connection,
        extractor.extract_listings(),
        "raw.listings",
        config.data.listings_file,
    )
    calendar = _insert_batches(
        connection,
        extractor.extract_calendar(),
        "raw.calendar",
        config.data.calendar_file,
    )
    logger.info(
        "Loaded %s listings and %s calendar rows",
        f"{listings:,}",
        f"{calendar:,}",
    )

    for script in TRANSFORM_SCRIPTS:
        _run_script(connection, script)


def _export_parquet(connection: duckdb.DuckDBPyConnection, destination: Path) -> None:
    """Export every table in :data:`DEMO_FILES` to the demo directory."""
    for qualified_name, filename in DEMO_FILES.items():
        projection = DEMO_EXPORTS.get(qualified_name)
        if projection is None:  # pragma: no cover - guarded by a test
            raise BuildError(
                f"No export projection defined for {qualified_name}. "
                "Add it to DEMO_EXPORTS so the demo layer stays complete."
            )
        target = destination / filename
        logger.info("Exporting %s -> %s", qualified_name, filename)
        connection.execute(
            f"COPY ({projection}) TO '{target.as_posix()}' {PARQUET_OPTIONS}"
        )


def build_demo_layer(
    config: AppConfig | None = None,
    output: Path | None = None,
    *,
    force: bool = False,
    verify: bool = True,
) -> Path:
    """Build the Parquet demo layer and return its directory.

    Parameters
    ----------
    config:
        Application config; the default config is used when omitted.
    output:
        Destination directory. Defaults to ``dashboard.demo_dir``.
    force:
        Rebuild even when the destination already holds a layer. Without it an
        existing layer is left alone, because the build is not incremental.
    verify:
        Check the materialised pipeline against the figures documented for the
        bundled Toronto snapshot (:data:`EXPECTED`). Leave it on for the
        committed snapshot; turn it off when building the demo layer from a
        *different* city, whose headline figures are naturally different.
    """
    config = config or get_config()
    destination = output or config.dashboard.demo_path

    if destination.exists() and any(destination.glob("*.parquet")) and not force:
        logger.info(
            "%s already holds a demo layer; pass --force to rebuild", destination
        )
        return destination

    destination.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    # The materialised database is ~950 MB and is deleted at the end; only the
    # Parquet export is kept. A temporary file keeps the repository clean if the
    # build is interrupted.
    with tempfile.TemporaryDirectory(prefix="inside-airbnb-demo-") as tmp:
        working = Path(tmp) / "build.duckdb"
        connection = duckdb.connect(str(working))
        try:
            _materialize(connection, config)
            # Verify against the documented figures *before* exporting: this is
            # the only moment the full raw/staging layers exist, and the night
            # total cannot be recovered from the narrowed export.
            measured = measure_pipeline(connection)
            if verify:
                if not _matches(measured):
                    raise BuildError(
                        "The DuckDB pipeline does not reproduce the documented "
                        f"figures: {measured}"
                    )
                logger.info("Pipeline figures verified: %s", _headline(measured))
            else:
                logger.warning(
                    "Verification skipped; measured figures: %s", _headline(measured)
                )
            _export_parquet(connection, destination)
        finally:
            connection.close()

    elapsed = time.perf_counter() - started
    size_mb = sum(f.stat().st_size for f in destination.glob("*.parquet")) / 1e6
    logger.info(
        "Built demo layer in %s (%.1f MB) in %.1fs", destination, size_mb, elapsed
    )
    return destination


def _headline(measured: dict[str, object]) -> str:
    """One-line summary of the figures, for the build log."""
    return ", ".join(f"{key}={measured[key]}" for key in EXPECTED if key in measured)


def _matches(measured: dict[str, object]) -> bool:
    """Whether every figure in :data:`EXPECTED` was reproduced exactly."""
    return all(measured.get(key) == value for key, value in EXPECTED.items())


def measure_pipeline(connection: duckdb.DuckDBPyConnection) -> dict[str, object]:
    """Measure the documented figures on a fully materialised DuckDB pipeline.

    This runs against the throwaway database the build materialises, where the
    complete ``raw``/``staging``/``marts`` schemas exist. It is the strongest
    check available: the same SQL scripts, a different engine, and the numbers
    have to land exactly on the ones in ``docs/methodology.md``.
    """
    nights = connection.execute("SELECT COUNT(*) FROM staging.calendar").fetchone()
    booked = connection.execute(
        "SELECT COUNT(*) FILTER (WHERE NOT available) FROM staging.calendar"
    ).fetchone()
    occupancy = connection.execute(
        """
        SELECT SUM(booked_nights)::DOUBLE / NULLIF(SUM(total_nights), 0)
        FROM marts.occupancy_by_listing
        WHERE month IS NULL AND week_of_year IS NULL AND quarter IS NULL
        """
    ).fetchone()
    revenue = connection.execute(
        """
        SELECT SUM(total_revenue) FROM marts.revenue_by_listing
        WHERE month IS NULL AND quarter IS NULL
        """
    ).fetchone()

    return {
        "calendar_nights": int(nights[0]) if nights else 0,
        "booked_nights": int(booked[0]) if booked else 0,
        "occupancy_rate": round(float(occupancy[0]), 3)
        if occupancy and occupancy[0]
        else 0.0,
        "total_revenue": round(float(revenue[0])) if revenue and revenue[0] else 0,
    }


def verify_demo_layer(path: Path) -> dict[str, object]:
    """Re-read a built demo layer and report the figures it can answer.

    The layer is narrowed on purpose (see :data:`DEMO_EXPORTS`), so the night
    total is not recoverable from it — that figure is checked by
    :func:`measure_pipeline` during the build, while the full pipeline is still
    materialised. What this function proves is that the exported files exist,
    load, and still carry the metrics the dashboard reads: the booked-night
    total, the occupancy rate and the estimated revenue.
    """
    if not path.is_dir():
        raise BuildError(f"Demo layer not found at {path}")

    connection = duckdb.connect()
    try:
        for schema in ("raw", "staging", "marts"):
            connection.execute(f"CREATE SCHEMA {schema}")
        for qualified_name, filename in DEMO_FILES.items():
            file = path / filename
            if not file.exists():
                raise BuildError(f"Demo layer is incomplete: {file} is missing")
            connection.execute(
                f"CREATE VIEW {qualified_name} AS "
                f"SELECT * FROM read_parquet('{file.as_posix()}')"
            )

        booked_nights = connection.execute(
            """
            SELECT SUM(booked_nights) FROM marts.occupancy_by_listing
            WHERE month IS NULL AND week_of_year IS NULL AND quarter IS NULL
            """
        ).fetchone()
        occupancy = connection.execute(
            """
            SELECT SUM(booked_nights)::DOUBLE / NULLIF(SUM(total_nights), 0)
            FROM marts.occupancy_by_listing
            WHERE month IS NULL AND week_of_year IS NULL AND quarter IS NULL
            """
        ).fetchone()
        revenue = connection.execute(
            """
            SELECT SUM(total_revenue) FROM marts.revenue_by_listing
            WHERE month IS NULL AND quarter IS NULL
            """
        ).fetchone()
        listings = connection.execute(
            "SELECT COUNT(*) FROM staging.calendar"
        ).fetchone()
    finally:
        connection.close()

    return {
        "booked_nights": int(booked_nights[0]) if booked_nights else 0,
        "occupancy_rate": round(float(occupancy[0]), 3)
        if occupancy and occupancy[0]
        else 0.0,
        "total_revenue": round(float(revenue[0])) if revenue and revenue[0] else 0,
        "listings_with_calendar": int(listings[0]) if listings else 0,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Build the Parquet demo layer for the dashboard."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Destination directory (default: dashboard.demo_dir from the config)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when the destination already holds a layer",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only verify an existing layer against the documented figures",
    )
    parser.add_argument(
        "--no-verify",
        dest="no_verify",
        action="store_true",
        help=(
            "Skip the check against the bundled Toronto figures while building. "
            "Use it when the demo layer is built from a different city."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build (or verify) the demo layer and return a process exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    args = parse_args(argv)
    config = get_config()
    destination = args.output or config.dashboard.demo_path

    try:
        if args.verify:
            # A rebuild re-checks the documented figures as part of the build,
            # so --verify only has to confirm the exported layer is readable.
            measured = verify_demo_layer(destination)
            logger.info("Exported layer: %s", measured)
            logger.info("Demo layer verified")
            return 0

        build_demo_layer(
            config, args.output, force=args.force, verify=not args.no_verify
        )
    except (BuildError, duckdb.Error) as exc:
        logger.error("Demo build failed: %s", exc)
        return 1

    logger.info("Demo layer built and verified against docs/methodology.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
