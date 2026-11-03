"""Query backends for the occupancy dashboard.

The dashboard is a read-only view over three schemas (``raw``, ``staging``,
``marts``) that the ETL pipeline normally builds in PostgreSQL. Requiring a
database server to look at the dashboard is a poor fit for a repository that
ships its own dataset: a reviewer has to start Docker and wait out an 8M-row
load before the first chart appears.

This module keeps the analytics in one place while letting the *engine* vary:

* :class:`PostgresBackend` — the production path, reading the marts the pipeline
  populated.
* :class:`DuckDbBackend` — the demo path, reading a small Parquet layer that
  ``scripts/build_demo_marts.py`` builds from the committed snapshot by running
  the very same ``sql/*.sql`` scripts.

Because both backends execute the same ``sql/queries/*.sql`` files, no query is
duplicated and no aggregation is reimplemented in Python. The only thing that
differs is the SQL dialect, and :func:`to_duckdb_sql` bridges that gap.

This module deliberately imports no Streamlit: it is plain Python so it can be
unit-tested and reused from a CLI (the build script uses it too).
"""

from __future__ import annotations

import logging
import re
import threading
from abc import ABC, abstractmethod
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.config import AppConfig

logger = logging.getLogger(__name__)

#: Scalar values accepted as SQL bind parameters by :meth:`QueryBackend.execute`.
#: Defined once here and imported by :mod:`src.dashboard.data`, so the two
#: layers cannot drift into incompatible (invariant) dict value types.
SqlParamValue = str | bytes | date | timedelta | int | float | bool | None

#: Seconds to wait for a PostgreSQL connection before declaring it unreachable.
POSTGRES_CONNECT_TIMEOUT = 3


class BackendUnavailable(RuntimeError):
    """Raised when a backend cannot be used (no server, or no demo layer)."""


# ---------------------------------------------------------------------------
# Demo layer layout
# ---------------------------------------------------------------------------

#: Parquet files that make up the DuckDB demo layer, keyed by the
#: ``schema.table`` name each one answers to. The build script writes exactly
#: these names and :class:`DuckDbBackend` reads them back, so the two cannot
#: drift apart.
DEMO_FILES: dict[str, str] = {
    "raw.listings": "raw_listings.parquet",
    "raw.calendar": "raw_calendar.parquet",
    "staging.listings": "staging_listings.parquet",
    "staging.calendar": "staging_calendar.parquet",
    "marts.occupancy_by_listing": "marts_occupancy_by_listing.parquet",
    "marts.occupancy_by_neighbourhood": "marts_occupancy_by_neighbourhood.parquet",
    "marts.occupancy_by_room_type": "marts_occupancy_by_room_type.parquet",
    "marts.revenue_by_listing": "marts_revenue_by_listing.parquet",
}

#: Schemas the demo layer exposes. Created before any view is registered.
DEMO_SCHEMAS: tuple[str, ...] = ("raw", "staging", "marts")

#: ``marts.v_occupancy_summary`` is a view in PostgreSQL, not a table, so it has
#: no Parquet file of its own. It is recreated over the demo marts instead.
#: ``::DOUBLE`` replaces the PostgreSQL ``::NUMERIC`` so the division returns a
#: float rather than a Decimal, matching what the other demo columns produce.
DEMO_SUMMARY_VIEW_SQL = """
CREATE VIEW marts.v_occupancy_summary AS
SELECT
    'overall' AS dimension,
    NULL::TEXT AS dimension_value,
    year,
    month,
    quarter,
    SUM(total_listings) AS total_listings,
    SUM(total_nights) AS total_nights,
    SUM(available_nights) AS available_nights,
    SUM(booked_nights) AS booked_nights,
    CASE WHEN SUM(total_nights) > 0
         THEN SUM(booked_nights)::DOUBLE / SUM(total_nights)
         ELSE 0 END AS occupancy_rate,
    AVG(avg_price_per_night) AS avg_price_per_night
FROM (
    SELECT year, month, quarter, total_listings, total_nights,
           available_nights, booked_nights, avg_price_per_night
    FROM marts.occupancy_by_neighbourhood
    UNION ALL
    SELECT year, month, quarter, total_listings, total_nights,
           available_nights, booked_nights, avg_price_per_night
    FROM marts.occupancy_by_room_type
) combined
GROUP BY year, month, quarter
ORDER BY year, month, quarter
"""


# ---------------------------------------------------------------------------
# Dialect adaptation
# ---------------------------------------------------------------------------

#: ``UNIQUE NULLS NOT DISTINCT`` (PostgreSQL 15+) has no DuckDB equivalent.
#: DuckDB treats NULLs as distinct in a UNIQUE constraint, which is harmless
#: here: the demo layer is built once, so the constraint never has to arbitrate
#: an upsert.
_NULLS_NOT_DISTINCT = re.compile(r"UNIQUE\s+NULLS\s+NOT\s+DISTINCT", re.IGNORECASE)

#: ``:name`` bind markers become ``$name``. The negative lookbehind keeps the
#: PostgreSQL ``::`` cast operator (``booked_nights::NUMERIC``) intact.
_BIND_MARKER = re.compile(r"(?<!:):([A-Za-z_]\w*)")


def to_duckdb_sql(sql: str) -> str:
    """Translate PostgreSQL SQL into the DuckDB dialect.

    Only two constructs used by this project differ:

    1. ``UNIQUE NULLS NOT DISTINCT`` -> ``UNIQUE`` (see
       :data:`_NULLS_NOT_DISTINCT`).
    2. ``:name`` bind markers -> ``$name`` (see :data:`_BIND_MARKER`).

    Everything else the queries rely on — ``FILTER (WHERE ...)``,
    ``IS NOT DISTINCT FROM``, ``EXTRACT(ISODOW ...)``, ``regexp_replace``,
    ``RANK() OVER``, ``NULLS LAST``, ``::NUMERIC`` casts and
    ``ON CONFLICT ... DO UPDATE`` — is already valid DuckDB, verified against
    the bundled snapshot.

    The translation is textual, so it assumes no bind marker appears inside a
    string literal. No query in ``sql/`` does that; a new one that needs a
    literal colon should use ``$name`` directly.
    """
    sql = _NULLS_NOT_DISTINCT.sub("UNIQUE", sql)
    return _BIND_MARKER.sub(r"$\1", sql)


# ---------------------------------------------------------------------------
# Result normalization
# ---------------------------------------------------------------------------


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with ``Decimal`` columns converted to ``float64``.

    PostgreSQL returns ``NUMERIC`` as :class:`decimal.Decimal`, so those columns
    arrive as ``object`` dtype and behave subtly differently from floats:
    ``Decimal('NaN')`` is not recognised by :func:`pandas.isna`, and arithmetic
    on object columns is slower. Converting to ``float64`` gives the two engines
    one identical result type, which is what makes a Postgres/DuckDB parity test
    meaningful.
    """
    if df.empty:
        return df

    converted: dict[str, pd.Series] = {}
    for column in df.columns:
        series = df[column]
        if series.dtype == object and any(
            isinstance(value, Decimal) for value in series.dropna()
        ):
            converted[column] = series.astype("float64")

    if not converted:
        return df
    return df.assign(**converted)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class QueryBackend(ABC):
    """A read-only SQL engine the dashboard can run its queries against."""

    #: Short identifier used in the UI and in logs.
    kind: str

    @abstractmethod
    def execute(
        self, sql: str, params: dict[str, SqlParamValue] | None = None
    ) -> pd.DataFrame:
        """Run ``sql`` and return the result as a DataFrame."""

    @abstractmethod
    def describe(self) -> str:
        """Human-readable description of where the data comes from."""

    def close(self) -> None:  # pragma: no cover - default no-op
        """Release any resources held by the backend."""


class PostgresBackend(QueryBackend):
    """Reads the ``marts`` schema the ETL pipeline built in PostgreSQL."""

    kind = "postgres"

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def execute(
        self, sql: str, params: dict[str, SqlParamValue] | None = None
    ) -> pd.DataFrame:
        with self._engine.connect() as conn:
            frame = pd.read_sql(text(sql), conn, params=params or {})
        return normalize_frame(frame)

    def describe(self) -> str:
        url = self._engine.url
        return f"PostgreSQL {url.host}:{url.port}/{url.database}"

    def close(self) -> None:
        self._engine.dispose()


class DuckDbBackend(QueryBackend):
    """Reads the Parquet demo layer through DuckDB views.

    The layer is a directory of Parquet files (see :data:`DEMO_FILES`), not a
    DuckDB database file. DuckDB reads Parquet natively, so the views cost
    nothing to create and the committed artifact stays ~14 MB instead of the
    ~950 MB a materialised database would take.

    The connection is in-memory and shared, so it is guarded by a lock:
    Streamlit runs the script body on a worker thread and DuckDB connections are
    not safe to use concurrently.
    """

    kind = "duckdb"

    def __init__(self, demo_dir: Path) -> None:
        self._dir = demo_dir
        self._lock = threading.Lock()
        self._connection = duckdb.connect()
        self._register_views()

    def _register_views(self) -> None:
        """Create every demo schema and view over the Parquet layer."""
        for schema in DEMO_SCHEMAS:
            self._connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

        for qualified_name, filename in DEMO_FILES.items():
            path = self._dir / filename
            if not path.exists():
                raise BackendUnavailable(
                    f"Demo layer is incomplete: {path} is missing. "
                    "Rebuild it with: python -m scripts.build_demo_marts --force"
                )
            # The path is interpolated because DuckDB's read_parquet takes a
            # literal; it comes from config, not from user input.
            self._connection.execute(
                f"CREATE OR REPLACE VIEW {qualified_name} AS "
                f"SELECT * FROM read_parquet('{path.as_posix()}')"
            )

        self._connection.execute(DEMO_SUMMARY_VIEW_SQL)

    def execute(
        self, sql: str, params: dict[str, SqlParamValue] | None = None
    ) -> pd.DataFrame:
        translated = to_duckdb_sql(sql)
        with self._lock:
            frame = self._connection.execute(translated, params or {}).fetch_df()
        return normalize_frame(frame)

    def describe(self) -> str:
        return f"DuckDB demo layer ({self._dir})"

    def close(self) -> None:
        self._connection.close()


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def make_postgres_backend(config: AppConfig) -> PostgresBackend:
    """Build a PostgreSQL backend, failing fast when the server is unreachable."""
    engine = create_engine(
        config.database.url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": POSTGRES_CONNECT_TIMEOUT},
    )
    try:
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001 - any driver error means "unavailable"
        engine.dispose()
        raise BackendUnavailable(f"PostgreSQL unreachable: {exc}") from exc
    return PostgresBackend(engine)


def make_duckdb_backend(config: AppConfig) -> DuckDbBackend:
    """Build a DuckDB backend over the pre-built Parquet demo layer."""
    demo_dir = config.dashboard.demo_path
    if not demo_dir.is_dir():
        raise BackendUnavailable(
            f"DuckDB demo layer not found at {demo_dir}. "
            "Build it with: python -m scripts.build_demo_marts"
        )
    try:
        return DuckDbBackend(demo_dir)
    except duckdb.Error as exc:
        raise BackendUnavailable(f"DuckDB demo layer unusable: {exc}") from exc


def select_backend(config: AppConfig) -> QueryBackend:
    """Return the backend named by ``dashboard.source``.

    ``auto`` prefers PostgreSQL and silently falls back to DuckDB, which is what
    makes a fresh clone work without Docker. An explicit ``postgres`` or
    ``duckdb`` never falls back: if the configured engine is unavailable the
    error surfaces, so a misconfigured deployment is not hidden behind a demo
    dataset.
    """
    source = config.dashboard.source.lower()
    if source not in {"auto", "postgres", "duckdb"}:
        raise BackendUnavailable(
            f"Unknown dashboard.source '{config.dashboard.source}'. "
            "Valid values: auto, postgres, duckdb."
        )

    if source == "duckdb":
        return make_duckdb_backend(config)

    if source == "postgres":
        return make_postgres_backend(config)

    try:
        return make_postgres_backend(config)
    except BackendUnavailable as exc:
        logger.info("PostgreSQL unavailable (%s); using the DuckDB demo backend", exc)
        return make_duckdb_backend(config)


def backend_summary(backend: QueryBackend) -> dict[str, Any]:
    """Small dict describing the active backend, for the sidebar badge."""
    return {"kind": backend.kind, "description": backend.describe()}
