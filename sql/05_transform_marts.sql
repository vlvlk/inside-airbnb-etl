-- Transform: Staging -> Marts
-- This script calculates occupancy rates and revenue metrics

-- ============================================================
-- Occupancy by Listing
-- ============================================================

-- Monthly occupancy by listing
INSERT INTO marts.occupancy_by_listing (
    listing_id, year, month, week_of_year, quarter,
    total_nights, available_nights, booked_nights, occupancy_rate,
    calculated_at
)
WITH monthly_agg AS (
    SELECT
        c.listing_id,
        c.year,
        c.month,
        NULL::INTEGER AS week_of_year,
        c.quarter,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE c.available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT c.available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT c.available)::NUMERIC / COUNT(*) AS occupancy_rate,
        NOW() AS calculated_at
    FROM staging.calendar c
    GROUP BY c.listing_id, c.year, c.month, c.quarter
),
weekly_agg AS (
    SELECT
        c.listing_id,
        c.year,
        NULL::INTEGER AS month,
        c.week_of_year,
        c.quarter,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE c.available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT c.available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT c.available)::NUMERIC / COUNT(*) AS occupancy_rate,
        NOW() AS calculated_at
    FROM staging.calendar c
    GROUP BY c.listing_id, c.year, c.week_of_year, c.quarter
),
quarterly_agg AS (
    SELECT
        c.listing_id,
        c.year,
        NULL::INTEGER AS month,
        NULL::INTEGER AS week_of_year,
        c.quarter,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE c.available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT c.available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT c.available)::NUMERIC / COUNT(*) AS occupancy_rate,
        NOW() AS calculated_at
    FROM staging.calendar c
    GROUP BY c.listing_id, c.year, c.quarter
),
yearly_agg AS (
    SELECT
        c.listing_id,
        c.year,
        NULL::INTEGER AS month,
        NULL::INTEGER AS week_of_year,
        NULL::INTEGER AS quarter,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE c.available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT c.available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT c.available)::NUMERIC / COUNT(*) AS occupancy_rate,
        NOW() AS calculated_at
    FROM staging.calendar c
    GROUP BY c.listing_id, c.year
)
SELECT * FROM monthly_agg
UNION ALL
SELECT * FROM weekly_agg
UNION ALL
SELECT * FROM quarterly_agg
UNION ALL
SELECT * FROM yearly_agg
ON CONFLICT (listing_id, year, month, week_of_year, quarter) DO UPDATE SET
    total_nights = EXCLUDED.total_nights,
    available_nights = EXCLUDED.available_nights,
    booked_nights = EXCLUDED.booked_nights,
    occupancy_rate = EXCLUDED.occupancy_rate,
    calculated_at = EXCLUDED.calculated_at;

-- ============================================================
-- Occupancy by Neighbourhood
-- ============================================================

INSERT INTO marts.occupancy_by_neighbourhood (
    neighbourhood_cleansed, year, month, week_of_year, quarter,
    total_listings, total_nights, available_nights, booked_nights,
    occupancy_rate, avg_price_per_night,
    calculated_at
)
WITH listing_calendar AS (
    SELECT
        l.neighbourhood_cleansed,
        c.listing_id,
        c.date,
        c.available,
        c.year,
        c.month,
        c.week_of_year,
        c.quarter,
        l.price_per_night
    FROM staging.calendar c
    JOIN staging.listings l ON c.listing_id = l.listing_id
    WHERE l.neighbourhood_cleansed IS NOT NULL
),
monthly_nbhd AS (
    SELECT
        neighbourhood_cleansed,
        year,
        month,
        NULL::INTEGER AS week_of_year,
        quarter,
        COUNT(DISTINCT listing_id) AS total_listings,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        AVG(price_per_night) AS avg_price_per_night,
        NOW() AS calculated_at
    FROM listing_calendar
    GROUP BY neighbourhood_cleansed, year, month, quarter
),
weekly_nbhd AS (
    SELECT
        neighbourhood_cleansed,
        year,
        NULL::INTEGER AS month,
        week_of_year,
        quarter,
        COUNT(DISTINCT listing_id) AS total_listings,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        AVG(price_per_night) AS avg_price_per_night,
        NOW() AS calculated_at
    FROM listing_calendar
    GROUP BY neighbourhood_cleansed, year, week_of_year, quarter
),
quarterly_nbhd AS (
    SELECT
        neighbourhood_cleansed,
        year,
        NULL::INTEGER AS month,
        NULL::INTEGER AS week_of_year,
        quarter,
        COUNT(DISTINCT listing_id) AS total_listings,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        AVG(price_per_night) AS avg_price_per_night,
        NOW() AS calculated_at
    FROM listing_calendar
    GROUP BY neighbourhood_cleansed, year, quarter
),
yearly_nbhd AS (
    SELECT
        neighbourhood_cleansed,
        year,
        NULL::INTEGER AS month,
        NULL::INTEGER AS week_of_year,
        NULL::INTEGER AS quarter,
        COUNT(DISTINCT listing_id) AS total_listings,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        AVG(price_per_night) AS avg_price_per_night,
        NOW() AS calculated_at
    FROM listing_calendar
    GROUP BY neighbourhood_cleansed, year
)
SELECT * FROM monthly_nbhd
UNION ALL
SELECT * FROM weekly_nbhd
UNION ALL
SELECT * FROM quarterly_nbhd
UNION ALL
SELECT * FROM yearly_nbhd
ON CONFLICT (neighbourhood_cleansed, year, month, week_of_year, quarter) DO UPDATE SET
    total_listings = EXCLUDED.total_listings,
    total_nights = EXCLUDED.total_nights,
    available_nights = EXCLUDED.available_nights,
    booked_nights = EXCLUDED.booked_nights,
    occupancy_rate = EXCLUDED.occupancy_rate,
    avg_price_per_night = EXCLUDED.avg_price_per_night,
    calculated_at = EXCLUDED.calculated_at;

-- ============================================================
-- Occupancy by Room Type
-- ============================================================

INSERT INTO marts.occupancy_by_room_type (
    room_type, year, month, week_of_year, quarter,
    total_listings, total_nights, available_nights, booked_nights,
    occupancy_rate, avg_price_per_night,
    calculated_at
)
WITH listing_calendar AS (
    SELECT
        l.room_type,
        c.listing_id,
        c.date,
        c.available,
        c.year,
        c.month,
        c.week_of_year,
        c.quarter,
        l.price_per_night
    FROM staging.calendar c
    JOIN staging.listings l ON c.listing_id = l.listing_id
    WHERE l.room_type IS NOT NULL
),
monthly_room AS (
    SELECT
        room_type,
        year,
        month,
        NULL::INTEGER AS week_of_year,
        quarter,
        COUNT(DISTINCT listing_id) AS total_listings,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        AVG(price_per_night) AS avg_price_per_night,
        NOW() AS calculated_at
    FROM listing_calendar
    GROUP BY room_type, year, month, quarter
),
weekly_room AS (
    SELECT
        room_type,
        year,
        NULL::INTEGER AS month,
        week_of_year,
        quarter,
        COUNT(DISTINCT listing_id) AS total_listings,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        AVG(price_per_night) AS avg_price_per_night,
        NOW() AS calculated_at
    FROM listing_calendar
    GROUP BY room_type, year, week_of_year, quarter
),
quarterly_room AS (
    SELECT
        room_type,
        year,
        NULL::INTEGER AS month,
        NULL::INTEGER AS week_of_year,
        quarter,
        COUNT(DISTINCT listing_id) AS total_listings,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        AVG(price_per_night) AS avg_price_per_night,
        NOW() AS calculated_at
    FROM listing_calendar
    GROUP BY room_type, year, quarter
),
yearly_room AS (
    SELECT
        room_type,
        year,
        NULL::INTEGER AS month,
        NULL::INTEGER AS week_of_year,
        NULL::INTEGER AS quarter,
        COUNT(DISTINCT listing_id) AS total_listings,
        COUNT(*) AS total_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        AVG(price_per_night) AS avg_price_per_night,
        NOW() AS calculated_at
    FROM listing_calendar
    GROUP BY room_type, year
)
SELECT * FROM monthly_room
UNION ALL
SELECT * FROM weekly_room
UNION ALL
SELECT * FROM quarterly_room
UNION ALL
SELECT * FROM yearly_room
ON CONFLICT (room_type, year, month, week_of_year, quarter) DO UPDATE SET
    total_listings = EXCLUDED.total_listings,
    total_nights = EXCLUDED.total_nights,
    available_nights = EXCLUDED.available_nights,
    booked_nights = EXCLUDED.booked_nights,
    occupancy_rate = EXCLUDED.occupancy_rate,
    avg_price_per_night = EXCLUDED.avg_price_per_night,
    calculated_at = EXCLUDED.calculated_at;

-- ============================================================
-- Revenue by Listing (ADR, RevPAR)
-- ============================================================

INSERT INTO marts.revenue_by_listing (
    listing_id, year, month, quarter,
    avg_daily_rate, total_revenue, booked_nights, available_nights,
    occupancy_rate, revenue_per_available_night,
    calculated_at
)
WITH booked_calendar AS (
    SELECT
        c.listing_id,
        c.year,
        c.month,
        c.quarter,
        c.available,
        l.price_per_night
    FROM staging.calendar c
    JOIN staging.listings l ON c.listing_id = l.listing_id
    WHERE l.price_per_night IS NOT NULL
),
monthly_rev AS (
    SELECT
        listing_id,
        year,
        month,
        quarter,
        AVG(price_per_night) FILTER (WHERE NOT available) AS avg_daily_rate,
        SUM(price_per_night) FILTER (WHERE NOT available) AS total_revenue,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        CASE
            WHEN COUNT(*) FILTER (WHERE available) > 0
            THEN SUM(price_per_night) FILTER (WHERE NOT available) / COUNT(*) FILTER (WHERE available)
            ELSE 0
        END AS revenue_per_available_night,
        NOW() AS calculated_at
    FROM booked_calendar
    GROUP BY listing_id, year, month, quarter
),
quarterly_rev AS (
    SELECT
        listing_id,
        year,
        NULL::INTEGER AS month,
        quarter,
        AVG(price_per_night) FILTER (WHERE NOT available) AS avg_daily_rate,
        SUM(price_per_night) FILTER (WHERE NOT available) AS total_revenue,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        CASE
            WHEN COUNT(*) FILTER (WHERE available) > 0
            THEN SUM(price_per_night) FILTER (WHERE NOT available) / COUNT(*) FILTER (WHERE available)
            ELSE 0
        END AS revenue_per_available_night,
        NOW() AS calculated_at
    FROM booked_calendar
    GROUP BY listing_id, year, quarter
),
yearly_rev AS (
    SELECT
        listing_id,
        year,
        NULL::INTEGER AS month,
        NULL::INTEGER AS quarter,
        AVG(price_per_night) FILTER (WHERE NOT available) AS avg_daily_rate,
        SUM(price_per_night) FILTER (WHERE NOT available) AS total_revenue,
        COUNT(*) FILTER (WHERE NOT available) AS booked_nights,
        COUNT(*) FILTER (WHERE available) AS available_nights,
        COUNT(*) FILTER (WHERE NOT available)::NUMERIC / COUNT(*) AS occupancy_rate,
        CASE
            WHEN COUNT(*) FILTER (WHERE available) > 0
            THEN SUM(price_per_night) FILTER (WHERE NOT available) / COUNT(*) FILTER (WHERE available)
            ELSE 0
        END AS revenue_per_available_night,
        NOW() AS calculated_at
    FROM booked_calendar
    GROUP BY listing_id, year
)
SELECT * FROM monthly_rev
UNION ALL
SELECT * FROM quarterly_rev
UNION ALL
SELECT * FROM yearly_rev
ON CONFLICT (listing_id, year, month, quarter) DO UPDATE SET
    avg_daily_rate = EXCLUDED.avg_daily_rate,
    revenue_per_available_night = EXCLUDED.revenue_per_available_night,
    total_revenue = EXCLUDED.total_revenue,
    booked_nights = EXCLUDED.booked_nights,
    available_nights = EXCLUDED.available_nights,
    occupancy_rate = EXCLUDED.occupancy_rate,
    calculated_at = EXCLUDED.calculated_at;