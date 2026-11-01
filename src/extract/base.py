"""Shared extraction logic for every input format.

The pipeline can read the same logical dataset from CSV or Parquet. Everything
except *how bytes become chunks* is identical: the pre-flight existence check,
the invalid-row policy, the read/load size split and the normalization step. That
common part lives here, so :class:`~src.extract.csv_extractor.CSVExtractor` and
:class:`~src.extract.parquet_extractor.ParquetExtractor` cannot drift apart.

Subclasses implement :meth:`BaseExtractor._read_chunks`; the public
``extract_listings`` / ``extract_calendar`` methods are inherited.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from src.config import AppConfig
from src.extract.normalize import (
    invalid_calendar_mask,
    invalid_listing_mask,
    normalize_calendar,
    normalize_listings,
)

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Reads raw data in chunks and yields normalized DataFrames.

    Normalization is fully vectorized (see :mod:`src.extract.normalize`): there
    is no per-row model construction on the hot path, which is what made a
    330 MB calendar file crawl when it was validated row by row.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.batch_size = config.pipeline.batch_size
        self.chunk_size = config.pipeline.chunk_size
        self.validate = config.pipeline.validate_data
        self.skip_invalid = config.pipeline.skip_invalid_rows

    @abstractmethod
    def _read_chunks(self, path: Path) -> Iterator[pd.DataFrame]:
        """Stream ``path`` as raw chunks of at most ``chunk_size`` rows."""

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
