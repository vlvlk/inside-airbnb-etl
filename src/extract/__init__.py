"""Extraction layer: pick a reader for the configured input format.

The bundled dataset is Parquet, but the CSV path is kept for anyone pointing the
config at the original ``csv.gz`` downloads. :func:`make_extractor` picks the
implementation from the configured file extension, so the pipeline stays
format-agnostic and no extra config key is needed.
"""

from __future__ import annotations

from pathlib import Path

from src.config import get_config
from src.extract.base import BaseExtractor
from src.extract.csv_extractor import CSVExtractor
from src.extract.parquet_extractor import ParquetExtractor

__all__ = [
    "BaseExtractor",
    "CSVExtractor",
    "ParquetExtractor",
    "make_extractor",
]


def make_extractor(config_path: Path | None = None) -> BaseExtractor:
    """Return the extractor matching the configured listings file extension.

    ``.parquet`` selects :class:`ParquetExtractor`; anything else falls back to
    :class:`CSVExtractor`, which also keeps ``.csv.gz`` working.
    """
    config = get_config(config_path)
    if config.data.listings_path.suffix == ".parquet":
        return ParquetExtractor(config_path)
    return CSVExtractor(config_path)
