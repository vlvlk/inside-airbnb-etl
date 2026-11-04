# Schema

The pipeline writes three layers into PostgreSQL, each in its own schema. Queries and the dashboard read the marts only.

## Data layers

| Layer | Schema | Tables | Purpose |
| ------- | -------- | -------- | --------- |
| **Raw** | `raw` | `listings`, `calendar` | 1:1 copy of CSV with minimal validation |
| **Staging** | `staging` | `listings`, `calendar` | Cleaned, typed data with derived time dimensions |
| **Marts** | `marts` | `occupancy_by_listing`, `occupancy_by_neighbourhood`, `occupancy_by_room_type`, `revenue_by_listing` | Pre-aggregated metrics for analytics |

## Raw tables

```sql
raw.listings      -- All listing fields from CSV
raw.calendar      -- listing_id, date, available, min/max nights
```

## Staging tables

```sql
staging.listings  -- Cleaned listings with typed fields
staging.calendar  -- Calendar with derived time dimensions (year, month, week, quarter, is_weekend)
```

## Marts tables

```sql
marts.occupancy_by_listing         -- Occupancy per listing per time period
marts.occupancy_by_neighbourhood   -- Occupancy per neighbourhood per time period
marts.occupancy_by_room_type       -- Occupancy per room type per time period
marts.revenue_by_listing           -- ADR, RevPAR, total revenue per listing
marts.v_occupancy_summary          -- Overall summary view
```

## Key metrics

- **Occupancy Rate** = `booked_nights / total_nights` (a fraction in `[0, 1]`). `booked_nights` counts every night flagged unavailable, so this is an upper bound; see [`methodology.md`](methodology.md:1).
- **ADR (Average Daily Rate)** = Average price per booked night
- **RevPAR (Revenue Per Available Room)** = Total revenue / available nights

Revenue is estimated from each listing's single scraped price (the calendar snapshot carries no per-night price), so ADR, RevPAR and total revenue are estimates over the priced subset of listings. The measured size of each gap is in [`methodology.md`](methodology.md:1).

Calculated at multiple granularities:

- By listing
- By neighbourhood
- By room type
- By time period (year, month, week, quarter)

## Data sources

The repository ships one Inside Airbnb snapshot, committed as Parquet in `data/raw/`:

- `listings.parquet`: Toronto listings scraped 2026-09-16, all 90 CSV columns
- `calendar.parquet`: availability calendar covering 2026-09-17 → 2027-09-17

Source: [Inside Airbnb](https://insideairbnb.com/get-the-data) (Toronto, Canada). A copy of the same snapshot is on [Kaggle](https://www.kaggle.com/datasets/vladimirkondratev/inside-airbnb-toronto-sep-2026/).

The original `csv.gz` downloads are not committed. Rebuild the Parquet artifacts with [`scripts/csv_to_parquet.py`](../scripts/csv_to_parquet.py:1); the pipeline reads whichever format `data.listings_file` / `data.calendar_file` point at.

## Related

- [Queries](queries.md) for the SQL that reads these tables
- [Setup](setup.md) for loading a different snapshot
