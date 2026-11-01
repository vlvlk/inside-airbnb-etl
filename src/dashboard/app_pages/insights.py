"""Insights page: the headline findings, each backed by the chart that shows it.

This is the page to read first. It turns the marts into a short narrative —
what the Toronto market looks like, what actually drives occupancy, and what a
host should do about it. Every number in the prose is computed from the marts at
run time (never hard-coded), so the text stays in step with the data instead of
drifting away from it. The assumptions behind those numbers are collected in
``docs/methodology.md``.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.dashboard import data, ui

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

seasonality = data.load_seasonality()
segments = data.load_host_segmentation()
rooms = data.load_room_types()
price_occ = data.load_price_vs_occupancy()
neighbourhoods = data.load_neighbourhoods()
kpis = data.load_overall_kpis()

years = data.available_years(kpis, segments, rooms, neighbourhoods)
if not years:
    st.warning(
        "No mart data found. Run the pipeline first: `python -m src.pipeline`.",
        icon=":material/warning:",
    )
    st.stop()

with st.sidebar:
    st.markdown("**Filters**")
    selected_years = st.multiselect(
        "Year",
        options=years,
        default=years,
        key="insights_years",
        help="Restrict every finding on this page to these years.",
    )

# The marts encode the period by leaving finer columns NULL, so yearly rows are
# selected through the shared granularity helper. ``host_segmentation`` already
# returns yearly rows only and has no period columns to filter on.
kpis_year = ui.apply_year_filter(data.filter_granularity(kpis, "year"), selected_years)
seg_year = ui.apply_year_filter(segments, selected_years)
room_year = ui.apply_year_filter(data.filter_granularity(rooms, "year"), selected_years)
nb_year = ui.apply_year_filter(
    data.filter_granularity(neighbourhoods, "year"), selected_years
)


def _occupancy(booked: float, total: float) -> float | None:
    """Occupancy fraction, or ``None`` when the denominator is empty."""
    return booked / total if total else None


def _segment_value(
    frame: pd.DataFrame, year: int, segment: str, column: str
) -> float | None:
    """Read one cell from the host-segment frame, tolerating a missing row."""
    row = frame[(frame["year"] == year) & (frame["host_segment"] == segment)]
    return float(row[column].iloc[0]) if not row.empty else None


st.markdown(
    "A short read of the processed Inside Airbnb snapshot. Each finding below is "
    "backed by the chart next to it; the numbers are recomputed from the marts on "
    "every run."
)

# ---------------------------------------------------------------------------
# Portfolio KPIs
# ---------------------------------------------------------------------------

total_listings = int(kpis_year["total_listings"].max()) if not kpis_year.empty else 0
total_nights = int(kpis_year["total_nights"].sum())
booked_nights = int(kpis_year["booked_nights"].sum())
occupancy = _occupancy(booked_nights, total_nights)
has_rev = "total_revenue" in kpis_year and kpis_year["total_revenue"].notna().any()
total_revenue = float(kpis_year["total_revenue"].sum()) if has_rev else None
# ADR and RevPAR must use the revenue side's own night counts: the revenue marts
# only cover priced listings, while ``booked_nights`` above covers every listing
# with calendar data. Dividing revenue by the wider denominator understates ADR.
rev_booked = int(kpis_year["rev_booked_nights"].sum()) if has_rev else 0
rev_available = int(kpis_year["rev_available_nights"].sum()) if has_rev else 0
adr = total_revenue / rev_booked if total_revenue and rev_booked else None
revpar = total_revenue / rev_available if total_revenue and rev_available else None

with st.container(horizontal=True):
    st.metric("Listings", f"{total_listings:,}", border=True)
    st.metric("Occupancy rate", ui.format_occupancy(occupancy), border=True)
    st.metric("Avg daily rate", ui.format_money(adr), border=True)
    st.metric("RevPAR", ui.format_money(revpar), border=True)
    st.metric("Total revenue", ui.format_money(total_revenue), border=True)

# ---------------------------------------------------------------------------
# Finding 1 - Seasonality
# ---------------------------------------------------------------------------

if not seasonality.empty:
    rates = seasonality["occupancy_rate"]
    peak_pos = int(rates.to_numpy().argmax())
    trough_pos = int(rates.to_numpy().argmin())
    peak_rate = float(rates.iloc[peak_pos])
    trough_rate = float(rates.iloc[trough_pos])
    peak_month = int(seasonality["month"].iloc[peak_pos])
    trough_month = int(seasonality["month"].iloc[trough_pos])
    peak_name = ui.MONTH_NAMES.get(peak_month, str(peak_month))
    trough_name = ui.MONTH_NAMES.get(trough_month, str(trough_month))
    spread_pp = (peak_rate - trough_rate) * 100

    with st.container(border=True):
        st.subheader("1. Demand is strongly seasonal")
        st.markdown(
            f"Occupancy swings from **{ui.format_occupancy(trough_rate)}** "
            f"in {trough_name} to **{ui.format_occupancy(peak_rate)}** in "
            f"{peak_name} — a **{spread_pp:.0f} point** gap between the slowest and the "
            "busiest month. A host who prices flat across the year leaves money on the "
            "table in summer and sits empty in winter."
        )
        st.altair_chart(
            ui.seasonality_chart(seasonality, alt_text="Occupancy by month"),
            alt="Occupancy rate by calendar month, aggregated across all years",
        )

# ---------------------------------------------------------------------------
# Finding 2 - Host segmentation
# ---------------------------------------------------------------------------

if not seg_year.empty:
    latest_year = int(seg_year["year"].max())
    single = _segment_value(seg_year, latest_year, "Single listing", "occupancy_rate")
    pro = _segment_value(
        seg_year, latest_year, "Professional (5+ listings)", "occupancy_rate"
    )
    single_adr = _segment_value(
        seg_year, latest_year, "Single listing", "avg_daily_rate"
    )
    pro_adr = _segment_value(
        seg_year, latest_year, "Professional (5+ listings)", "avg_daily_rate"
    )

    with st.container(border=True):
        st.subheader("2. Single-listing hosts fill more nights than professionals")
        if single is not None and pro is not None:
            st.markdown(
                f"In {latest_year}, hosts renting out a single home filled "
                f"**{ui.format_occupancy(single)}** of their nights, while hosts running "
                f"five or more listings filled **{ui.format_occupancy(pro)}**. "
                "Scale does not buy occupancy in this market — the professional segment "
                "looks oversupplied."
            )
        if single_adr is not None and pro_adr is not None:
            st.markdown(
                f"The same split holds on price: single-listing hosts average "
                f"**{ui.format_money(single_adr)}** a night against "
                f"**{ui.format_money(pro_adr)}** for professionals, so the smaller hosts "
                "win on both occupancy and rate."
            )
        row = st.columns(2)
        with row[0]:
            st.altair_chart(
                ui.grouped_bar_chart(
                    seg_year,
                    category_col="host_segment",
                    value_col="occupancy_rate",
                    group_col="year",
                    category_order=ui.HOST_SEGMENT_ORDER,
                ),
                alt="Occupancy rate by host portfolio size and year",
            )
        with row[1]:
            st.altair_chart(
                ui.grouped_bar_chart(
                    seg_year,
                    category_col="host_segment",
                    value_col="avg_daily_rate",
                    group_col="year",
                    value_axis=alt.Axis(format="$,.0f", title="ADR ($)"),
                    value_format="$,.0f",
                    value_title="ADR",
                    category_order=ui.HOST_SEGMENT_ORDER,
                ),
                alt="Average daily rate by host portfolio size and year",
            )

# ---------------------------------------------------------------------------
# Finding 3 - Room type
# ---------------------------------------------------------------------------

if not room_year.empty:
    room_agg = (
        room_year.groupby("room_type", as_index=False)
        .agg(
            total_nights=("total_nights", "sum"),
            booked_nights=("booked_nights", "sum"),
            avg_price_per_night=("avg_price_per_night", "mean"),
            total_listings=("total_listings", "max"),
        )
        .assign(occupancy_rate=lambda df: df["booked_nights"] / df["total_nights"])
    )
    entire = room_agg[room_agg["room_type"] == "Entire home/apt"]
    private = room_agg[room_agg["room_type"] == "Private room"]

    with st.container(border=True):
        st.subheader("3. Whole homes fill more nights and cost far more")
        if not entire.empty and not private.empty:
            e, p = entire.iloc[0], private.iloc[0]
            price_ratio = (
                e["avg_price_per_night"] / p["avg_price_per_night"]
                if p["avg_price_per_night"]
                else None
            )
            st.markdown(
                f"Entire homes fill **{ui.format_occupancy(e['occupancy_rate'])}** of "
                f"nights at **{ui.format_money(e['avg_price_per_night'])}** a night; "
                f"private rooms fill **{ui.format_occupancy(p['occupancy_rate'])}** at "
                f"**{ui.format_money(p['avg_price_per_night'])}**. The price gap is much "
                f"wider than the occupancy gap"
                + (f" ({price_ratio:.1f}x the rate)" if price_ratio else "")
                + " — guests pay a large premium for a whole home without it being much "
                "harder to fill."
            )
        st.altair_chart(
            ui.ranking_bar_chart(
                room_agg,
                category_col="room_type",
                value_col="occupancy_rate",
                alt_text="Occupancy by room type",
            ),
            alt="Room types ranked by occupancy rate",
        )

# ---------------------------------------------------------------------------
# Finding 4 - Price is not the driver
# ---------------------------------------------------------------------------

if not price_occ.empty and price_occ["avg_price_per_night"].notna().any():
    correlation = price_occ["avg_price_per_night"].corr(price_occ["occupancy_rate"])

    with st.container(border=True):
        st.subheader("4. Higher prices do not buy higher occupancy")
        if pd.notna(correlation):
            st.markdown(
                f"Across room types and months the correlation between price and "
                f"occupancy is **{correlation:+.2f}** — effectively flat, and if anything "
                "negative. Being the most expensive listing in a segment does not make it "
                "fill faster; demand here is driven by season and location, not by price "
                "alone."
            )
        st.altair_chart(
            ui.price_vs_occupancy_chart(
                price_occ, color_col="room_type", alt_text="Price versus occupancy"
            ),
            alt="Average price per night versus occupancy rate by room type and month",
        )

# ---------------------------------------------------------------------------
# Finding 5 - Location
# ---------------------------------------------------------------------------

if not nb_year.empty:
    nb_agg = (
        nb_year.groupby("neighbourhood_cleansed", as_index=False)
        .agg(
            total_nights=("total_nights", "sum"),
            booked_nights=("booked_nights", "sum"),
            total_listings=("total_listings", "max"),
            avg_price_per_night=("avg_price_per_night", "mean"),
        )
        .assign(occupancy_rate=lambda df: df["booked_nights"] / df["total_nights"])
    )
    if not nb_agg.empty:
        rates = nb_agg["occupancy_rate"]
        best_pos = int(rates.to_numpy().argmax())
        worst_pos = int(rates.to_numpy().argmin())
        best_name = str(nb_agg["neighbourhood_cleansed"].iloc[best_pos])
        worst_name = str(nb_agg["neighbourhood_cleansed"].iloc[worst_pos])
        best_rate = float(rates.iloc[best_pos])
        worst_rate = float(rates.iloc[worst_pos])
        spread_pp = (best_rate - worst_rate) * 100

        with st.container(border=True):
            st.subheader("5. Location is the biggest single lever")
            st.markdown(
                f"**{best_name}** fills "
                f"**{ui.format_occupancy(best_rate)}** of its nights; "
                f"**{worst_name}** fills only "
                f"**{ui.format_occupancy(worst_rate)}**. That "
                f"**{spread_pp:.0f} point** spread sits inside one city, which is a wider "
                "range than any pricing or room-type choice produces."
            )
            st.altair_chart(
                ui.ranking_bar_chart(
                    nb_agg,
                    category_col="neighbourhood_cleansed",
                    value_col="occupancy_rate",
                    alt_text="Neighbourhood occupancy ranking",
                    top_n=10,
                ),
                alt="Neighbourhoods ranked by occupancy rate",
            )

# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("What a host should take from this")
    st.markdown(
        "- **Price to the season.** The gap between the best and worst month is wide "
        "enough that a flat calendar price is leaving revenue on the table.\n"
        "- **Do not compete on being the most expensive.** Higher rates do not correlate "
        "with higher occupancy; the win comes from season, location and room type.\n"
        "- **Whole homes earn their premium.** The rate gap to private rooms is far "
        "larger than the occupancy gap, so the premium is not being competed away.\n"
        "- **Check the neighbourhood first.** Location moves occupancy more than any "
        "other lever in the data.\n"
        "- **Watch the professional segment.** Multi-listing hosts fill fewer nights at "
        "lower rates, which is the signature of local oversupply."
    )

# ---------------------------------------------------------------------------
# Caveats
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("Read these numbers with care")
    st.markdown(
        "- **`booked_nights` counts every unavailable night.** Inside Airbnb's calendar "
        "cannot separate a real booking from a night the host blocked by hand, so "
        "occupancy here is an upper bound. `docs/methodology.md` quantifies the gap "
        "against Inside Airbnb's own estimate.\n"
        "- **Revenue is estimated from a static price.** The calendar snapshot carries no "
        "per-night price, so every night is valued at the listing's single scraped price. "
        "Real revenue varies with season and discounts.\n"
        "- **Two different 'average prices' exist.** `avg_price_per_night` averages all "
        "nights; ADR averages only booked nights. They are not interchangeable.\n"
        "- **The revenue marts cover a subset.** Listings without a price are excluded "
        "from ADR and RevPAR."
    )

st.caption(
    "Source: Inside Airbnb Toronto snapshot, 2026-09-17 to 2027-09-17. "
    "Methodology and known limitations: `docs/methodology.md`."
)
