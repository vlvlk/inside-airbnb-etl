# Queries

Every dashboard view is backed by a plain SQL file in [`sql/queries/`](../sql/queries/overall_kpis.sql:1), so the same statements can be run by hand.

| File | Purpose |
| ------ | --------- |
| [`overall_kpis.sql`](../sql/queries/overall_kpis.sql:1) | Portfolio KPIs per period (occupancy + revenue joined on granularity) |
| [`occupancy_by_neighbourhood.sql`](../sql/queries/occupancy_by_neighbourhood.sql:1) | Occupancy and price per neighbourhood, all granularities |
| [`occupancy_by_room_type.sql`](../sql/queries/occupancy_by_room_type.sql:1) | Occupancy and price per room type |
| [`occupancy_by_listing.sql`](../sql/queries/occupancy_by_listing.sql:1) | Occupancy per listing |
| [`revenue_by_listing.sql`](../sql/queries/revenue_by_listing.sql:1) | ADR, RevPAR, revenue per listing |
| [`host_segmentation.sql`](../sql/queries/host_segmentation.sql:1) | Occupancy, ADR and RevPAR by host portfolio size (single vs professional) |
| [`top_listings_by_revpar.sql`](../sql/queries/top_listings_by_revpar.sql:1) | Top listings by RevPAR per month (window ranking; takes a `:limit` bind marker) |
| [`seasonality.sql`](../sql/queries/seasonality.sql:1) | Occupancy collapsed by calendar month |
| [`neighbourhood_ranking.sql`](../sql/queries/neighbourhood_ranking.sql:1) | Neighbourhood leaderboard per year |
| [`price_vs_occupancy.sql`](../sql/queries/price_vs_occupancy.sql:1) | Price vs. occupancy by room type and month |
| [`data_quality.sql`](../sql/queries/data_quality.sql:1) | Layer counts and data quality checks (ghosts, missing prices, dropped rows) |

Run one directly:

```bash
psql -h localhost -U airbnb -d airbnb -f sql/queries/seasonality.sql
```

Ten of the eleven files run through `psql` unchanged. `top_listings_by_revpar.sql` is the exception: it takes a `:limit` bind parameter, which `psql` does not substitute, so pass it explicitly:

```bash
psql -h localhost -U airbnb -d airbnb -v limit=20 \
  -f sql/queries/top_listings_by_revpar.sql
```

## Ad-hoc examples

Occupancy by neighbourhood (monthly):

```sql
SELECT
    neighbourhood_cleansed,
    year,
    month,
    total_listings,
    occupancy_rate,
    avg_price_per_night
FROM marts.occupancy_by_neighbourhood
WHERE month IS NOT NULL
ORDER BY year, month, occupancy_rate DESC;
```

Top listings by RevPAR:

```sql
SELECT
    listing_id,
    year,
    month,
    revenue_per_available_night AS revpar,
    avg_daily_rate AS adr,
    occupancy_rate
FROM marts.revenue_by_listing
WHERE month IS NOT NULL
  AND revenue_per_available_night IS NOT NULL
ORDER BY revpar DESC NULLS LAST
LIMIT 20;
```

The `NULLS LAST` clause matters: PostgreSQL sorts NULLs first on `DESC`, so without it the twenty rows you get back are the listings with no RevPAR at all.

Overall occupancy trend:

```sql
SELECT * FROM marts.v_occupancy_summary
ORDER BY year, month;
```

## Related

- [Schema](schema.md) for the columns each query reads
- [Dashboard](dashboard.md) for the SQL explorer page
