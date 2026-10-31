"""Pydantic models for Airbnb listings data validation."""

import math
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator


def _is_missing(v: object) -> bool:
    """Return True for values that should be treated as absent.

    Covers ``None``, empty/whitespace strings and NaN values that pandas
    produces for empty CSV cells (``float('nan')`` for text columns and
    ``Decimal('NaN')`` for numeric one).
    """
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, float):
        return math.isnan(v)
    if isinstance(v, Decimal):
        return v.is_nan()
    return False


#: Listing columns stored as plain TEXT (empty cells become ``None``).
LISTING_STR_FIELDS: tuple[str, ...] = (
    "listing_url",
    "scrape_id",
    "source",
    "name",
    "description",
    "neighborhood_overview",
    "picture_url",
    "host_url",
    "host_profile_id",
    "host_profile_url",
    "host_name",
    "host_location",
    "host_about",
    "host_response_time",
    "host_response_rate",
    "host_acceptance_rate",
    "host_thumbnail_url",
    "host_picture_url",
    "host_neighbourhood",
    "host_verifications",
    "neighbourhood",
    "neighbourhood_cleansed",
    "neighbourhood_group_cleansed",
    "property_type",
    "room_type",
    "bathrooms_text",
    "amenities",
    "price",
    "price_quote_raw",
    "calendar_updated",
    "license",
)

#: Listing columns parsed as ISO dates; unparseable cells become ``None``.
LISTING_DATE_FIELDS: tuple[str, ...] = (
    "last_scraped",
    "host_since",
    "price_quote_checkin_date",
    "price_quote_checkout_date",
    "calendar_last_scraped",
    "first_review",
    "last_review",
)

#: Listing columns parsed as decimals (currency symbols and commas stripped).
LISTING_DECIMAL_FIELDS: tuple[str, ...] = (
    "latitude",
    "longitude",
    "price_quote_total_price",
    "price_quote_price_per_night",
    "bathrooms",
    "minimum_nights_avg_ntm",
    "maximum_nights_avg_ntm",
    "review_scores_rating",
    "review_scores_accuracy",
    "review_scores_cleanliness",
    "review_scores_checkin",
    "review_scores_communication",
    "review_scores_location",
    "review_scores_value",
    "reviews_per_month",
)

#: Listing columns coerced to integers.
LISTING_INT_FIELDS: tuple[str, ...] = (
    "id",
    "host_id",
    "host_listings_count",
    "host_total_listings_count",
    "accommodates",
    "bedrooms",
    "beds",
    "minimum_nights",
    "maximum_nights",
    "minimum_minimum_nights",
    "maximum_minimum_nights",
    "minimum_maximum_nights",
    "maximum_maximum_nights",
    "availability_30",
    "availability_60",
    "availability_90",
    "availability_365",
    "number_of_reviews",
    "number_of_reviews_ltm",
    "number_of_reviews_l30d",
    "availability_eoy",
    "number_of_reviews_ly",
    "estimated_occupancy_l365d",
    "estimated_revenue_l365d",
    "calculated_host_listings_count",
    "calculated_host_listings_count_entire_homes",
    "calculated_host_listings_count_private_rooms",
    "calculated_host_listings_count_shared_rooms",
    "hosts_time_as_user_years",
    "hosts_time_as_user_months",
    "hosts_time_as_host_years",
    "hosts_time_as_host_months",
)

#: Listing columns normalized to the canonical ``'t'``/``'f'`` text flag.
LISTING_BOOL_STR_FIELDS: tuple[str, ...] = (
    "host_is_superhost",
    "host_has_profile_pic",
    "host_identity_verified",
    "has_availability",
    "instant_bookable",
)

#: Every listing column in CSV order, used by the vectorized normalizer and
#: by the ``COPY`` loader to align the DataFrame with ``raw.listings``.
LISTING_FIELDS: tuple[str, ...] = (
    "id",
    "listing_url",
    "scrape_id",
    "last_scraped",
    "source",
    "name",
    "description",
    "neighborhood_overview",
    "picture_url",
    "host_id",
    "host_url",
    "host_profile_id",
    "host_profile_url",
    "host_name",
    "host_since",
    "hosts_time_as_user_years",
    "hosts_time_as_user_months",
    "hosts_time_as_host_years",
    "hosts_time_as_host_months",
    "host_location",
    "host_about",
    "host_response_time",
    "host_response_rate",
    "host_acceptance_rate",
    "host_is_superhost",
    "host_thumbnail_url",
    "host_picture_url",
    "host_neighbourhood",
    "host_listings_count",
    "host_total_listings_count",
    "host_verifications",
    "host_has_profile_pic",
    "host_identity_verified",
    "neighbourhood",
    "neighbourhood_cleansed",
    "neighbourhood_group_cleansed",
    "latitude",
    "longitude",
    "property_type",
    "room_type",
    "accommodates",
    "bathrooms",
    "bathrooms_text",
    "bedrooms",
    "beds",
    "amenities",
    "price",
    "price_quote_checkin_date",
    "price_quote_checkout_date",
    "price_quote_total_price",
    "price_quote_price_per_night",
    "price_quote_raw",
    "minimum_nights",
    "maximum_nights",
    "minimum_minimum_nights",
    "maximum_minimum_nights",
    "minimum_maximum_nights",
    "maximum_maximum_nights",
    "minimum_nights_avg_ntm",
    "maximum_nights_avg_ntm",
    "calendar_updated",
    "has_availability",
    "availability_30",
    "availability_60",
    "availability_90",
    "availability_365",
    "calendar_last_scraped",
    "number_of_reviews",
    "number_of_reviews_ltm",
    "number_of_reviews_l30d",
    "availability_eoy",
    "number_of_reviews_ly",
    "estimated_occupancy_l365d",
    "estimated_revenue_l365d",
    "first_review",
    "last_review",
    "review_scores_rating",
    "review_scores_accuracy",
    "review_scores_cleanliness",
    "review_scores_checkin",
    "review_scores_communication",
    "review_scores_location",
    "review_scores_value",
    "license",
    "instant_bookable",
    "calculated_host_listings_count",
    "calculated_host_listings_count_entire_homes",
    "calculated_host_listings_count_private_rooms",
    "calculated_host_listings_count_shared_rooms",
    "reviews_per_month",
)


class ListingRaw(BaseModel):
    """Raw listing model matching CSV structure - all fields as strings for initial load."""

    # Primary identifiers
    id: int
    listing_url: str | None = None
    scrape_id: str | None = None
    last_scraped: date | None = None
    source: str | None = None
    name: str | None = None

    # Description fields
    description: str | None = None
    neighborhood_overview: str | None = None
    picture_url: str | None = None

    # Host information
    host_id: int | None = None
    host_url: str | None = None
    host_profile_id: str | None = None
    host_profile_url: str | None = None
    host_name: str | None = None
    host_since: date | None = None
    hosts_time_as_user_years: int | None = None
    hosts_time_as_user_months: int | None = None
    hosts_time_as_host_years: int | None = None
    hosts_time_as_host_months: int | None = None
    host_location: str | None = None
    host_about: str | None = None
    host_response_time: str | None = None
    host_response_rate: str | None = None
    host_acceptance_rate: str | None = None
    host_is_superhost: str | None = None
    host_thumbnail_url: str | None = None
    host_picture_url: str | None = None
    host_neighbourhood: str | None = None
    host_listings_count: int | None = None
    host_total_listings_count: int | None = None
    host_verifications: str | None = None
    host_has_profile_pic: str | None = None
    host_identity_verified: str | None = None

    # Location
    neighbourhood: str | None = None
    neighbourhood_cleansed: str | None = None
    neighbourhood_group_cleansed: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None

    # Property details
    property_type: str | None = None
    room_type: str | None = None
    accommodates: int | None = None
    bathrooms: Decimal | None = None
    bathrooms_text: str | None = None
    bedrooms: int | None = None
    beds: int | None = None
    amenities: str | None = None

    # Pricing
    price: str | None = None
    price_quote_checkin_date: date | None = None
    price_quote_checkout_date: date | None = None
    price_quote_total_price: Decimal | None = None
    price_quote_price_per_night: Decimal | None = None
    price_quote_raw: str | None = None

    # Minimum/maximum nights
    minimum_nights: int | None = None
    maximum_nights: int | None = None
    minimum_minimum_nights: int | None = None
    maximum_minimum_nights: int | None = None
    minimum_maximum_nights: int | None = None
    maximum_maximum_nights: int | None = None
    minimum_nights_avg_ntm: Decimal | None = None
    maximum_nights_avg_ntm: Decimal | None = None

    # Availability
    calendar_updated: str | None = None
    has_availability: str | None = None
    availability_30: int | None = None
    availability_60: int | None = None
    availability_90: int | None = None
    availability_365: int | None = None
    calendar_last_scraped: date | None = None

    # Reviews
    number_of_reviews: int | None = None
    number_of_reviews_ltm: int | None = None
    number_of_reviews_l30d: int | None = None
    availability_eoy: int | None = None
    number_of_reviews_ly: int | None = None

    # Estimated metrics
    estimated_occupancy_l365d: int | None = None
    estimated_revenue_l365d: int | None = None

    # Review dates
    first_review: date | None = None
    last_review: date | None = None

    # Review scores
    review_scores_rating: Decimal | None = None
    review_scores_accuracy: Decimal | None = None
    review_scores_cleanliness: Decimal | None = None
    review_scores_checkin: Decimal | None = None
    review_scores_communication: Decimal | None = None
    review_scores_location: Decimal | None = None
    review_scores_value: Decimal | None = None

    # Other
    license: str | None = None
    instant_bookable: str | None = None
    calculated_host_listings_count: int | None = None
    calculated_host_listings_count_entire_homes: int | None = None
    calculated_host_listings_count_private_rooms: int | None = None
    calculated_host_listings_count_shared_rooms: int | None = None
    reviews_per_month: Decimal | None = None

    @field_validator(*LISTING_STR_FIELDS, mode="before")
    @classmethod
    def parse_str(cls, v):
        # Empty CSV cells arrive as NaN from pandas; normalize them to None so
        # the optional ``str`` fields validate instead of raising string_type.
        if _is_missing(v):
            return None
        return v if isinstance(v, str) else str(v)

    @field_validator(*LISTING_DATE_FIELDS, mode="before")
    @classmethod
    def parse_date(cls, v):
        if _is_missing(v):
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v))
        except (ValueError, TypeError):
            return None

    @field_validator(*LISTING_DECIMAL_FIELDS, mode="before")
    @classmethod
    def parse_decimal(cls, v):
        if _is_missing(v):
            return None
        if isinstance(v, Decimal):
            return v
        try:
            # Remove currency symbols and commas
            cleaned = str(v).replace("$", "").replace(",", "").strip()
            if not cleaned:
                return None
            result = Decimal(cleaned)
            # pandas turns empty cells into NaN; guard against Decimal('NaN')
            # which Pydantic rejects as a non-finite number.
            return None if result.is_nan() else result
        except (ValueError, TypeError):
            return None

    @field_validator(*LISTING_INT_FIELDS, mode="before")
    @classmethod
    def parse_int(cls, v):
        if _is_missing(v):
            return None
        if isinstance(v, int):
            return v
        try:
            return int(float(str(v).replace(",", "")))
        except (ValueError, TypeError):
            return None

    @field_validator(*LISTING_BOOL_STR_FIELDS, mode="before")
    @classmethod
    def parse_bool_str(cls, v):
        # Raw layer stores these as TEXT, so normalize to canonical 't'/'f'.
        if _is_missing(v):
            return None
        if isinstance(v, bool):
            return "t" if v else "f"
        return "t" if str(v).strip().lower() in ("t", "true", "1", "yes", "y") else "f"

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }


class ListingStaging(BaseModel):
    """Staging model with cleaned and typed fields for analytics."""

    # Primary identifiers
    listing_id: int
    listing_url: str | None = None
    scrape_id: str | None = None
    last_scraped: date | None = None

    # Core listing info
    name: str | None = None
    description: str | None = None
    picture_url: str | None = None

    # Host info (essential for analytics)
    host_id: int | None = None
    host_name: str | None = None
    host_since: date | None = None
    host_is_superhost: bool | None = None
    host_identity_verified: bool | None = None
    host_listings_count: int | None = None

    # Location (key for geographic analytics)
    neighbourhood: str | None = None
    neighbourhood_cleansed: str | None = None
    neighbourhood_group_cleansed: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None

    # Property details
    property_type: str | None = None
    room_type: str | None = None
    accommodates: int | None = None
    bathrooms: Decimal | None = None
    bedrooms: int | None = None
    beds: int | None = None

    # Pricing (cleaned)
    price: Decimal | None = None
    price_per_night: Decimal | None = None

    # Stay requirements
    minimum_nights: int | None = None
    maximum_nights: int | None = None

    # Availability
    has_availability: bool | None = None
    availability_30: int | None = None
    availability_60: int | None = None
    availability_90: int | None = None
    availability_365: int | None = None
    calendar_last_scraped: date | None = None

    # Reviews
    number_of_reviews: int | None = None
    number_of_reviews_ltm: int | None = None
    review_scores_rating: Decimal | None = None
    review_scores_cleanliness: Decimal | None = None
    review_scores_checkin: Decimal | None = None
    review_scores_communication: Decimal | None = None
    review_scores_location: Decimal | None = None
    review_scores_value: Decimal | None = None

    # Booking
    instant_bookable: bool | None = None

    model_config = {
        "from_attributes": True,
    }
