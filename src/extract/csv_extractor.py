"""CSV extraction for Airbnb data.

Only the chunk reader lives here; validation, batching and normalization are
shared with the Parquet path via :class:`~src.extract.base.BaseExtractor`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from src.config import get_config
from src.extract.base import BaseExtractor

logger = logging.getLogger(__name__)


class CSVExtractor(BaseExtractor):
    """Extracts and normalizes data from CSV files using pandas."""

    def __init__(self, config_path: Path | None = None):
        super().__init__(get_config(config_path))

    def _read_chunks(self, path: Path) -> Iterator[pd.DataFrame]:
        """Stream a CSV as raw string chunks of ``chunk_size`` rows."""
        return pd.read_csv(
            path,
            chunksize=self.chunk_size,
            dtype=str,
            keep_default_na=False,
            na_values=["", "NA", "N/A", "null", "NULL"],
        )


def extract_listings_df(path: Path | None = None) -> pd.DataFrame:
    """Convenience function to extract listings as a DataFrame."""
    config = get_config()
    listings_path = path or config.data.listings_path
    return pd.read_csv(listings_path, dtype=str, keep_default_na=False)


def extract_calendar_df(path: Path | None = None) -> pd.DataFrame:
    """Convenience function to extract calendar as a DataFrame."""
    config = get_config()
    calendar_path = path or config.data.calendar_path
    return pd.read_csv(calendar_path, dtype=str, keep_default_na=False)
