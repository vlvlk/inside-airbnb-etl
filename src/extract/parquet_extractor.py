"""Parquet extraction for the bundled dataset.

The repository ships the Toronto snapshot as Parquet (see
``scripts/csv_to_parquet.py``), so a fresh clone can run the pipeline without
network access. This extractor reads those files back with the exact same
contract as :class:`~src.extract.csv_extractor.CSVExtractor`.

Reading goes through Parquet row groups rather than loading the whole file: the
calendar holds 8M rows (~282 MB in memory), and the CSV path deliberately reads
in chunks for the same reason.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from src.config import get_config
from src.extract.base import BaseExtractor

logger = logging.getLogger(__name__)


class ParquetExtractor(BaseExtractor):
    """Extracts and normalizes data from Parquet files using pyarrow."""

    def __init__(self, config_path: Path | None = None):
        super().__init__(get_config(config_path))

    def _read_chunks(self, path: Path) -> Iterator[pd.DataFrame]:
        """Stream a Parquet file as chunks of at most ``chunk_size`` rows.

        ``iter_batches`` walks the file row group by row group, so peak memory
        stays proportional to ``chunk_size`` instead of the file size. Values
        arrive already typed (``int64``, ``datetime64``, ``bool``); the
        normalizer coerces them to the raw layer's text representation, so no
        casting is needed here.
        """
        parquet_file = pq.ParquetFile(path)
        for batch in parquet_file.iter_batches(batch_size=self.chunk_size):
            yield batch.to_pandas()
