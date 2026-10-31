-- Occupancy per listing per period, for every granularity.
SELECT
    listing_id,
    year,
    month,
    week_of_year,
    quarter,
    total_nights,
    available_nights,
    booked_nights,
    occupancy_rate
FROM marts.occupancy_by_listing
ORDER BY year, month NULLS LAST, week_of_year NULLS LAST, quarter NULLS LAST;
