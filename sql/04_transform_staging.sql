-- Transform: Raw -> Staging
-- This script cleans and types data from raw layer to staging layer

-- ============================================================
-- Listings: Raw -> Staging
-- ============================================================

-- Upsert listings from raw to staging
INSERT INTO staging.listings (
    listing_id, listing_url, scrape_id, last_scraped,
    name, description, picture_url,
    host_id, host_name, host_since, host_is_superhost,
    host_identity_verified, host_listings_count,
    neighbourhood, neighbourhood_cleansed, neighbourhood_group_cleansed,
    latitude, longitude,
    property_type, room_type, accommodates, bathrooms, bedrooms, beds,
    price, price_per_night,
    minimum_nights, maximum_nights,
    has_availability, availability_30, availability_60, availability_90, availability_365,
    calendar_last_scraped,
    number_of_reviews, number_of_reviews_ltm,
    review_scores_rating, review_scores_cleanliness, review_scores_checkin,
    review_scores_communication, review_scores_location, review_scores_value,
    instant_bookable,
    updated_at
)
WITH cleaned_listings AS (
    SELECT
        id AS listing_id,
        listing_url,
        scrape_id,
        last_scraped,
        name,
        description,
        picture_url,
        host_id,
        host_name,
        host_since,
        CASE
            WHEN lower(host_is_superhost) IN ('t', 'true', '1', 'yes', 'y') THEN TRUE
            WHEN lower(host_is_superhost) IN ('f', 'false', '0', 'no', 'n') THEN FALSE
            ELSE NULL
        END AS host_is_superhost,
        CASE
            WHEN lower(host_identity_verified) IN ('t', 'true', '1', 'yes', 'y') THEN TRUE
            WHEN lower(host_identity_verified) IN ('f', 'false', '0', 'no', 'n') THEN FALSE
            ELSE NULL
        END AS host_identity_verified,
        host_listings_count,
        neighbourhood,
        neighbourhood_cleansed,
        neighbourhood_group_cleansed,
        latitude,
        longitude,
        property_type,
        room_type,
        accommodates,
        bathrooms,
        bedrooms,
        beds,
        -- Clean price: remove $ and commas
        CASE
            WHEN price IS NOT NULL AND price != ''
            THEN regexp_replace(price, '[$,]', '', 'g')::NUMERIC(10, 2)
            ELSE NULL
        END AS price,
        price_quote_price_per_night AS price_per_night,
        minimum_nights,
        maximum_nights,
        CASE
            WHEN lower(has_availability) IN ('t', 'true', '1', 'yes', 'y') THEN TRUE
            WHEN lower(has_availability) IN ('f', 'false', '0', 'no', 'n') THEN FALSE
            ELSE NULL
        END AS has_availability,
        availability_30,
        availability_60,
        availability_90,
        availability_365,
        calendar_last_scraped,
        number_of_reviews,
        number_of_reviews_ltm,
        review_scores_rating,
        review_scores_cleanliness,
        review_scores_checkin,
        review_scores_communication,
        review_scores_location,
        review_scores_value,
        CASE
            WHEN lower(instant_bookable) IN ('t', 'true', '1', 'yes', 'y') THEN TRUE
            WHEN lower(instant_bookable) IN ('f', 'false', '0', 'no', 'n') THEN FALSE
            ELSE NULL
        END AS instant_bookable,
        NOW() AS updated_at
    FROM raw.listings
)
SELECT * FROM cleaned_listings
ON CONFLICT (listing_id) DO UPDATE SET
    listing_url = EXCLUDED.listing_url,
    scrape_id = EXCLUDED.scrape_id,
    last_scraped = EXCLUDED.last_scraped,
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    picture_url = EXCLUDED.picture_url,
    host_id = EXCLUDED.host_id,
    host_name = EXCLUDED.host_name,
    host_since = EXCLUDED.host_since,
    host_is_superhost = EXCLUDED.host_is_superhost,
    host_identity_verified = EXCLUDED.host_identity_verified,
    host_listings_count = EXCLUDED.host_listings_count,
    neighbourhood = EXCLUDED.neighbourhood,
    neighbourhood_cleansed = EXCLUDED.neighbourhood_cleansed,
    neighbourhood_group_cleansed = EXCLUDED.neighbourhood_group_cleansed,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    property_type = EXCLUDED.property_type,
    room_type = EXCLUDED.room_type,
    accommodates = EXCLUDED.accommodates,
    bathrooms = EXCLUDED.bathrooms,
    bedrooms = EXCLUDED.bedrooms,
    beds = EXCLUDED.beds,
    price = EXCLUDED.price,
    price_per_night = EXCLUDED.price_per_night,
    minimum_nights = EXCLUDED.minimum_nights,
    maximum_nights = EXCLUDED.maximum_nights,
    has_availability = EXCLUDED.has_availability,
    availability_30 = EXCLUDED.availability_30,
    availability_60 = EXCLUDED.availability_60,
    availability_90 = EXCLUDED.availability_90,
    availability_365 = EXCLUDED.availability_365,
    calendar_last_scraped = EXCLUDED.calendar_last_scraped,
    number_of_reviews = EXCLUDED.number_of_reviews,
    number_of_reviews_ltm = EXCLUDED.number_of_reviews_ltm,
    review_scores_rating = EXCLUDED.review_scores_rating,
    review_scores_cleanliness = EXCLUDED.review_scores_cleanliness,
    review_scores_checkin = EXCLUDED.review_scores_checkin,
    review_scores_communication = EXCLUDED.review_scores_communication,
    review_scores_location = EXCLUDED.review_scores_location,
    review_scores_value = EXCLUDED.review_scores_value,
    instant_bookable = EXCLUDED.instant_bookable,
    updated_at = EXCLUDED.updated_at;

-- ============================================================
-- Calendar: Raw -> Staging
-- ============================================================

-- Upsert calendar from raw to staging with derived time dimensions
INSERT INTO staging.calendar (
    listing_id, date, available, minimum_nights, maximum_nights,
    year, month, day, day_of_week, week_of_year, quarter, is_weekend,
    created_at
)
WITH cleaned_calendar AS (
    SELECT
        listing_id,
        date,
        CASE
            WHEN lower(available) IN ('t', 'true', '1', 'yes', 'y') THEN TRUE
            WHEN lower(available) IN ('f', 'false', '0', 'no', 'n') THEN FALSE
            ELSE NULL
        END AS available,
        minimum_nights,
        maximum_nights,
        EXTRACT(YEAR FROM date)::INTEGER AS year,
        EXTRACT(MONTH FROM date)::INTEGER AS month,
        EXTRACT(DAY FROM date)::INTEGER AS day,
        -- ISODOW is 1=Monday..7=Sunday. Shift by 1 so day_of_week matches the
        -- Python ``date.weekday()`` convention used by CalendarStaging (0=Monday).
        (EXTRACT(ISODOW FROM date)::INTEGER - 1) AS day_of_week,
        EXTRACT(WEEK FROM date)::INTEGER AS week_of_year,
        EXTRACT(QUARTER FROM date)::INTEGER AS quarter,
        -- Saturday (6) and Sunday (7) in ISODOW terms.
        (EXTRACT(ISODOW FROM date)::INTEGER IN (6, 7)) AS is_weekend,
        NOW() AS created_at
    FROM raw.calendar
    WHERE available IS NOT NULL
)
SELECT * FROM cleaned_calendar
ON CONFLICT (listing_id, date) DO UPDATE SET
    available = EXCLUDED.available,
    minimum_nights = EXCLUDED.minimum_nights,
    maximum_nights = EXCLUDED.maximum_nights,
    year = EXCLUDED.year,
    month = EXCLUDED.month,
    day = EXCLUDED.day,
    day_of_week = EXCLUDED.day_of_week,
    week_of_year = EXCLUDED.week_of_year,
    quarter = EXCLUDED.quarter,
    is_weekend = EXCLUDED.is_weekend,
    created_at = EXCLUDED.created_at;