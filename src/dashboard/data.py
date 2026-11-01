"""Data access for the occupancy dashboard.

Every read goes through the pre-aggregated ``marts`` schema; the dashboard never
touches the raw layer. The SQLAlchemy engine is a cached resource (one
connection pool per Streamlit process) and each query is wrapped in
``st.cache_data``, so switching pages or changing filters does not re-query
Postgres on every rerun.

The SQL itself lives in ``sql/queries/*.sql`` so the same statements can be run
by hand with ``psql`` and reused outside the dashboard.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import TypeAlias

import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.config import get_config

#: Directory holding the reusable, dashboard-facing SQL queries.
QUERIES_DIR = Path(__file__).resolve().parents[2] / "sql" / "queries"

#: Cache lifetime for query results.
CACHE_TTL = "10m"

#: Scalar values accepted as SQL bind parameters by :func:`run_query`.
SqlParamValue: TypeAlias = str | bytes | date | timedelta | bool | int | float | None


@st.cache_resource
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine for the configured database."""
    return create_engine(get_config().database.url, pool_pre_ping=True)


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
    """
    sql = (QUERIES_DIR / f"{name}.sql").read_text(encoding="utf-8")
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


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
