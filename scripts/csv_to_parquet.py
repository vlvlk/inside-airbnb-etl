"""Convert Inside Airbnb CSV (optionally gzipped) into Parquet artifacts.

The repository ships the Toronto snapshot as Parquet so a fresh clone can run
the pipeline without network access. This utility rebuilds those artifacts from
the original ``csv.gz`` downloads, for example after refreshing the snapshot.

Usage::

    python scripts/csv_to_parquet.py
    python scripts/csv_to_parquet.py --listings data/raw/listings.csv.gz \\
        --calendar data/raw/calendar.csv.gz

The conversion is deliberately asymmetric:

* ``listings`` is read as text (``dtype=str``) and written verbatim, so the raw
  layer stays a 1:1 copy of the CSV — all 90 columns, no type coercion.
* ``calendar`` is read with explicit narrow dtypes. It holds 8M rows, and typing
  ``listing_id``/``date``/``available`` is what shrinks it ~9x versus ``csv.gz``.
  It is streamed in chunks so peak memory stays bounded.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

#: Rows per Parquet row group. Matches ``pipeline.chunk_size`` so the reader
#: holds roughly the same amount of data in memory as the CSV path.
ROW_GROUP_SIZE = 250_000

#: Rows read from the CSV per pandas pass during conversion.
READ_CHUNK_SIZE = 500_000

#: Parquet codec and level. zstd-19 is what gets the calendar down to ~2 MB.
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 19

#: Explicit dtypes for the calendar file. ``date`` is parsed separately because
#: it is not a pandas read_csv dtype.
CALENDAR_DTYPES: dict[str, str] = {
    "listing_id": "int64",
    "available": "string",
    "minimum_nights": "Int32",
    "maximum_nights": "Int32",
}


def _default_path(name: str) -> Path:
    """Return the default input path for ``name`` (``data/raw/<name>.csv.gz``)."""
    return Path("data/raw") / f"{name}.csv.gz"


def _parquet_path(src: Path) -> Path:
    """Map ``listings.csv.gz`` / ``listings.csv`` to ``listings.parquet``."""
    return src.with_name(f"{src.name.split('.')[0]}.parquet")


def convert_listings(src: Path, dst: Path) -> None:
    """Write every listing column to Parquet, preserving the CSV 1:1 as text."""
    logger.info("Reading listings from %s", src)
    frame = pd.read_csv(src, dtype=str, keep_default_na=False)
    logger.info("Listings: %s rows, %s columns", *frame.shape)

    frame.to_parquet(
        dst,
        engine="pyarrow",
        compression=COMPRESSION,
        compression_level=COMPRESSION_LEVEL,
        index=False,
    )
    logger.info("Wrote %s (%.2f MB)", dst, dst.stat().st_size / 1e6)


def convert_calendar(src: Path, dst: Path) -> None:
    """Stream the calendar into Parquet row groups, keeping memory bounded."""
    logger.info("Reading calendar from %s", src)
    reader = pd.read_csv(src, dtype=CALENDAR_DTYPES, chunksize=READ_CHUNK_SIZE)

    writer: pq.ParquetWriter | None = None
    total = 0
    try:
        for chunk in reader:
            chunk["date"] = pd.to_datetime(chunk["date"])
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(
                    dst,
                    table.schema,
                    compression=COMPRESSION,
                    compression_level=COMPRESSION_LEVEL,
                )
            writer.write_table(table, row_group_size=ROW_GROUP_SIZE)
            total += len(chunk)
    finally:
        if writer is not None:
            writer.close()

    logger.info(
        "Calendar: %s rows -> %s (%.2f MB)", total, dst, dst.stat().st_size / 1e6
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert Inside Airbnb CSV files into Parquet artifacts."
    )
    parser.add_argument(
        "--listings",
        type=Path,
        default=_default_path("listings"),
        help="Path to listings CSV (default: data/raw/listings.csv.gz)",
    )
    parser.add_argument(
        "--calendar",
        type=Path,
        default=_default_path("calendar"),
        help="Path to calendar CSV (default: data/raw/calendar.csv.gz)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Convert both files and return a process exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    args = parse_args(argv)

    for src in (args.listings, args.calendar):
        if not src.exists():
            logger.error("Input file not found: %s", src)
            return 1

    convert_listings(args.listings, _parquet_path(args.listings))
    convert_calendar(args.calendar, _parquet_path(args.calendar))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
