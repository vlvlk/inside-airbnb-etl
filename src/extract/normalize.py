"""Vectorized CSV normalization.

Replaces the row-by-row Pydantic validation loop with pandas column
operations, so a 330 MB calendar file is cleaned in a handful of vectorized
passes instead of millions of Python-level model constructions.

The output is a DataFrame whose columns match the raw layer DDL exactly and
whose values are already Postgres-friendly text (``'t'``/``'f'`` flags, ISO
dates, plain numbers, ``NA`` for NULLs), which lets the loader stream it
straight into ``COPY ... FROM STDIN``.

The field groups driving the transforms live next to the Pydantic models
(:mod:`src.models.listing`, :mod:`src.models.calendar`), so the two paths can
never drift apart.
"""

from __future__ import annotations

import logging

import pandas as pd

from src.models.calendar import (
    CALENDAR_BOOL_STR_FIELDS,
    CALENDAR_FIELDS,
    CALENDAR_INT_FIELDS,
)
from src.models.listing import (
    LISTING_BOOL_STR_FIELDS,
    LISTING_DATE_FIELDS,
    LISTING_DECIMAL_FIELDS,
    LISTING_FIELDS,
    LISTING_INT_FIELDS,
    LISTING_STR_FIELDS,
)

logger = logging.getLogger(__name__)

#: Values that the ``'t'``/``'f'`` normalizer treats as ``True``.
_TRUTHY = ("t", "true", "1", "yes", "y")


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    """Return ``frame[name]`` as a ``Series``.

    ``reindex`` guarantees the column exists, so the value is always 1-D; the
    cast only silences pandas' ``Series | DataFrame`` return annotation.
    """
    return frame[name]  # type: ignore[return-value]


def _as_series(value: object) -> pd.Series:
    """Cast a pandas result back to ``Series`` for the type checker."""
    return value  # type: ignore[return-value]


def _as_text(series: pd.Series) -> pd.Series:
    """Return the column as stripped nullable strings (``NaN`` -> ``pd.NA``)."""
    return series.astype("string").str.strip()


def _to_flag(series: pd.Series) -> pd.Series:
    """Normalize a column to the canonical ``'t'``/``'f'`` text flag.

    Mirrors ``ListingRaw.parse_bool_str``: missing cells become ``NA``,
    anything truthy becomes ``'t'`` and every other value becomes ``'f'``.
    """
    text = _as_text(series).str.lower()
    missing = text.isna() | text.eq("")
    flags = text.isin(_TRUTHY).map({True: "t", False: "f"}).astype("string")
    return flags.where(~missing, other=pd.NA)


def _to_date(series: pd.Series) -> pd.Series:
    """Parse ISO dates, emitting ``YYYY-MM-DD`` text and ``NA`` when invalid."""
    parsed = pd.to_datetime(series, errors="coerce")
    formatted = _as_series(parsed.dt.strftime("%Y-%m-%d"))
    return formatted.astype("string")


def _to_decimal_text(series: pd.Series) -> pd.Series:
    """Strip currency symbols/commas, keeping the original text when numeric.

    Non-numeric cells (and empty ones) become ``NA`` so Postgres stores NULL
    instead of failing the ``COPY``.
    """
    cleaned = (
        series.astype("string")
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    numeric = _as_series(pd.to_numeric(cleaned, errors="coerce"))
    return cleaned.where(pd.notna(numeric), other=pd.NA)


def _to_int_text(series: pd.Series) -> pd.Series:
    """Coerce a column to whole numbers, truncating like ``int(float(v))``."""
    cleaned = series.astype("string").str.replace(",", "", regex=False).str.strip()
    numeric = _as_series(pd.to_numeric(cleaned, errors="coerce"))
    # ``astype("Int64")`` truncates toward zero, matching ``int(float(v))``.
    return numeric.astype("Int64").astype("string")


def _numeric_ids(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.replace(",", "", regex=False).str.strip()
    return _as_series(pd.to_numeric(cleaned, errors="coerce"))


def normalize_listings(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` reindexed to the raw DDL columns and fully normalized."""
    src = df.reindex(columns=list(LISTING_FIELDS))
    columns: dict[str, pd.Series] = {}

    for col in LISTING_FIELDS:
        series = _column(src, col)
        if col in LISTING_STR_FIELDS:
            columns[col] = series.astype("string")
        elif col in LISTING_DATE_FIELDS:
            columns[col] = _to_date(series)
        elif col in LISTING_DECIMAL_FIELDS:
            columns[col] = _to_decimal_text(series)
        elif col in LISTING_INT_FIELDS:
            columns[col] = _to_int_text(series)
        elif col in LISTING_BOOL_STR_FIELDS:
            columns[col] = _to_flag(series)
        else:  # pragma: no cover - every field belongs to exactly one group
            columns[col] = series.astype("string")

    return pd.DataFrame(columns, index=df.index)


def normalize_calendar(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` reindexed to the raw calendar columns and normalized."""
    src = df.reindex(columns=list(CALENDAR_FIELDS))
    columns: dict[str, pd.Series] = {}

    for col in CALENDAR_FIELDS:
        series = _column(src, col)
        if col == "date":
            columns[col] = _to_date(series)
        elif col in CALENDAR_BOOL_STR_FIELDS:
            columns[col] = _to_flag(series)
        else:  # listing_id and the CALENDAR_INT_FIELDS night columns
            assert col in CALENDAR_INT_FIELDS or col == "listing_id"
            columns[col] = _to_int_text(series)

    return pd.DataFrame(columns, index=df.index)


def invalid_listing_mask(df: pd.DataFrame) -> pd.Series:
    """Boolean mask of rows whose required ``id`` cannot be parsed."""
    return _numeric_ids(_column(df, "id")).isna()


def invalid_calendar_mask(df: pd.DataFrame) -> pd.Series:
    """Boolean mask of rows with an unparseable ``listing_id`` or ``date``."""
    ids = _numeric_ids(_column(df, "listing_id"))
    dates = pd.to_datetime(_column(df, "date"), errors="coerce")
    return ids.isna() | dates.isna()
