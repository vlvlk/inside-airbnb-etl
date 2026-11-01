"""Data quality page: what the pipeline dropped, skipped or estimated.

An analyst is only as trustworthy as their worst assumption, so this page makes
the pipeline's gaps visible instead of hiding them: how many listings never
reached the calendar, how many carry no price, and how many rows the staging
filter removed. The counts come from ``sql/queries/data_quality.sql`` and read
the raw and staging layers on purpose — a quality check has to compare layers.
"""

from __future__ import annotations

import streamlit as st

from src.dashboard import data

quality = data.load_data_quality()

if quality.empty:
    st.warning(
        "No data quality results. Run the pipeline first: `python -m src.pipeline`.",
        icon=":material/warning:",
    )
    st.stop()

st.markdown(
    "Counts straight from the database, not from the marts. Each one is a place "
    "where the pipeline had to make a decision about the data."
)


def _value(check: str) -> int | None:
    """Return the count for a named check, or ``None`` if it is missing."""
    row = quality[quality["check_name"] == check]
    return int(row["value"].iloc[0]) if not row.empty else None


raw_listings = _value("Listings in raw layer")
staging_listings = _value("Listings in staging layer")
ghosts = _value("Ghost listings (staging minus raw)")
with_calendar = _value("Listings with calendar data")
no_price = _value("Listings without a price")
null_availability = _value("Calendar rows with NULL availability")
zero_occ = _value("Listings with zero booked nights")

with st.container(horizontal=True):
    st.metric(
        "Listings in raw",
        f"{raw_listings:,}" if raw_listings is not None else "n/a",
        border=True,
    )
    st.metric(
        "Listings with calendar",
        f"{with_calendar:,}" if with_calendar is not None else "n/a",
        border=True,
    )
    st.metric(
        "Ghost listings", f"{ghosts:,}" if ghosts is not None else "n/a", border=True
    )
    st.metric(
        "Listings without price",
        f"{no_price:,}" if no_price is not None else "n/a",
        border=True,
    )

# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("What these numbers mean")
    if ghosts is not None and raw_listings is not None and staging_listings is not None:
        st.markdown(
            f"- **{ghosts:,} ghost listings.** `staging.listings` holds "
            f"{staging_listings:,} rows while the raw layer holds {raw_listings:,}. "
            "The staging upsert never deletes, so listings from earlier snapshots "
            "survive after they disappear from the source. The marts join through the "
            "calendar, which only covers the current snapshot, so ghosts never reach a "
            "metric — but any query that reads `staging.listings` directly will "
            "over-count."
        )
    if no_price is not None:
        st.markdown(
            f"- **{no_price:,} listings carry no price.** They are excluded from the "
            "revenue marts, so ADR and RevPAR describe a subset of the market rather "
            "than all of it. Occupancy, which does not need a price, still covers them."
        )
    if null_availability is not None:
        st.markdown(
            f"- **{null_availability:,} calendar rows had no availability flag.** The "
            "staging transform drops them (`WHERE available IS NOT NULL`), so a listing "
            "with a fully blank calendar would silently vanish from every metric."
        )
    if zero_occ is not None:
        st.markdown(
            f"- **{zero_occ:,} listings show exactly 0% occupancy.** A listing that is "
            "available every single night for a year is more likely dormant or "
            "mispriced than genuinely unbooked, so read the bottom of any ranking with "
            "care."
        )

# ---------------------------------------------------------------------------
# Raw table
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("All checks")
    st.dataframe(
        quality[["check_name", "value", "detail"]],
        hide_index=True,
        column_config={
            "check_name": st.column_config.TextColumn("Check"),
            "value": st.column_config.NumberColumn("Value", format="%d"),
            "detail": st.column_config.TextColumn("Why it matters", width="large"),
        },
        alt="Data quality checks with counts and explanations",
    )
    st.download_button(
        "Download CSV",
        data=quality.to_csv(index=False).encode("utf-8"),
        file_name="data_quality.csv",
        mime="text/csv",
        icon=":material/download:",
    )

st.caption(
    "The full list of known limitations, with the measured size of each, is in "
    "`docs/methodology.md`."
)
