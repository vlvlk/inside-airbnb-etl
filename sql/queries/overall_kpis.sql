-- Overall portfolio KPIs per period (weekly / monthly / quarterly / yearly).
--
-- Occupancy is aggregated from the listing-level mart (one row per listing per
-- period, so nights are never double counted), while revenue metrics come from
-- marts.revenue_by_listing. The two are joined on the full granularity key;
-- ``IS NOT DISTINCT FROM`` is required because coarser periods store NULL in
-- the finer granularity columns.
--
-- ``granularity`` tells the caller which row shape it is looking at:
--   'week'    -> week_of_year IS NOT NULL
--   'month'   -> month IS NOT NULL
--   'quarter' -> month IS NULL AND week_of_year IS NULL AND quarter IS NOT NULL
--   'year'    -> month, week_of_year and quarter all NULL
--
-- ``week_of_year`` is part of the grouping key: without it, weekly rows (which
-- have month IS NULL) would be merged into the quarterly bucket.
WITH occ AS (
    SELECT
        year,
        month,
        week_of_year,
        quarter,
        CASE
            WHEN week_of_year IS NOT NULL THEN 'week'
            WHEN month IS NOT NULL THEN 'month'
            WHEN quarter IS NOT NULL THEN 'quarter'
            ELSE 'year'
        END AS granularity,
        COUNT(DISTINCT listing_id) AS total_listings,
        SUM(total_nights) AS total_nights,
        SUM(available_nights) AS available_nights,
        SUM(booked_nights) AS booked_nights,
        SUM(booked_nights)::NUMERIC / NULLIF(SUM(total_nights), 0) AS occupancy_rate
    FROM marts.occupancy_by_listing
    GROUP BY year, month, week_of_year, quarter
),
rev AS (
    SELECT
        year,
        month,
        quarter,
        SUM(total_revenue) AS total_revenue,
        SUM(booked_nights) AS booked_nights,
        SUM(available_nights) AS available_nights,
        SUM(total_revenue) / NULLIF(SUM(booked_nights), 0) AS avg_daily_rate,
        SUM(total_revenue) / NULLIF(SUM(available_nights), 0) AS revenue_per_available_night
    FROM marts.revenue_by_listing
    GROUP BY year, month, quarter
)
SELECT
    o.year,
    o.month,
    o.week_of_year,
    o.quarter,
    o.granularity,
    o.total_listings,
    o.total_nights,
    o.available_nights,
    o.booked_nights,
    o.occupancy_rate,
    r.total_revenue,
    r.avg_daily_rate,
    r.revenue_per_available_night
FROM occ o
LEFT JOIN rev r
    ON r.year = o.year
   AND r.month IS NOT DISTINCT FROM o.month
   AND r.quarter IS NOT DISTINCT FROM o.quarter
ORDER BY o.year, o.month NULLS LAST, o.week_of_year NULLS LAST, o.quarter NULLS LAST;
