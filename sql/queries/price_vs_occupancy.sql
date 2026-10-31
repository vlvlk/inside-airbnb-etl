-- Price vs. occupancy by room type and month, for the scatter plot that shows
-- whether higher-priced segments actually fill more nights.
SELECT
    room_type,
    year,
    month,
    total_listings,
    total_nights,
    booked_nights,
    occupancy_rate,
    avg_price_per_night
FROM marts.occupancy_by_room_type
WHERE month IS NOT NULL
  AND avg_price_per_night IS NOT NULL
ORDER BY year, month, room_type;
