"""Occupancy page: neighbourhood and room-type breakdowns."""

from __future__ import annotations

import streamlit as st

from src.dashboard import data, ui

neighbourhoods = data.load_neighbourhoods()
room_types = data.load_room_types()
ranking = data.load_neighbourhood_ranking()
years = data.available_years(neighbourhoods, room_types)

if not years:
    st.warning(
        "No mart data found. Run the pipeline first: `python -m src.pipeline`.",
        icon=":material/warning:",
    )
    st.stop()

selected_years, granularity = ui.sidebar_filters(years, key_prefix="occupancy")

nbh = data.filter_granularity(neighbourhoods, granularity)
nbh = ui.apply_year_filter(nbh, selected_years)
rooms = data.filter_granularity(room_types, granularity)
rooms = ui.apply_year_filter(rooms, selected_years)

# Aggregate by category so each neighbourhood/room-type appears once with
# a weighted occupancy rate (sum of booked_nights / sum of total_nights)
# instead of individual period rows.
nbh_agg = data.aggregate_by_category(nbh, category_col="neighbourhood_cleansed")
rooms_agg = data.aggregate_by_category(rooms, category_col="room_type")

# ---------------------------------------------------------------------------
# Neighbourhood vs. room type
# ---------------------------------------------------------------------------

row = st.columns(2)
with row[0], st.container(border=True):
    st.subheader("Top neighbourhoods by occupancy")
    if nbh_agg.empty:
        ui.render_empty_state("No neighbourhood data for the current filters.")
    else:
        st.altair_chart(
            ui.ranking_bar_chart(
                nbh_agg,
                category_col="neighbourhood_cleansed",
                value_col="occupancy_rate",
                alt_text="Neighbourhood occupancy ranking",
            ),
            alt="Neighbourhoods ranked by occupancy rate",
        )

with row[1], st.container(border=True):
    st.subheader("Occupancy by room type")
    if rooms_agg.empty:
        ui.render_empty_state("No room-type data for the current filters.")
    else:
        st.altair_chart(
            ui.ranking_bar_chart(
                rooms_agg,
                category_col="room_type",
                value_col="occupancy_rate",
                alt_text="Room-type occupancy ranking",
            ),
            alt="Room types ranked by occupancy rate",
        )

# ---------------------------------------------------------------------------
# Price vs. occupancy
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("Price vs. occupancy")
    st.caption(
        "Each point is one room type in one period. In this snapshot the two do "
        "not move together — the most expensive segment does not fill the most "
        "nights. See the Insights page for the correlation."
    )
    scatter_df = data.add_period(rooms)
    if scatter_df.empty or scatter_df["avg_price_per_night"].isna().all():
        ui.render_empty_state("No priced room-type data for the current filters.")
    else:
        st.altair_chart(
            ui.price_vs_occupancy_chart(
                scatter_df,
                color_col="room_type",
                alt_text="Price versus occupancy by room type",
            ),
            alt="Average price per night versus occupancy rate by room type",
        )

# ---------------------------------------------------------------------------
# Neighbourhood leaderboard
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("Neighbourhood leaderboard")
    board = ui.apply_year_filter(ranking, selected_years)
    if board.empty:
        ui.render_empty_state("No yearly ranking available for the current filters.")
    else:
        st.dataframe(
            board,
            hide_index=True,
            column_config={
                **ui.occupancy_column_config(),
                "occupancy_rank": st.column_config.NumberColumn("Rank", format="%d"),
            },
            alt="Neighbourhood occupancy leaderboard per year",
        )
        st.download_button(
            "Download CSV",
            data=board.to_csv(index=False).encode("utf-8"),
            file_name="neighbourhood_ranking.csv",
            mime="text/csv",
            icon=":material/download:",
        )

# ---------------------------------------------------------------------------
# Full breakdown table
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader(f"Neighbourhood detail ({granularity})")
    if nbh.empty:
        ui.render_empty_state("Nothing to show for the current filters.")
    else:
        table = nbh[
            [
                "neighbourhood_cleansed",
                "year",
                "month",
                "week_of_year",
                "quarter",
                "total_listings",
                "total_nights",
                "booked_nights",
                "occupancy_rate",
                "avg_price_per_night",
            ]
        ].sort_values("occupancy_rate", ascending=False)
        st.dataframe(
            table,
            hide_index=True,
            column_config=ui.occupancy_column_config(),
            alt="Occupancy and price per neighbourhood",
        )
