-- Marts layer DDL: aggregated data for analytics
-- Schema: marts

CREATE SCHEMA IF NOT EXISTS marts;

-- Occupancy rate by listing and time period
CREATE TABLE IF NOT EXISTS marts.occupancy_by_listing (
    listing_id BIGINT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER,
    week_of_year INTEGER,
    quarter INTEGER,
    -- Aggregated metrics
    total_nights BIGINT NOT NULL,           -- Total nights in period
    available_nights BIGINT NOT NULL,       -- Nights where available = true
    booked_nights BIGINT NOT NULL,          -- Nights where available = false
    occupancy_rate NUMERIC(5, 4) NOT NULL,  -- booked_nights / total_nights, in [0, 1]
    -- Metadata
    calculated_at TIMESTAMPTZ DEFAULT NOW(),
    -- Granularity columns (month/week_of_year/quarter) are NULL for coarser
    -- periods, so a PRIMARY KEY (which implies NOT NULL) cannot be used here.
    -- UNIQUE NULLS NOT DISTINCT treats NULLs as equal, which keeps the target
    -- of the ``ON CONFLICT (...)`` upsert in sql/05_transform_marts.sql valid.
    UNIQUE NULLS NOT DISTINCT (listing_id, year, month, week_of_year, quarter)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_mart_occ_listing_year ON marts.occupancy_by_listing(listing_id, year);
CREATE INDEX IF NOT EXISTS idx_mart_occ_year_month ON marts.occupancy_by_listing(year, month);

-- Occupancy rate by neighbourhood and time period
CREATE TABLE IF NOT EXISTS marts.occupancy_by_neighbourhood (
    neighbourhood_cleansed TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER,
    week_of_year INTEGER,
    quarter INTEGER,
    -- Aggregated metrics
    total_listings BIGINT NOT NULL,
    total_nights BIGINT NOT NULL,
    available_nights BIGINT NOT NULL,
    booked_nights BIGINT NOT NULL,
    occupancy_rate NUMERIC(5, 4) NOT NULL,
    avg_price_per_night NUMERIC(10, 2),
    -- Metadata
    calculated_at TIMESTAMPTZ DEFAULT NOW(),
    -- See occupancy_by_listing: NULL granularity columns need NULLS NOT DISTINCT.
    UNIQUE NULLS NOT DISTINCT (neighbourhood_cleansed, year, month, week_of_year, quarter)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_mart_occ_nbhd_year ON marts.occupancy_by_neighbourhood(neighbourhood_cleansed, year);
CREATE INDEX IF NOT EXISTS idx_mart_occ_nbhd_year_month ON marts.occupancy_by_neighbourhood(year, month);

-- Occupancy rate by room type and time period
CREATE TABLE IF NOT EXISTS marts.occupancy_by_room_type (
    room_type TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER,
    week_of_year INTEGER,
    quarter INTEGER,
    -- Aggregated metrics
    total_listings BIGINT NOT NULL,
    total_nights BIGINT NOT NULL,
    available_nights BIGINT NOT NULL,
    booked_nights BIGINT NOT NULL,
    occupancy_rate NUMERIC(5, 4) NOT NULL,
    avg_price_per_night NUMERIC(10, 2),
    -- Metadata
    calculated_at TIMESTAMPTZ DEFAULT NOW(),
    -- See occupancy_by_listing: NULL granularity columns need NULLS NOT DISTINCT.
    UNIQUE NULLS NOT DISTINCT (room_type, year, month, week_of_year, quarter)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_mart_occ_room_year ON marts.occupancy_by_room_type(room_type, year);
CREATE INDEX IF NOT EXISTS idx_mart_occ_room_year_month ON marts.occupancy_by_room_type(year, month);

-- Revenue metrics by listing (ADR, RevPAR)
CREATE TABLE IF NOT EXISTS marts.revenue_by_listing (
    listing_id BIGINT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER,
    quarter INTEGER,
    -- Revenue metrics
    avg_daily_rate NUMERIC(10, 2),        -- ADR: average price per booked night
    revenue_per_available_night NUMERIC(10, 2),  -- RevPAR
    total_revenue NUMERIC(14, 2),         -- Estimated total revenue
    booked_nights BIGINT NOT NULL,
    available_nights BIGINT NOT NULL,
    occupancy_rate NUMERIC(5, 4) NOT NULL,
    -- Metadata
    calculated_at TIMESTAMPTZ DEFAULT NOW(),
    -- See occupancy_by_listing: NULL granularity columns need NULLS NOT DISTINCT.
    UNIQUE NULLS NOT DISTINCT (listing_id, year, month, quarter)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_mart_rev_listing_year ON marts.revenue_by_listing(listing_id, year);
CREATE INDEX IF NOT EXISTS idx_mart_rev_year_month ON marts.revenue_by_listing(year, month);

-- Summary view for quick dashboard queries
CREATE OR REPLACE VIEW marts.v_occupancy_summary AS
SELECT
    'overall' AS dimension,
    NULL::TEXT AS dimension_value,
    year,
    month,
    quarter,
    SUM(total_listings) AS total_listings,
    SUM(total_nights) AS total_nights,
    SUM(available_nights) AS available_nights,
    SUM(booked_nights) AS booked_nights,
    CASE WHEN SUM(total_nights) > 0
         THEN SUM(booked_nights)::NUMERIC / SUM(total_nights)
         ELSE 0 END AS occupancy_rate,
    AVG(avg_price_per_night) AS avg_price_per_night
FROM (
    SELECT year, month, quarter, total_listings, total_nights,
           available_nights, booked_nights, avg_price_per_night
    FROM marts.occupancy_by_neighbourhood
    UNION ALL
    SELECT year, month, quarter, total_listings, total_nights,
           available_nights, booked_nights, avg_price_per_night
    FROM marts.occupancy_by_room_type
) combined
GROUP BY year, month, quarter
ORDER BY year, month, quarter;