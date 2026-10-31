-- Neighbourhood leaderboard per year: occupancy rank inside each year, taken
-- from the yearly rows only (month, week_of_year and quarter all NULL).
SELECT
    neighbourhood_cleansed,
    year,
    total_listings,
    occupancy_rate,
    avg_price_per_night,
    RANK() OVER (
        PARTITION BY year
        ORDER BY occupancy_rate DESC
    ) AS occupancy_rank
FROM marts.occupancy_by_neighbourhood
WHERE month IS NULL
  AND week_of_year IS NULL
  AND quarter IS NULL
ORDER BY year, occupancy_rank;
