-- Top listings by RevPAR within each month, using a window function to rank
-- inside every (year, month) partition instead of a per-period loop.
--
-- ``:limit`` bounds the number of ranked rows returned.
SELECT
    listing_id,
    year,
    month,
    occupancy_rate,
    avg_daily_rate,
    revenue_per_available_night,
    total_revenue,
    booked_nights,
    available_nights,
    RANK() OVER (
        PARTITION BY year, month
        ORDER BY revenue_per_available_night DESC NULLS LAST
    ) AS revpar_rank
FROM marts.revenue_by_listing
WHERE month IS NOT NULL
  AND revenue_per_available_night IS NOT NULL
ORDER BY year, month, revpar_rank
LIMIT :limit;
