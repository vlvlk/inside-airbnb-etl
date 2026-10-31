-- Seasonality: occupancy collapsed by calendar month across all years.
--
-- Neighbourhood rows are summed (each listing belongs to exactly one
-- neighbourhood), so ``total_nights`` is the true portfolio total rather than a
-- double count.
SELECT
    month,
    SUM(total_nights) AS total_nights,
    SUM(booked_nights) AS booked_nights,
    SUM(booked_nights)::NUMERIC / NULLIF(SUM(total_nights), 0) AS occupancy_rate,
    AVG(avg_price_per_night) AS avg_price_per_night
FROM marts.occupancy_by_neighbourhood
WHERE month IS NOT NULL
GROUP BY month
ORDER BY month;
