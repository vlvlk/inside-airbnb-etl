"""CSV extraction module for Airbnb data.

Reads the raw CSVs in chunks and hands each chunk back as a *normalized*
DataFrame (see :mod:`src.extract.normalize`). Normalization is fully
vectorized: there is no per-row Pydantic construction on the hot path, which
is what made a 330 MB calendar file crawl when it was validated row by row.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from src.config import get_config
from src.extract.normalize import (
    invalid_calendar_mask,
    invalid_listing_mask,
    normalize_calendar,
    normalize_listings,
)

logger = logging.getLogger(__name__)


class CSVExtractor:
    """Extracts and normalizes data from CSV files using pandas."""

    def __init__(self, config_path: Path | None = None):
        self.config = get_config(config_path)
        self.batch_size = self.config.pipeline.batch_size
        self.chunk_size = self.config.pipeline.chunk_size
        self.validate = self.config.pipeline.validate_data
        self.skip_invalid = self.config.pipeline.skip_invalid_rows

    def _read_chunks(self, path: Path) -> Iterator[pd.DataFrame]:
        """Stream a CSV as raw string chunks of ``chunk_size`` rows."""
        return pd.read_csv(
            path,
            chunksize=self.chunk_size,
            dtype=str,
            keep_default_na=False,
            na_values=["", "NA", "N/A", "null", "NULL"],
        )

    def _validate(
        self,
        chunk: pd.DataFrame,
        invalid_mask: pd.Series,
        label: str,
        chunk_num: int,
    ) -> pd.DataFrame:
        """Drop or reject rows flagged by ``invalid_mask``.

        With ``skip_invalid`` the bad rows are reported and removed; otherwise
        the first offending row aborts the run with a clear message.
        """
        if not invalid_mask.any():
            return chunk

        bad = int(invalid_mask.sum())
        if not self.skip_invalid:
            first_bad = int(invalid_mask.to_numpy().argmax())
            raise ValueError(
                f"Invalid {label} row in chunk {chunk_num + 1} "
                f"(row {first_bad}): required key could not be parsed"
            )

        logger.warning(
            f"Skipping {bad} invalid {label} row(s) in chunk {chunk_num + 1}"
        )
        return chunk.loc[~invalid_mask]

    def _load_batches(self, chunk: pd.DataFrame) -> Iterator[pd.DataFrame]:
        """Split a read chunk into ``batch_size`` slices for the loader.

        Reading happens in ``chunk_size`` blocks (fewer pandas passes), while
        loading happens in ``batch_size`` blocks (bounded COPY buffers).
        """
        for start in range(0, len(chunk), self.batch_size):
            yield chunk.iloc[start : start + self.batch_size]

    def extract_listings(self) -> Iterator[pd.DataFrame]:
        """Yield normalized listings DataFrames of at most ``batch_size`` rows."""
        path = self.config.data.listings_path
        logger.info(f"Extracting listings from {path}")

        if not path.exists():
            raise FileNotFoundError(f"Listings file not found: {path}")

        for chunk_num, chunk in enumerate(self._read_chunks(path)):
            logger.debug(
                f"Processing listings chunk {chunk_num + 1} ({len(chunk)} rows)"
            )
            if self.validate:
                chunk = self._validate(
                    chunk, invalid_listing_mask(chunk), "listing", chunk_num
                )
            for batch in self._load_batches(chunk):
                yield normalize_listings(batch)

    def extract_calendar(self) -> Iterator[pd.DataFrame]:
        """Yield normalized calendar DataFrames of at most ``batch_size`` rows."""
        path = self.config.data.calendar_path
        logger.info(f"Extracting calendar from {path}")

        if not path.exists():
            raise FileNotFoundError(f"Calendar file not found: {path}")

        for chunk_num, chunk in enumerate(self._read_chunks(path)):
            logger.debug(
                f"Processing calendar chunk {chunk_num + 1} ({len(chunk)} rows)"
            )
            if self.validate:
                chunk = self._validate(
                    chunk, invalid_calendar_mask(chunk), "calendar", chunk_num
                )
            for batch in self._load_batches(chunk):
                yield normalize_calendar(batch)

    def extract_all(
        self,
    ) -> tuple[Iterator[pd.DataFrame], Iterator[pd.DataFrame]]:
        """Extract both listings and calendar."""
        return self.extract_listings(), self.extract_calendar()


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
