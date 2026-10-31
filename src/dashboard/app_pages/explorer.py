"""SQL explorer: run any of the reusable ``sql/queries`` statements and inspect
the result, with the exact SQL shown for copy-paste into ``psql``.
"""

from __future__ import annotations

import streamlit as st

from src.dashboard import data, ui

#: Friendly names for the query files, in the order they are offered.
QUERY_CATALOGUE: dict[str, str] = {
    "overall_kpis": "Overall KPIs per period",
    "occupancy_by_neighbourhood": "Occupancy by neighbourhood",
    "occupancy_by_room_type": "Occupancy by room type",
    "occupancy_by_listing": "Occupancy by listing",
    "revenue_by_listing": "Revenue by listing (ADR, RevPAR)",
    "top_listings_by_revpar": "Top listings by RevPAR",
    "seasonality": "Seasonality by month",
    "neighbourhood_ranking": "Neighbourhood ranking per year",
    "price_vs_occupancy": "Price vs. occupancy",
}

with st.sidebar:
    st.markdown("**Query**")
    query_name = st.selectbox(
        "Saved query",
        options=list(QUERY_CATALOGUE),
        format_func=lambda name: QUERY_CATALOGUE[name],
        label_visibility="collapsed",
    )
    limit = st.slider("Row limit", min_value=50, max_value=5000, value=500, step=50)

sql = (data.QUERIES_DIR / f"{query_name}.sql").read_text(encoding="utf-8")

try:
    df = data.run_query(query_name)
except Exception as exc:  # noqa: BLE001 - surface DB errors to the user
    st.error(f"Query failed: {exc}", icon=":material/error:")
    st.stop()

with st.container(border=True):
    st.subheader(QUERY_CATALOGUE[query_name])
    st.caption(f"{len(df):,} rows returned; showing the first {limit:,}.")
    st.dataframe(
        df.head(limit),
        hide_index=True,
        column_config=ui.occupancy_column_config(),
        alt=f"Result of the {QUERY_CATALOGUE[query_name]} query",
    )
    st.download_button(
        "Download CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"{query_name}.csv",
        mime="text/csv",
        icon=":material/download:",
    )

with st.expander("SQL source", icon=":material/code:"):
    st.caption(f"`sql/queries/{query_name}.sql`")
    st.code(sql, language="sql")
