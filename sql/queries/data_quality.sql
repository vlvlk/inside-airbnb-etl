-- Data quality checks for the pipeline output.
--
-- One row per check, ordered by importance. Values are the raw counts; what
-- each one means for the metrics is written up in docs/methodology.md.
--
-- This query reads the raw and staging layers on purpose. A quality check has
-- to compare layers (raw vs staging vs marts), so it is the one dashboard query
-- that is not restricted to the marts schema.
SELECT * FROM (
    SELECT
        1 AS ord,
        'Listings in raw layer' AS check_name,
        (SELECT COUNT(*) FROM raw.listings) AS value,
        'Rows in raw.listings (one snapshot)' AS detail
    UNION ALL
    SELECT
        2,
        'Listings in staging layer',
        (SELECT COUNT(*) FROM staging.listings),
        'The upsert never deletes, so stale snapshots survive here'
    UNION ALL
    SELECT
        3,
        'Ghost listings (staging minus raw)',
        (SELECT COUNT(*) FROM staging.listings s
         LEFT JOIN raw.listings r ON r.id = s.listing_id
         WHERE r.id IS NULL),
        'Rows left behind by earlier snapshots; excluded from the marts'
    UNION ALL
    SELECT
        4,
        'Listings with calendar data',
        (SELECT COUNT(DISTINCT listing_id) FROM staging.calendar),
        'The only listings the marts can aggregate'
    UNION ALL
    SELECT
        5,
        'Listings without a price',
        (SELECT COUNT(*) FROM staging.listings WHERE price_per_night IS NULL),
        'Excluded from the revenue marts, so ADR/RevPAR cover a subset'
    UNION ALL
    SELECT
        6,
        'Calendar rows with NULL availability',
        (SELECT COUNT(*) FROM raw.calendar WHERE available IS NULL),
        'Dropped by the staging filter (available IS NOT NULL)'
    UNION ALL
    SELECT
        7,
        'Listings with zero booked nights',
        (SELECT COUNT(*) FROM (
            SELECT listing_id
            FROM marts.occupancy_by_listing
            WHERE month IS NULL AND week_of_year IS NULL AND quarter IS NULL
            GROUP BY listing_id
            HAVING SUM(booked_nights) = 0
        ) zero_occ),
        'Occupancy is exactly 0 for the whole year'
) checks
ORDER BY ord;
