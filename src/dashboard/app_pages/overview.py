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

total_listings = int(kpis["total_listings"].max()) if not kpis.empty else 0
total_nights = int(kpis["total_nights"].sum())
booked_nights = int(kpis["booked_nights"].sum())
occupancy = booked_nights / total_nights if total_nights else None
total_revenue = float(kpis["total_revenue"].sum()) if "total_revenue" in kpis else None
adr = (
    float(kpis["avg_daily_rate"].dropna().mean())
    if "avg_daily_rate" in kpis and kpis["avg_daily_rate"].notna().any()
    else None
)

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
    f"({len(kpis):,} aggregated rows loaded)."
)
