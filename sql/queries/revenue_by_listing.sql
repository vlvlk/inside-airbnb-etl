-- Revenue metrics (ADR, RevPAR, total revenue) per listing per period.
SELECT
    listing_id,
    year,
    month,
    quarter,
    avg_daily_rate,
    revenue_per_available_night,
    total_revenue,
    booked_nights,
    available_nights,
    occupancy_rate
FROM marts.revenue_by_listing
ORDER BY year, month NULLS LAST, quarter NULLS LAST;
