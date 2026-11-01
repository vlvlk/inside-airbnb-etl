-- Occupancy, price and revenue by host portfolio size.
--
-- Answers the question every Airbnb market study has to answer: is the market
-- driven by ordinary people renting out one home, or by professional hosts
-- running a portfolio? The segment comes from
-- ``staging.listings.host_listings_count`` (how many listings the host has on
-- the platform).
--
-- Listings are joined to the calendar-backed marts, so the ghost rows that
-- earlier snapshots leave behind in ``staging.listings`` (the upsert never
-- deletes) never reach the aggregates.
--
-- Revenue columns come from ``marts.revenue_by_listing``, which only covers
-- listings that carry a price, so ADR/RevPAR are computed over that subset and
-- are not directly comparable with the occupancy columns.
WITH listing_segment AS (
    SELECT
        l.listing_id,
        CASE
            WHEN l.host_listings_count >= 5 THEN 'Professional (5+ listings)'
            WHEN l.host_listings_count >= 2 THEN 'Small portfolio (2-4 listings)'
            ELSE 'Single listing'
        END AS host_segment
    FROM staging.listings l
    WHERE l.host_listings_count IS NOT NULL
),
occ AS (
    SELECT
        s.host_segment,
        o.year,
        COUNT(DISTINCT o.listing_id) AS total_listings,
        SUM(o.total_nights) AS total_nights,
        SUM(o.booked_nights) AS booked_nights,
        SUM(o.available_nights) AS available_nights
    FROM marts.occupancy_by_listing o
    JOIN listing_segment s USING (listing_id)
    WHERE o.month IS NULL
      AND o.week_of_year IS NULL
      AND o.quarter IS NULL
    GROUP BY s.host_segment, o.year
),
rev AS (
    SELECT
        s.host_segment,
        r.year,
        SUM(r.total_revenue) AS total_revenue,
        SUM(r.booked_nights) AS booked_nights,
        SUM(r.available_nights) AS available_nights
    FROM marts.revenue_by_listing r
    JOIN listing_segment s USING (listing_id)
    WHERE r.month IS NULL
      AND r.quarter IS NULL
    GROUP BY s.host_segment, r.year
)
SELECT
    o.host_segment,
    o.year,
    o.total_listings,
    o.total_nights,
    o.booked_nights,
    o.booked_nights::NUMERIC / NULLIF(o.total_nights, 0) AS occupancy_rate,
    r.total_revenue / NULLIF(r.booked_nights, 0) AS avg_daily_rate,
    r.total_revenue / NULLIF(r.available_nights, 0) AS revenue_per_available_night,
    r.total_revenue
FROM occ o
LEFT JOIN rev r
    ON r.host_segment = o.host_segment
   AND r.year = o.year
ORDER BY o.year, occupancy_rate DESC;
