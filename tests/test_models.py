"""Tests for Pydantic models."""

from datetime import date
from decimal import Decimal

from src.models import CalendarRaw, CalendarStaging, ListingRaw, ListingStaging


class TestListingRaw:
    """Tests for ListingRaw model."""

    def test_valid_listing_minimal(self):
        """Test minimal valid listing."""
        data = {"id": "12345"}
        listing = ListingRaw(**data)
        assert listing.id == 12345

    def test_valid_listing_full(self):
        """Test listing with all fields."""
        data = {
            "id": "12345",
            "listing_url": "https://airbnb.com/rooms/12345",
            "name": "Test Listing",
            "host_id": "67890",
            "host_name": "Test Host",
            "neighbourhood_cleansed": "Downtown",
            "latitude": "40.7128",
            "longitude": "-74.0060",
            "property_type": "Entire rental unit",
            "room_type": "Entire home/apt",
            "accommodates": "4",
            "price": "$150.00",
            "price_quote_price_per_night": "150.00",
            "minimum_nights": "2",
            "maximum_nights": "30",
            "host_is_superhost": "t",
            "host_identity_verified": "f",
            "has_availability": "t",
            "instant_bookable": "f",
            "review_scores_rating": "4.85",
            "last_scraped": "2024-01-15",
        }
        listing = ListingRaw(**data)
        assert listing.id == 12345
        assert listing.name == "Test Listing"
        assert listing.host_id == 67890
        assert listing.latitude == Decimal("40.7128")
        assert listing.longitude == Decimal("-74.0060")
        assert listing.price == "$150.00"  # Raw keeps original string
        assert listing.price_quote_price_per_night == Decimal("150.00")
        # Raw layer keeps boolean flags as text ('t'/'f')
        assert listing.host_is_superhost == "t"
        assert listing.host_identity_verified == "f"
        assert listing.has_availability == "t"
        assert listing.instant_bookable == "f"
        assert listing.review_scores_rating == Decimal("4.85")
        assert listing.last_scraped == date(2024, 1, 15)

    def test_listing_price_parsing(self):
        """Test price parsing with various formats."""
        test_cases = [
            ("$150.00", "$150.00"),  # Raw keeps as string
            ("$1,234.56", "$1,234.56"),
            ("150", "150"),
            ("", None),  # Empty string is normalized to None
            (None, None),
        ]
        for input_val, expected in test_cases:
            data = {"id": "1", "price": input_val}
            listing = ListingRaw(**data)
            assert listing.price == expected

    def test_listing_decimal_fields(self):
        """Test decimal field parsing."""
        data = {
            "id": "1",
            "latitude": "40.7128",
            "longitude": "-74.0060",
            "bathrooms": "1.5",
            "review_scores_rating": "4.85",
        }
        listing = ListingRaw(**data)
        assert listing.latitude == Decimal("40.7128")
        assert listing.longitude == Decimal("-74.0060")
        assert listing.bathrooms == Decimal("1.5")
        assert listing.review_scores_rating == Decimal("4.85")

    def test_listing_bool_fields(self):
        """Test boolean string normalization to canonical 't'/'f'."""
        true_values = ["t", "true", "1", "yes", "y", "T", "TRUE"]
        false_values = ["f", "false", "0", "no", "n", "F", "FALSE"]

        for val in true_values:
            data = {"id": "1", "host_is_superhost": val}
            listing = ListingRaw(**data)
            assert listing.host_is_superhost == "t", f"Failed for {val}"

        for val in false_values:
            data = {"id": "1", "host_is_superhost": val}
            listing = ListingRaw(**data)
            assert listing.host_is_superhost == "f", f"Failed for {val}"

    def test_listing_invalid_int(self):
        """Test invalid integer handling."""
        data = {"id": "1", "accommodates": "invalid"}
        listing = ListingRaw(**data)
        assert listing.accommodates is None

    def test_listing_extra_fields_ignored(self):
        """Test that extra fields are ignored."""
        data = {"id": "1", "extra_field": "should_be_ignored"}
        listing = ListingRaw(**data)
        assert not hasattr(listing, "extra_field")


class TestCalendarRaw:
    """Tests for CalendarRaw model."""

    def test_valid_calendar_minimal(self):
        """Test minimal valid calendar entry."""
        data = {"listing_id": "12345", "date": "2024-01-15", "available": "t"}
        cal = CalendarRaw(**data)
        assert cal.listing_id == 12345
        assert cal.date == date(2024, 1, 15)
        assert cal.available == "t"  # Raw layer keeps canonical 't'/'f' text

    def test_calendar_available_parsing(self):
        """Test available field normalization to canonical 't'/'f' text."""
        true_cases = ["t", "T", "true", "TRUE"]
        false_cases = ["f", "F", "false", "FALSE"]

        for val in true_cases:
            data = {"listing_id": "1", "date": "2024-01-01", "available": val}
            cal = CalendarRaw(**data)
            assert cal.available == "t", f"Failed for {val}"

        for val in false_cases:
            data = {"listing_id": "1", "date": "2024-01-01", "available": val}
            cal = CalendarRaw(**data)
            assert cal.available == "f", f"Failed for {val}"

    def test_calendar_int_fields(self):
        """Test integer field parsing."""
        data = {
            "listing_id": "12345",
            "date": "2024-01-15",
            "available": "t",
            "minimum_nights": "2",
            "maximum_nights": "30",
        }
        cal = CalendarRaw(**data)
        assert cal.minimum_nights == 2
        assert cal.maximum_nights == 30


class TestCalendarStaging:
    """Tests for CalendarStaging model."""

    def test_from_raw_derives_time_fields(self):
        """Test that from_raw correctly derives time dimensions."""
        raw = CalendarRaw(
            listing_id=12345,
            date=date(2024, 1, 15),  # Monday
            available=True,
            minimum_nights=2,
            maximum_nights=30,
        )
        staging = CalendarStaging.from_raw(raw)

        assert staging.listing_id == 12345
        assert staging.date == date(2024, 1, 15)
        assert staging.available is True
        assert staging.year == 2024
        assert staging.month == 1
        assert staging.day == 15
        assert staging.day_of_week == 0  # Monday = 0
        assert staging.week_of_year == 3  # Jan 15 is week 3
        assert staging.quarter == 1
        assert staging.is_weekend is False

    def test_from_raw_weekend(self):
        """Test weekend detection."""
        raw = CalendarRaw(
            listing_id=12345,
            date=date(2024, 1, 13),  # Saturday
            available=False,
        )
        staging = CalendarStaging.from_raw(raw)
        assert staging.is_weekend is True
        assert staging.day_of_week == 5  # Saturday = 5

    def test_from_raw_sunday(self):
        """Test Sunday detection."""
        raw = CalendarRaw(
            listing_id=12345,
            date=date(2024, 1, 14),  # Sunday
            available=False,
        )
        staging = CalendarStaging.from_raw(raw)
        assert staging.is_weekend is True
        assert staging.day_of_week == 6  # Sunday = 6


class TestListingStaging:
    """Tests for ListingStaging model."""

    def test_model_creation(self):
        """Test basic model creation."""
        staging = ListingStaging(
            listing_id=12345,
            name="Test Listing",
            neighbourhood_cleansed="Downtown",
            room_type="Entire home/apt",
            price=Decimal("150.00"),
            price_per_night=Decimal("150.00"),
        )
        assert staging.listing_id == 12345
        assert staging.name == "Test Listing"
        assert staging.neighbourhood_cleansed == "Downtown"
        assert staging.room_type == "Entire home/apt"
        assert staging.price == Decimal("150.00")
        assert staging.price_per_night == Decimal("150.00")
