"""Overview page: portfolio KPIs, occupancy trend, seasonality and revenue."""

from __future__ import annotations

import streamlit as st

from src.dashboard import data, ui

kpis = data.load_overall_kpis()
seasonality = data.load_seasonality()
years = data.available_years(kpis, seasonality)

if not years:
    st.warning(
        "No mart data found. Run the pipeline first: `python -m src.pipeline`.",
        icon=":material/warning:",
    )
    st.stop()

selected_years, granularity = ui.sidebar_filters(years, key_prefix="overview")

kpis = ui.apply_year_filter(kpis, selected_years)
period_rows = data.filter_granularity(kpis, granularity)
period_rows = data.add_period(period_rows).sort_values("period")

# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------

# Every KPI is summed over ``period_rows`` — the rows at the *selected*
# granularity — never over the whole frame. ``overall_kpis`` returns weekly,
# monthly, quarterly and yearly rows at once, so summing ``kpis`` directly would
# count the same nights three or four times over.
total_listings = (
    int(period_rows["total_listings"].max()) if not period_rows.empty else 0
)
total_nights = int(period_rows["total_nights"].sum())
booked_nights = int(period_rows["booked_nights"].sum())
occupancy = booked_nights / total_nights if total_nights else None
has_rev = "total_revenue" in period_rows and period_rows["total_revenue"].notna().any()
total_revenue = float(period_rows["total_revenue"].sum()) if has_rev else None
# ADR is revenue over booked nights, both taken from the revenue side: the
# revenue marts only cover priced listings, so averaging the per-period ADR or
# dividing by the wider occupancy denominator would understate the rate.
rev_booked = (
    int(period_rows["rev_booked_nights"].sum())
    if "rev_booked_nights" in period_rows
    and period_rows["rev_booked_nights"].notna().any()
    else 0
)
adr = total_revenue / rev_booked if total_revenue and rev_booked else None

with st.container(horizontal=True):
    st.metric("Listings", f"{total_listings:,}", border=True)
    st.metric("Occupancy rate", ui.format_occupancy(occupancy), border=True)
    st.metric("Booked nights", f"{booked_nights:,}", border=True)
    st.metric("Avg daily rate", ui.format_money(adr), border=True)
    st.metric("Total revenue", ui.format_money(total_revenue), border=True)

# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

if period_rows.empty:
    ui.render_empty_state(f"No {granularity} data for the selected years.")
else:
    row = st.columns(2)
    with row[0], st.container(border=True):
        st.subheader("Occupancy rate over time")
        st.altair_chart(
            ui.occupancy_trend_chart(period_rows, alt_text="Occupancy over time"),
            alt="Occupancy rate over time for the selected period",
        )
    with row[1], st.container(border=True):
        st.subheader("ADR and RevPAR over time")
        st.altair_chart(
            ui.revenue_trend_chart(period_rows, alt_text="ADR and RevPAR"),
            alt="Average daily rate and revenue per available night over time",
        )

# ---------------------------------------------------------------------------
# Seasonality
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("Seasonality by calendar month")
    if seasonality.empty:
        ui.render_empty_state("No monthly data available.")
    else:
        st.altair_chart(
            ui.seasonality_chart(seasonality, alt_text="Occupancy by month"),
            alt="Occupancy rate by calendar month, aggregated across all years",
        )

# ---------------------------------------------------------------------------
# Period table
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("Period detail")
    if period_rows.empty:
        ui.render_empty_state("Nothing to show for the current filters.")
    else:
        table = period_rows[
            [
                "year",
                "month",
                "quarter",
                "total_listings",
                "total_nights",
                "booked_nights",
                "occupancy_rate",
                "avg_daily_rate",
                "revenue_per_available_night",
                "total_revenue",
            ]
        ].copy()
        st.dataframe(
            table,
            hide_index=True,
            column_config=ui.occupancy_column_config(),
            alt="Portfolio metrics per period",
        )
        st.download_button(
            "Download CSV",
            data=table.to_csv(index=False).encode("utf-8"),
            file_name=f"overall_kpis_{granularity}.csv",
            mime="text/csv",
            icon=":material/download:",
        )

st.caption(
    f"Source: `marts.occupancy_by_listing` and `marts.revenue_by_listing` "
    f"({len(period_rows):,} rows at the selected granularity)."
)
