"""Tests for the vectorized CSV normalizer (``src.extract.normalize``)."""

import pandas as pd
import pytest

from src.extract.normalize import (
    invalid_calendar_mask,
    invalid_listing_mask,
    normalize_calendar,
    normalize_listings,
)
from src.models.calendar import CALENDAR_FIELDS
from src.models.listing import LISTING_FIELDS


class TestNormalizeListings:
    """Column-wise normalization of the listings frame."""

    def test_reindexes_to_ddl_columns(self):
        df = pd.DataFrame({"id": ["1"], "name": ["A"]})

        out = normalize_listings(df)

        assert list(out.columns) == list(LISTING_FIELDS)

    def test_price_kept_verbatim(self):
        """The raw layer keeps the currency string; staging cleans it."""
        df = pd.DataFrame({"id": ["1"], "price": ["$1,234.56"]})

        out = normalize_listings(df)

        assert out["price"].iloc[0] == "$1,234.56"

    def test_bool_flags_normalized(self):
        df = pd.DataFrame(
            {
                "id": ["1", "2", "3"],
                "host_is_superhost": ["True", "f", ""],
            }
        )

        out = normalize_listings(df)

        assert list(out["host_is_superhost"]) == ["t", "f", pd.NA]

    def test_dates_normalized_to_iso(self):
        df = pd.DataFrame({"id": ["1", "2"], "last_scraped": ["2024-01-05", "bogus"]})

        out = normalize_listings(df)

        assert out["last_scraped"].iloc[0] == "2024-01-05"
        assert pd.isna(out["last_scraped"].iloc[1])

    def test_ints_truncated(self):
        df = pd.DataFrame({"id": ["1"], "accommodates": ["4.0"]})

        out = normalize_listings(df)

        assert out["accommodates"].iloc[0] == "4"

    def test_decimals_strip_currency(self):
        """Currency symbols and thousands separators are removed like Pydantic."""
        df = pd.DataFrame(
            {"id": ["1", "2"], "review_scores_rating": ["$4.50", "1,234.50"]}
        )

        out = normalize_listings(df)

        assert out["review_scores_rating"].iloc[0] == "4.50"
        assert out["review_scores_rating"].iloc[1] == "1234.50"

    def test_missing_optional_columns_become_na(self):
        df = pd.DataFrame({"id": ["1"]})

        out = normalize_listings(df)

        assert pd.isna(out["host_id"].iloc[0])


class TestNormalizeCalendar:
    """Column-wise normalization of the calendar frame."""

    def test_reindexes_to_ddl_columns(self):
        out = normalize_calendar(pd.DataFrame({"listing_id": ["1"]}))

        assert list(out.columns) == list(CALENDAR_FIELDS)

    def test_available_flag_and_date(self):
        df = pd.DataFrame(
            {
                "listing_id": ["10", "10", "10"],
                "date": ["2024-02-01", "2024-02-02", "bad"],
                "available": ["t", "f", "t"],
                "minimum_nights": ["1", "2", "3"],
                "maximum_nights": ["30", "30", "30"],
            }
        )

        out = normalize_calendar(df)

        assert list(out["available"]) == ["t", "f", "t"]
        assert out["date"].iloc[0] == "2024-02-01"
        assert pd.isna(out["date"].iloc[2])
        assert list(out["minimum_nights"]) == ["1", "2", "3"]

    def test_empty_available_becomes_na(self):
        df = pd.DataFrame(
            {
                "listing_id": ["1"],
                "date": ["2024-02-01"],
                "available": [""],
            }
        )

        out = normalize_calendar(df)

        assert pd.isna(out["available"].iloc[0])


class TestInvalidMasks:
    """Masks flag rows whose required keys cannot be parsed."""

    def test_listing_mask_flags_bad_id(self):
        df = pd.DataFrame({"id": ["1", "invalid", "3"]})

        mask = invalid_listing_mask(df)

        assert list(mask) == [False, True, False]

    def test_calendar_mask_flags_bad_id_and_date(self):
        df = pd.DataFrame(
            {
                "listing_id": ["1", "bad", "3"],
                "date": ["2024-01-01", "2024-01-02", "not-a-date"],
            }
        )

        mask = invalid_calendar_mask(df)

        assert list(mask) == [False, True, True]

    def test_calendar_mask_all_valid(self):
        df = pd.DataFrame(
            {"listing_id": ["1"], "date": ["2024-01-01"]},
        )

        assert not invalid_calendar_mask(df).any()


@pytest.mark.parametrize("value", ["1", "1.0", "1,000"])
def test_numeric_id_variants_are_valid(value):
    df = pd.DataFrame({"id": [value]})

    assert not invalid_listing_mask(df).any()
