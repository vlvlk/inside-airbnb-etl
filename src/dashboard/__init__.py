"""Streamlit dashboard for the Airbnb occupancy marts.

The dashboard is a thin, read-only presentation layer on top of the
pre-aggregated ``marts`` schema produced by the ETL pipeline. It never reads the
raw layer, so it stays fast even on the full 8M-row calendar dataset.
"""
