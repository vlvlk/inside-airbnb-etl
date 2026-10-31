-- Occupancy and average price per room type, for every granularity.
SELECT
    room_type,
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
FROM marts.occupancy_by_room_type
ORDER BY
    year,
    month NULLS LAST,
    week_of_year NULLS LAST,
    quarter NULLS LAST,
    occupancy_rate DESC;
