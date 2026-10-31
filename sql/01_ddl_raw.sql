-- Raw layer DDL: 1:1 copy of CSV files
-- Schema: raw

CREATE SCHEMA IF NOT EXISTS raw;

-- Raw listings table - matches CSV structure exactly
CREATE TABLE IF NOT EXISTS raw.listings (
    id BIGINT PRIMARY KEY,
    listing_url TEXT,
    scrape_id TEXT,
    last_scraped DATE,
    source TEXT,
    name TEXT,
    description TEXT,
    neighborhood_overview TEXT,
    picture_url TEXT,
    host_id BIGINT,
    host_url TEXT,
    host_profile_id TEXT,
    host_profile_url TEXT,
    host_name TEXT,
    host_since DATE,
    hosts_time_as_user_years INTEGER,
    hosts_time_as_user_months INTEGER,
    hosts_time_as_host_years INTEGER,
    hosts_time_as_host_months INTEGER,
    host_location TEXT,
    host_about TEXT,
    host_response_time TEXT,
    host_response_rate TEXT,
    host_acceptance_rate TEXT,
    host_is_superhost TEXT,
    host_thumbnail_url TEXT,
    host_picture_url TEXT,
    host_neighbourhood TEXT,
    host_listings_count INTEGER,
    host_total_listings_count INTEGER,
    host_verifications TEXT,
    host_has_profile_pic TEXT,
    host_identity_verified TEXT,
    neighbourhood TEXT,
    neighbourhood_cleansed TEXT,
    neighbourhood_group_cleansed TEXT,
    latitude NUMERIC(10, 6),
    longitude NUMERIC(10, 6),
    property_type TEXT,
    room_type TEXT,
    accommodates INTEGER,
    bathrooms NUMERIC(4, 2),
    bathrooms_text TEXT,
    bedrooms INTEGER,
    beds INTEGER,
    amenities TEXT,
    price TEXT,
    price_quote_checkin_date DATE,
    price_quote_checkout_date DATE,
    price_quote_total_price NUMERIC(12, 2),
    price_quote_price_per_night NUMERIC(10, 2),
    price_quote_raw TEXT,
    minimum_nights INTEGER,
    maximum_nights INTEGER,
    minimum_minimum_nights INTEGER,
    maximum_minimum_nights INTEGER,
    minimum_maximum_nights INTEGER,
    maximum_maximum_nights INTEGER,
    -- CSV uses 2147483647 (INT32 max) as an "unbounded" sentinel, so these
    -- must hold up to 10 integer digits. Raw layer keeps the value verbatim.
    minimum_nights_avg_ntm NUMERIC(12, 2),
    maximum_nights_avg_ntm NUMERIC(12, 2),
    calendar_updated TEXT,
    has_availability TEXT,
    availability_30 INTEGER,
    availability_60 INTEGER,
    availability_90 INTEGER,
    availability_365 INTEGER,
    calendar_last_scraped DATE,
    number_of_reviews INTEGER,
    number_of_reviews_ltm INTEGER,
    number_of_reviews_l30d INTEGER,
    availability_eoy INTEGER,
    number_of_reviews_ly INTEGER,
    estimated_occupancy_l365d INTEGER,
    estimated_revenue_l365d INTEGER,
    first_review DATE,
    last_review DATE,
    review_scores_rating NUMERIC(3, 2),
    review_scores_accuracy NUMERIC(3, 2),
    review_scores_cleanliness NUMERIC(3, 2),
    review_scores_checkin NUMERIC(3, 2),
    review_scores_communication NUMERIC(3, 2),
    review_scores_location NUMERIC(3, 2),
    review_scores_value NUMERIC(3, 2),
    license TEXT,
    instant_bookable TEXT,
    calculated_host_listings_count INTEGER,
    calculated_host_listings_count_entire_homes INTEGER,
    calculated_host_listings_count_private_rooms INTEGER,
    calculated_host_listings_count_shared_rooms INTEGER,
    reviews_per_month NUMERIC(5, 2),
    -- Metadata
    loaded_at TIMESTAMPTZ DEFAULT NOW(),
    source_file TEXT
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_raw_listings_host_id ON raw.listings(host_id);
CREATE INDEX IF NOT EXISTS idx_raw_listings_neighbourhood_cleansed ON raw.listings(neighbourhood_cleansed);
CREATE INDEX IF NOT EXISTS idx_raw_listings_last_scraped ON raw.listings(last_scraped);

-- Raw calendar table - matches CSV structure exactly
CREATE TABLE IF NOT EXISTS raw.calendar (
    listing_id BIGINT NOT NULL,
    date DATE NOT NULL,
    -- 't' or 'f'. NULL when the CSV cell is empty (such rows are filtered out
    -- of staging by the ``WHERE available IS NOT NULL`` guard).
    available CHAR(1),
    minimum_nights INTEGER,
    maximum_nights INTEGER,
    -- Metadata
    loaded_at TIMESTAMPTZ DEFAULT NOW(),
    source_file TEXT,
    PRIMARY KEY (listing_id, date)
);

-- Index for time-series queries
CREATE INDEX IF NOT EXISTS idx_raw_calendar_date ON raw.calendar(date);
CREATE INDEX IF NOT EXISTS idx_raw_calendar_available ON raw.calendar(available);
CREATE INDEX IF NOT EXISTS idx_raw_calendar_listing_date ON raw.calendar(listing_id, date);