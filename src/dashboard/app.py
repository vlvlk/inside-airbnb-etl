"""Entry point for the Airbnb occupancy dashboard.

Run from the project root:

    streamlit run src/dashboard/app.py

The app is a read-only view over the ``marts`` schema produced by the ETL
pipeline, so the pipeline (``python -m src.pipeline``) must have run at least
once against the configured database.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Airbnb occupancy",
    page_icon=":material/apartment:",
    layout="wide",
)

pages = st.navigation(
    {
        "Analytics": [
            st.Page(
                "app_pages/overview.py",
                title="Overview",
                icon=":material/dashboard:",
                default=True,
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
                "app_pages/explorer.py",
                title="SQL explorer",
                icon=":material/table_view:",
            ),
        ],
    },
    position="sidebar",
)

st.title(f"{pages.icon} {pages.title}")
pages.run()
