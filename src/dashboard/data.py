"""Data access for the occupancy dashboard.

Every read goes through the pre-aggregated ``marts`` schema; the dashboard never
touches the raw layer. The SQL itself lives in ``sql/queries/*.sql`` so the same
statements can be run by hand with ``psql`` and reused outside the dashboard.

The engine behind those statements is chosen at runtime by
:mod:`src.dashboard.backend`: PostgreSQL when the pipeline has populated it,
otherwise a DuckDB file built from the bundled Parquet snapshot. Both execute
the same SQL files, so no query is duplicated. The backend is a cached resource
(one connection per Streamlit process) and each query is wrapped in
``st.cache_data``, so switching pages or changing filters does not re-query the
engine on every rerun.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from src.config import get_config
from src.dashboard.backend import (
    BackendUnavailable,
    QueryBackend,
    SqlParamValue,
    select_backend,
)

logger = logging.getLogger(__name__)

#: Directory holding the reusable, dashboard-facing SQL queries.
QUERIES_DIR = Path(__file__).resolve().parents[2] / "sql" / "queries"

#: Cache lifetime for query results.
CACHE_TTL = "10m"

__all__ = [
    "CACHE_TTL",
    "GRANULARITIES",
    "QUERIES_DIR",
    "SqlParamValue",
    "active_backend",
    "add_granularity",
    "add_period",
    "aggregate_by_category",
    "available_years",
    "filter_granularity",
    "get_backend",
    "load_data_quality",
    "load_host_segmentation",
    "load_listings",
    "load_neighbourhood_ranking",
    "load_neighbourhoods",
    "load_overall_kpis",
    "load_price_vs_occupancy",
    "load_revenue",
    "load_room_types",
    "load_seasonality",
    "load_top_listings",
    "run_query",
]


@st.cache_resource(show_spinner=False)
def get_backend() -> QueryBackend | None:
    """Return the process-wide query backend, or ``None`` when none is usable.

    Returning ``None`` instead of raising keeps the pages in charge of the empty
    state: they already render a "run the pipeline first" warning when a loader
    comes back empty, which is exactly the right message when neither PostgreSQL
    nor the DuckDB demo file is available.
    """
    try:
        return select_backend(get_config())
    except BackendUnavailable as exc:
        logger.warning("No dashboard backend available: %s", exc)
        return None


def active_backend() -> QueryBackend | None:
    """Return the active backend for display purposes (``None`` if unavailable)."""
    return get_backend()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def run_query(
    name: str, params: dict[str, SqlParamValue] | None = None
) -> pd.DataFrame:
    """Run the named query from :data:`QUERIES_DIR` and return a DataFrame.

    Parameters
    ----------
    name:
        File stem of the SQL file, e.g. ``"overall_kpis"``.
    params:
        Optional bind parameters (e.g. ``{"limit": 20}``) for ``:name`` markers.

    Returns an empty frame when no backend is available, so the caller's empty
    state handles it. A genuine query error still propagates.
    """
    backend = get_backend()
    if backend is None:
        return pd.DataFrame()
    sql = (QUERIES_DIR / f"{name}.sql").read_text(encoding="utf-8")
    return backend.execute(sql, params)


# ---------------------------------------------------------------------------
# Typed loaders (one per query file)
# ---------------------------------------------------------------------------


def load_overall_kpis() -> pd.DataFrame:
    """Portfolio KPIs per period, with a ``granularity`` column."""
    return run_query("overall_kpis")


def load_neighbourhoods() -> pd.DataFrame:
    """Occupancy and price per neighbourhood, all granularities."""
    return run_query("occupancy_by_neighbourhood")


def load_room_types() -> pd.DataFrame:
    """Occupancy and price per room type, all granularities."""
    return run_query("occupancy_by_room_type")


def load_listings() -> pd.DataFrame:
    """Occupancy per listing, all granularities."""
    return run_query("occupancy_by_listing")


def load_revenue() -> pd.DataFrame:
    """Revenue metrics (ADR, RevPAR) per listing, all granularities."""
    return run_query("revenue_by_listing")


def load_top_listings(limit: int = 20) -> pd.DataFrame:
    """Top listings by RevPAR within each month."""
    return run_query("top_listings_by_revpar", {"limit": int(limit)})


def load_seasonality() -> pd.DataFrame:
    """Occupancy collapsed by calendar month across all years."""
    return run_query("seasonality")


def load_neighbourhood_ranking() -> pd.DataFrame:
    """Neighbourhood leaderboard per year (yearly rows only)."""
    return run_query("neighbourhood_ranking")


def load_price_vs_occupancy() -> pd.DataFrame:
    """Price vs. occupancy by room type and month."""
    return run_query("price_vs_occupancy")


def load_host_segmentation() -> pd.DataFrame:
    """Occupancy, price and revenue by host portfolio size."""
    return run_query("host_segmentation")


def load_data_quality() -> pd.DataFrame:
    """Layer counts and data quality checks (reads raw, staging and marts)."""
    return run_query("data_quality")


# ---------------------------------------------------------------------------
# Granularity helpers
# ---------------------------------------------------------------------------

#: Granularity levels in coarse-to-fine order.
GRANULARITIES: tuple[str, ...] = ("year", "quarter", "month", "week")


def add_granularity(df: pd.DataFrame) -> pd.DataFrame:
    """Derive a ``granularity`` label from the period columns.

    The marts encode the period by leaving finer columns ``NULL`` (a monthly row
    has ``week_of_year IS NULL``; a yearly row has ``month``, ``week_of_year``
    and ``quarter`` all ``NULL``), so the level is inferred rather than stored.
    """
    if df.empty:
        return df.assign(granularity=pd.Series(dtype="object"))

    df = df.copy()
    has_week = "week_of_year" in df.columns
    conditions = [df["month"].notna()]
    choices = ["month"]
    if has_week:
        conditions.append(df["week_of_year"].notna())
        choices.append("week")
    conditions.append(df["quarter"].notna())
    choices.append("quarter")
    df["granularity"] = np.select(conditions, choices, default="year")
    return df


def filter_granularity(df: pd.DataFrame, level: str) -> pd.DataFrame:
    """Keep only rows at ``level`` (one of :data:`GRANULARITIES`)."""
    if "granularity" not in df.columns:
        df = add_granularity(df)
    return df[df["granularity"] == level]


def add_period(df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``period`` datetime column for trend charts.

    Monthly and quarterly rows use the first day of the month/quarter. Weekly
    rows (``month IS NULL``) are dated from the ISO week, so the weekly
    granularity also plots on a real time axis instead of ``NaT``.
    """
    df = df.copy()
    if "month" in df.columns:
        # ``to_datetime`` expects a frame of date parts, not a dict of series,
        # and the frame must carry nothing but year/month/day.
        period = pd.to_datetime(df[["year", "month"]].assign(day=1), errors="coerce")
        if "week_of_year" in df.columns:
            weekly = df["month"].isna() & df["week_of_year"].notna()
            if weekly.any():
                # Nullable integers keep the ISO week text stable when the
                # source column is a float (NULLs become float64 in pandas).
                year_text = df["year"].loc[weekly].astype("Int64").astype(str)
                week_text = (
                    df["week_of_year"]
                    .loc[weekly]
                    .astype("Int64")
                    .astype(str)
                    .str.zfill(2)
                )
                week_start = pd.to_datetime(
                    year_text + "-W" + week_text + "-1",
                    format="%G-W%V-%u",
                    errors="coerce",
                )
                period = period.copy()
                period.loc[weekly] = week_start
        df["period"] = period
    return df


def available_years(*frames: pd.DataFrame) -> list[int]:
    """Return the sorted union of years across the given frames."""
    years: set[int] = set()
    for frame in frames:
        if not frame.empty and "year" in frame.columns:
            years.update(int(y) for y in frame["year"].dropna().unique())
    return sorted(years)


def aggregate_by_category(
    df: pd.DataFrame,
    *,
    category_col: str,
    value_col: str = "occupancy_rate",
    weight_col: str = "total_nights",
    booked_col: str = "booked_nights",
    price_col: str = "avg_price_per_night",
    listings_col: str = "total_listings",
) -> pd.DataFrame:
    """Aggregate a granularity-filtered frame by category, computing weighted metrics.

    The marts store one row per (category, period). This function collapses across
    periods so that each category appears once with:
    - ``value_col`` recomputed as ``sum(booked_col) / sum(weight_col)`` (weighted rate)
    - ``price_col`` as the mean of the period-level averages
    - ``listings_col`` as the max across periods (stable identifier)

    Parameters
    ----------
    df:
        Frame already filtered to a single granularity (e.g. monthly rows only).
    category_col:
        Column to group by (``neighbourhood_cleansed`` or ``room_type``).
    value_col:
        Name of the rate column to recompute (default ``occupancy_rate``).
    weight_col:
        Denominator column for the weighted rate (default ``total_nights``).
    booked_col:
        Numerator column for the weighted rate (default ``booked_nights``).
    price_col:
        Price column to average (default ``avg_price_per_night``).
    listings_col:
        Listings column to take the max of (default ``total_listings``).

    Returns
    -------
    DataFrame with one row per category and the aggregated columns.
    """
    if df.empty:
        return df

    required = {category_col, weight_col, booked_col}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise ValueError(f"Missing required columns for aggregation: {missing}")

    agg_dict = {
        weight_col: "sum",
        booked_col: "sum",
    }
    optional = {}
    if price_col in df.columns:
        optional[price_col] = "mean"
    if listings_col in df.columns:
        optional[listings_col] = "max"

    grouped = df.groupby(category_col, as_index=False).agg({**agg_dict, **optional})
    grouped[value_col] = grouped[booked_col] / grouped[weight_col]
    return grouped
