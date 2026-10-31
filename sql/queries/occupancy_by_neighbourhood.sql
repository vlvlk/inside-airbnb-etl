-- Occupancy and average price per neighbourhood, for every granularity
-- (monthly, weekly, quarterly, yearly). The dashboard filters the granularity
-- in pandas after this single cached load.
SELECT
    neighbourhood_cleansed,
    year,
    month,
    week_of_year,
    quarter,
    total_listings,
    total_nights,
    available_nights,
    booked_nights,
    occupancy_rate,
    avg_price_per_night
FROM marts.occupancy_by_neighbourhood
ORDER BY
    year,
    month NULLS LAST,
    week_of_year NULLS LAST,
    quarter NULLS LAST,
    occupancy_rate DESC;
