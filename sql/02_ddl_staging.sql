-- Staging layer DDL: cleaned and typed data
-- Schema: staging

CREATE SCHEMA IF NOT EXISTS staging;

-- Staging listings table - cleaned and typed for analytics
CREATE TABLE IF NOT EXISTS staging.listings (
    listing_id BIGINT PRIMARY KEY,
    listing_url TEXT,
    scrape_id TEXT,
    last_scraped DATE,
    name TEXT,
    description TEXT,
    picture_url TEXT,
    host_id BIGINT,
    host_name TEXT,
    host_since DATE,
    host_is_superhost BOOLEAN,
    host_identity_verified BOOLEAN,
    host_listings_count INTEGER,
    neighbourhood TEXT,
    neighbourhood_cleansed TEXT,
    neighbourhood_group_cleansed TEXT,
    latitude NUMERIC(10, 6),
    longitude NUMERIC(10, 6),
    property_type TEXT,
    room_type TEXT,
    accommodates INTEGER,
    bathrooms NUMERIC(4, 2),
    bedrooms INTEGER,
    beds INTEGER,
    price NUMERIC(10, 2),
    price_per_night NUMERIC(10, 2),
    minimum_nights INTEGER,
    maximum_nights INTEGER,
    has_availability BOOLEAN,
    availability_30 INTEGER,
    availability_60 INTEGER,
    availability_90 INTEGER,
    availability_365 INTEGER,
    calendar_last_scraped DATE,
    number_of_reviews INTEGER,
    number_of_reviews_ltm INTEGER,
    review_scores_rating NUMERIC(3, 2),
    review_scores_cleanliness NUMERIC(3, 2),
    review_scores_checkin NUMERIC(3, 2),
    review_scores_communication NUMERIC(3, 2),
    review_scores_location NUMERIC(3, 2),
    review_scores_value NUMERIC(3, 2),
    instant_bookable BOOLEAN,
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for analytics queries
CREATE INDEX IF NOT EXISTS idx_stg_listings_neighbourhood_cleansed ON staging.listings(neighbourhood_cleansed);
CREATE INDEX IF NOT EXISTS idx_stg_listings_host_id ON staging.listings(host_id);
CREATE INDEX IF NOT EXISTS idx_stg_listings_room_type ON staging.listings(room_type);
CREATE INDEX IF NOT EXISTS idx_stg_listings_property_type ON staging.listings(property_type);
CREATE INDEX IF NOT EXISTS idx_stg_listings_price ON staging.listings(price);
CREATE INDEX IF NOT EXISTS idx_stg_listings_last_scraped ON staging.listings(last_scraped);

-- Staging calendar table - cleaned with derived time dimensions
CREATE TABLE IF NOT EXISTS staging.calendar (
    listing_id BIGINT NOT NULL,
    date DATE NOT NULL,
    available BOOLEAN NOT NULL,  -- True = available, False = booked
    minimum_nights INTEGER,
    maximum_nights INTEGER,
    -- Derived time dimensions
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,  -- 0=Monday, 6=Sunday
    week_of_year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    is_weekend BOOLEAN NOT NULL,
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (listing_id, date)
);

-- Indexes for time-series analytics
CREATE INDEX IF NOT EXISTS idx_stg_calendar_date ON staging.calendar(date);
CREATE INDEX IF NOT EXISTS idx_stg_calendar_available ON staging.calendar(available);
CREATE INDEX IF NOT EXISTS idx_stg_calendar_year_month ON staging.calendar(year, month);
CREATE INDEX IF NOT EXISTS idx_stg_calendar_listing_date ON staging.calendar(listing_id, date);
CREATE INDEX IF NOT EXISTS idx_stg_calendar_year_week ON staging.calendar(year, week_of_year);