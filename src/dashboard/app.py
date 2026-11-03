"""Entry point for the Inside Airbnb dashboard.

Run from the project root:

    streamlit run src/dashboard/app.py

The app is a read-only view over the ``marts`` schema produced by the ETL
pipeline. That schema can come from two places, chosen by ``dashboard.source``:

* PostgreSQL, once ``python -m src.pipeline`` has populated it;
* the bundled Parquet demo layer, so a fresh clone works with no database.

Either way the same ``sql/queries/*.sql`` files run, so the numbers are the
same. The sidebar states which source is live.
"""

from __future__ import annotations

import streamlit as st

from src.dashboard import data

st.set_page_config(
    page_title="Inside Airbnb",
    page_icon=":material/apartment:",
    layout="wide",
)

pages = st.navigation(
    {
        "Analytics": [
            st.Page(
                "app_pages/insights.py",
                title="Insights",
                icon=":material/lightbulb:",
                default=True,
            ),
            st.Page(
                "app_pages/overview.py",
                title="Overview",
                icon=":material/dashboard:",
            ),
            st.Page(
                "app_pages/occupancy.py",
                title="Occupancy",
                icon=":material/event_available:",
            ),
            st.Page(
                "app_pages/revenue.py",
                title="Revenue",
                icon=":material/payments:",
            ),
        ],
        "Data": [
            st.Page(
                "app_pages/data_quality.py",
                title="Data quality",
                icon=":material/fact_check:",
            ),
            st.Page(
                "app_pages/explorer.py",
                title="SQL explorer",
                icon=":material/table_view:",
            ),
        ],
    },
    position="sidebar",
)

# ---------------------------------------------------------------------------
# Data source indicator
# ---------------------------------------------------------------------------

# Which engine is serving the numbers is not a detail: the demo layer is a
# committed snapshot, not a live warehouse. Saying so in the sidebar keeps the
# dashboard honest about what the reader is looking at.
backend = data.active_backend()

with st.sidebar:
    if backend is None:
        st.warning(
            "No data source available. Start PostgreSQL and run "
            "`python -m src.pipeline`, or build the demo layer with "
            "`python -m scripts.build_demo_marts`.",
            icon=":material/database_off:",
        )
    elif backend.kind == "duckdb":
        st.badge("Demo data", icon=":material/science:", color="orange")
        st.caption(
            "Reading the bundled Parquet snapshot, not a live database. "
            "Run the pipeline and use PostgreSQL for the production path."
        )
    else:
        st.badge("PostgreSQL", icon=":material/database:", color="green")
        st.caption(backend.describe())

st.title(f"{pages.icon} {pages.title}")
pages.run()
