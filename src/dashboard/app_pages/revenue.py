"""Revenue page: ADR, RevPAR and top-earning listings."""

from __future__ import annotations

import streamlit as st

from src.dashboard import data, ui

revenue = data.load_revenue()
years = data.available_years(revenue)

if not years:
    st.warning(
        "No mart data found. Run the pipeline first: `python -m src.pipeline`.",
        icon=":material/warning:",
    )
    st.stop()

# marts.revenue_by_listing has no week_of_year column, so weekly granularity is
# not offered here.
selected_years, granularity = ui.sidebar_filters(
    years, key_prefix="revenue", granularities=("year", "quarter", "month")
)

period_rows = data.filter_granularity(revenue, granularity)
period_rows = ui.apply_year_filter(period_rows, selected_years)

# Aggregate listing rows up to a portfolio-level time series.
portfolio = (
    period_rows.groupby(["year", "month", "quarter"], dropna=False)
    .agg(
        total_revenue=("total_revenue", "sum"),
        booked_nights=("booked_nights", "sum"),
        available_nights=("available_nights", "sum"),
    )
    .reset_index()
)
portfolio = data.add_period(portfolio)
portfolio["avg_daily_rate"] = portfolio["total_revenue"] / portfolio[
    "booked_nights"
].replace(0, None)
portfolio["revenue_per_available_night"] = portfolio["total_revenue"] / portfolio[
    "available_nights"
].replace(0, None)
portfolio = portfolio.sort_values("period")

# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------

total_revenue = float(period_rows["total_revenue"].sum())
booked = int(period_rows["booked_nights"].sum())
available = int(period_rows["available_nights"].sum())
adr = total_revenue / booked if booked else None
revpar = total_revenue / available if available else None
occupancy = booked / available if available else None

with st.container(horizontal=True):
    st.metric("Total revenue", ui.format_money(total_revenue), border=True)
    st.metric("ADR", ui.format_money(adr), border=True)
    st.metric("RevPAR", ui.format_money(revpar), border=True)
    st.metric("Occupancy rate", ui.format_occupancy(occupancy), border=True)

# ---------------------------------------------------------------------------
# Revenue trend
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("ADR and RevPAR over time")
    if portfolio.empty:
        ui.render_empty_state("No revenue data for the current filters.")
    else:
        st.altair_chart(
            ui.revenue_trend_chart(portfolio, alt_text="ADR and RevPAR trend"),
            alt="Average daily rate and revenue per available night over time",
        )

# ---------------------------------------------------------------------------
# Top listings
# ---------------------------------------------------------------------------

with st.container(border=True):
    header = st.container(
        horizontal=True,
        horizontal_alignment="distribute",
        vertical_alignment="center",
    )
    with header:
        st.subheader("Top listings by RevPAR")
        top_n = st.select_slider(
            "Rows",
            options=[10, 20, 50, 100],
            value=20,
            key="revenue_top_n",
            label_visibility="collapsed",
        )

    top = data.load_top_listings(int(top_n))
    top = ui.apply_year_filter(top, selected_years)
    if top.empty:
        ui.render_empty_state("No ranked listings for the current filters.")
    else:
        st.dataframe(
            top,
            hide_index=True,
            column_config={
                **ui.occupancy_column_config(),
                "revpar_rank": st.column_config.NumberColumn("Rank", format="%d"),
            },
            alt="Top listings by revenue per available night",
        )
        st.download_button(
            "Download CSV",
            data=top.to_csv(index=False).encode("utf-8"),
            file_name="top_listings_by_revpar.csv",
            mime="text/csv",
            icon=":material/download:",
        )
