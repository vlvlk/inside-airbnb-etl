"""Reusable UI helpers: sidebar filters, formatting and Altair chart builders.

Kept separate from :mod:`src.dashboard.data` so the data layer stays free of
Streamlit layout concerns and the chart definitions can be unit-tested.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st
from streamlit.elements.lib.column_config_utils import ColumnConfigMappingInput

from src.dashboard.data import GRANULARITIES

#: Shared chart height so cards line up in a row.
CHART_HEIGHT = 320

#: Occupancy is stored as a fraction in [0, 1]; charts show it as a percentage.
OCCUPANCY_AXIS = alt.Axis(format="%", title="Occupancy rate")

#: Host-portfolio segments in the order they should read on a chart.
HOST_SEGMENT_ORDER: tuple[str, ...] = (
    "Single listing",
    "Small portfolio (2-4 listings)",
    "Professional (5+ listings)",
)

#: Month number -> short English month name, used for chart axes and labels.
MONTH_NAMES: dict[int, str] = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


def sidebar_filters(
    years: list[int],
    *,
    key_prefix: str,
    granularities: tuple[str, ...] = GRANULARITIES,
    default_granularity: str = "month",
) -> tuple[list[int], str]:
    """Render the shared year/granularity filters in the sidebar.

    Returns the selected years and the selected granularity level.
    """
    with st.sidebar:
        st.markdown("**Filters**")
        selected_years = st.multiselect(
            "Year",
            options=years,
            default=years,
            key=f"{key_prefix}_years",
            help="Restrict every chart and table on this page to these years.",
        )
        granularity = st.segmented_control(
            "Granularity",
            options=list(granularities),
            default=default_granularity,
            key=f"{key_prefix}_granularity",
        )
    return selected_years, granularity or default_granularity


def apply_year_filter(df: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """Keep rows whose ``year`` is in ``years`` (no-op when nothing is selected)."""
    if df.empty or not years:
        return df
    return df[df["year"].isin(years)]


def format_occupancy(value: float | None) -> str:
    """Format an occupancy fraction as a percentage string."""
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.1%}"


def format_money(value: float | None, currency: str = "$") -> str:
    """Format a monetary value with thousands separators."""
    if value is None or pd.isna(value):
        return "n/a"
    return f"{currency}{value:,.0f}"


#: Identifier columns. They are 64-bit integers in the warehouse, but their
#: values routinely exceed JavaScript's ``Number.MAX_SAFE_INTEGER`` (2**53 - 1).
#: Streamlit then renders them as error cells ("larger than the maximum
#: supported integer values in number columns") and aligns them inconsistently
#: with the safe ones, so they are cast to text before display.
ID_COLUMNS: tuple[str, ...] = ("listing_id", "host_id")


def stringify_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with any identifier column cast to text.

    ``listing_id`` and ``host_id`` are opaque identifiers, not quantities. Casting
    them to text keeps every digit exact (a Python ``int`` to ``str`` conversion
    loses nothing) and lets the dataframe render them as plain, left-aligned
    text instead of flagging the values above 2**53 - 1 as errors. The function
    is a no-op when the frame carries none of :data:`ID_COLUMNS`.
    """
    present = [col for col in ID_COLUMNS if col in df.columns]
    if not present:
        return df
    df = df.copy()
    for col in present:
        df[col] = df[col].astype("string")
    return df


def occupancy_trend_chart(df: pd.DataFrame, *, alt_text: str) -> alt.Chart:
    """Line chart of occupancy rate over time."""
    chart: alt.Chart = (
        alt.Chart(df)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("period:T", title=None),
            y=alt.Y("occupancy_rate:Q", axis=OCCUPANCY_AXIS),
            tooltip=[
                alt.Tooltip("period:T", title="Period", format="%b %Y"),
                alt.Tooltip("occupancy_rate:Q", title="Occupancy", format=".1%"),
                alt.Tooltip("booked_nights:Q", title="Booked nights", format=","),
                alt.Tooltip("total_listings:Q", title="Listings", format=","),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )
    return chart


def revenue_trend_chart(df: pd.DataFrame, *, alt_text: str) -> alt.Chart:
    """Line chart of ADR and RevPAR over time (two series)."""
    melted = df.melt(
        id_vars=["period"],
        value_vars=["avg_daily_rate", "revenue_per_available_night"],
        var_name="metric",
        value_name="value",
    )
    labels = {
        "avg_daily_rate": "ADR",
        "revenue_per_available_night": "RevPAR",
    }
    melted["metric"] = melted["metric"].map(labels)
    chart: alt.Chart = (
        alt.Chart(melted)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("period:T", title=None),
            y=alt.Y("value:Q", title="Price per night ($)"),
            color=alt.Color("metric:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=[
                alt.Tooltip("period:T", title="Period", format="%b %Y"),
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("value:Q", title="Value", format="$,.0f"),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )
    return chart


def seasonality_chart(df: pd.DataFrame, *, alt_text: str) -> alt.Chart:
    """Bar chart of occupancy by calendar month."""
    chart_df = df.copy()
    # Nullable integers keep the mapping total: a NULL month stays missing
    # instead of raising while casting float64 to a plain integer dtype.
    chart_df["month_name"] = chart_df["month"].astype("Int64").map(MONTH_NAMES)
    chart: alt.Chart = (
        alt.Chart(chart_df)
        .mark_bar()
        .encode(
            x=alt.X("month_name:N", title=None, sort=list(MONTH_NAMES.values())),
            y=alt.Y("occupancy_rate:Q", axis=OCCUPANCY_AXIS),
            tooltip=[
                alt.Tooltip("month_name:N", title="Month"),
                alt.Tooltip("occupancy_rate:Q", title="Occupancy", format=".1%"),
                alt.Tooltip("booked_nights:Q", title="Booked nights", format=","),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )
    return chart


def ranking_bar_chart(
    df: pd.DataFrame,
    *,
    category_col: str,
    value_col: str,
    alt_text: str,
    top_n: int = 15,
) -> alt.Chart:
    """Horizontal bar chart ranking categories by a value."""
    top = df.nlargest(top_n, value_col)
    chart: alt.Chart = (
        alt.Chart(top)
        .mark_bar()
        .encode(
            y=alt.Y(f"{category_col}:N", title=None, sort="-x"),
            x=alt.X(f"{value_col}:Q", axis=OCCUPANCY_AXIS),
            tooltip=[
                alt.Tooltip(f"{category_col}:N", title="Category"),
                alt.Tooltip(f"{value_col}:Q", title="Occupancy", format=".1%"),
            ],
        )
        .properties(height=max(CHART_HEIGHT, 22 * len(top)))
    )
    return chart


def grouped_bar_chart(
    df: pd.DataFrame,
    *,
    category_col: str,
    value_col: str,
    group_col: str,
    value_axis: alt.Axis = OCCUPANCY_AXIS,
    value_format: str = ".1%",
    value_title: str = "Occupancy",
    category_order: tuple[str, ...] | None = None,
) -> alt.Chart:
    """Grouped bar chart: one bar per (category, group) pair.

    Used for the host-segment comparison, where each segment carries one bar per
    year. ``category_order`` pins the segment order so the chart reads from the
    smallest host to the largest instead of sorting alphabetically.
    """
    chart: alt.Chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(
                f"{category_col}:N",
                title=None,
                sort=list(category_order) if category_order is not None else None,
            ),
            xOffset=alt.XOffset(f"{group_col}:N"),
            y=alt.Y(f"{value_col}:Q", axis=value_axis),
            color=alt.Color(f"{group_col}:N", title=None),
            tooltip=[
                alt.Tooltip(f"{category_col}:N", title="Segment"),
                alt.Tooltip(f"{group_col}:N", title="Year"),
                alt.Tooltip(f"{value_col}:Q", title=value_title, format=value_format),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )
    return chart


def price_vs_occupancy_chart(
    df: pd.DataFrame,
    *,
    color_col: str,
    alt_text: str,
) -> alt.Chart:
    """Scatter plot of average price against occupancy rate."""
    chart: alt.Chart = (
        alt.Chart(df)
        .mark_circle(size=90, opacity=0.7)
        .encode(
            x=alt.X("avg_price_per_night:Q", title="Average price per night ($)"),
            y=alt.Y("occupancy_rate:Q", axis=OCCUPANCY_AXIS),
            color=alt.Color(f"{color_col}:N", title=None),
            tooltip=[
                alt.Tooltip(f"{color_col}:N", title="Category"),
                alt.Tooltip("period:T", title="Period", format="%b %Y"),
                alt.Tooltip("avg_price_per_night:Q", title="Price", format="$,.0f"),
                alt.Tooltip("occupancy_rate:Q", title="Occupancy", format=".1%"),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )
    return chart


def occupancy_column_config() -> ColumnConfigMappingInput:
    """Column configuration shared by the occupancy tables."""
    return {
        "listing_id": st.column_config.TextColumn("Listing ID"),
        "host_id": st.column_config.TextColumn("Host ID"),
        "occupancy_rate": st.column_config.NumberColumn("Occupancy", format="percent"),
        "avg_price_per_night": st.column_config.NumberColumn(
            "Avg price", format="$%.2f"
        ),
        "avg_daily_rate": st.column_config.NumberColumn("ADR", format="$%.2f"),
        "revenue_per_available_night": st.column_config.NumberColumn(
            "RevPAR", format="$%.2f"
        ),
        "total_revenue": st.column_config.NumberColumn("Revenue", format="$%.2f"),
        "total_nights": st.column_config.NumberColumn("Nights", format="%d"),
        "available_nights": st.column_config.NumberColumn("Available", format="%d"),
        "booked_nights": st.column_config.NumberColumn("Booked", format="%d"),
        "total_listings": st.column_config.NumberColumn("Listings", format="%d"),
        "month": st.column_config.NumberColumn("Month", format="%d"),
        "week_of_year": st.column_config.NumberColumn("Week", format="%d"),
        "quarter": st.column_config.NumberColumn("Quarter", format="%d"),
        "year": st.column_config.NumberColumn("Year", format="%d"),
    }


def render_empty_state(message: str) -> None:
    """Show a friendly empty state instead of an empty chart."""
    st.info(message, icon=":material/info:")
