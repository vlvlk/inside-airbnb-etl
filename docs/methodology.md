# Methodology and known limitations

This document records how each metric is defined, which assumption it rests on,
and how large the resulting error is in the bundled snapshot. The numbers below
are measured against the committed Toronto data (Inside Airbnb, 2026-09-17 →
2027-09-17) and are recomputed by [`sql/queries/data_quality.sql`](../sql/queries/data_quality.sql)
and the Insights page.

The short version: **the occupancy figure is an upper bound, and the revenue
figure is an estimate.** Both are useful, neither is exact, and the size of each
gap is given below.

---

## Where the numbers come from

The dashboard can be served by two engines, and both produce the figures in this
document:

| Engine | How it gets the data |
| ------ | -------------------- |
| PostgreSQL | `python -m src.pipeline` runs the ETL, then the dashboard reads `marts` |
| DuckDB demo layer | `python -m scripts.build_demo_marts` runs the *same* SQL scripts in DuckDB and exports Parquet |

The demo path is not a second implementation. It executes the same
`sql/01..05_*.sql` files and the same vectorized normalizers, and the build
script refuses to write the layer unless the four headline figures below match
exactly. That check is also a test
([`tests/test_backend.py`](../tests/test_backend.py:1)), so a drift between the
two engines fails CI rather than reaching a reader.

One deliberate difference: the demo layer narrows `raw.listings` to the `id`
column and stores distinct listing ids for `staging.calendar`, because the only
query that reads those layers (`sql/queries/data_quality.sql`) counts rows and
joins on `listing_id`. The Data quality page therefore reports the same counts
from both engines, but the demo layer does not carry the full raw payload.

---

## Metric definitions

| Metric | Formula | Where |
| ------ | ------- | ----- |
| `occupancy_rate` | `booked_nights / total_nights` | `marts.occupancy_by_*` |
| `booked_nights` | `COUNT(*) FILTER (WHERE NOT available)` | `sql/05_transform_marts.sql` |
| `available_nights` | `COUNT(*) FILTER (WHERE available)` | `sql/05_transform_marts.sql` |
| `avg_price_per_night` | `AVG(price_per_night)` over **all** nights | `sql/05_transform_marts.sql` |
| `avg_daily_rate` (ADR) | `SUM(price_per_night) / booked_nights` | `sql/05_transform_marts.sql` |
| `revenue_per_available_night` (RevPAR) | `SUM(price_per_night) / available_nights` | `sql/05_transform_marts.sql` |
| `total_revenue` | `SUM(price_per_night) FILTER (WHERE NOT available)` | `sql/05_transform_marts.sql` |

Headline values in the bundled snapshot:

| Quantity | Value |
| -------- | ----- |
| Calendar nights | 8,048,251 |
| Booked nights (unavailable) | 3,814,938 |
| **Occupancy rate** | **47.4%** |
| Estimated total revenue | $538,161,557 |
| ADR (booked nights, priced listings) | $238.50 |
| RevPAR (available nights, priced listings) | $139.43 |
| `avg_price_per_night` (all nights) | $201.90 |

---

## Limitation 1 — "unavailable" is not the same as "booked"

**The assumption.** The pipeline treats every night with `available = false` as a
booked night. Inside Airbnb's calendar does not distinguish a real reservation
from a night the host blocked by hand (maintenance, a stay of their own, a
deliberate gap between bookings). Every such night is counted as revenue.

**How big is the gap.** Inside Airbnb ships its own occupancy estimate in
`listings.estimated_occupancy_l365d`. Comparing the two:

| Source | Occupancy |
| ------ | --------- |
| This pipeline (`booked_nights / total_nights`) | 47.4% |
| Inside Airbnb `estimated_occupancy_l365d` (72.6 nights / 365) | 19.9% |

The two disagree by more than a factor of two, and their per-listing correlation
is **−0.02** — statistically indistinguishable from zero. Inside Airbnb's own
estimate is itself a model (it infers stays from review cadence), so neither
number is ground truth, but the size of the disagreement is the point: **treat
47.4% as a ceiling, not a measurement.**

**What to do with it.** Report occupancy as "unavailable nights" and say so. Any
comparison between neighbourhoods, room types or host segments is still valid as
long as the same definition is applied on both sides, because the bias applies
uniformly. Absolute levels should not be quoted as bookings.

---

## Limitation 2 — revenue is estimated from a single static price

**The assumption.** The calendar snapshot carries only five columns —
`listing_id, date, available, minimum_nights, maximum_nights`. It has no
per-night price. The pipeline therefore values every night of a listing at the
one price scraped for that listing (`staging.listings.price_per_night`).

**Why that is wrong.** Real nightly prices vary with season, weekend, lead time
and last-minute discounts. A flat price cannot capture any of that.

**How big is the gap.** The artefact is visible directly in the seasonality
query: `avg_price_per_night` is **$201.88 in every month** — identical across the
whole year, which is impossible for real prices. The two "average prices" the
pipeline produces are not the same quantity:

| Metric | Averaged over | Value |
| ------ | ------------- | ----- |
| `avg_price_per_night` | every night (booked or not) | $201.90 |
| `avg_daily_rate` | booked nights only, priced listings | $238.50 |
| ADR computed the wrong way (revenue ÷ all booked nights) | mixes populations | $141 |

**What to do with it.** Treat `total_revenue` as an upper-bound estimate and
read it as "revenue at the listed price", not "revenue earned". A ±20% band is a
reasonable sensitivity range given typical seasonal spreads. The loss is
structural: the price columns inside Airbnb publishes (`price`,
`adjusted_price` in the full `calendar.csv.gz`) are dropped at ingest, which is
the single highest-value fix for a future snapshot.

---

## Limitation 3 — two different "average prices" coexist

`avg_price_per_night` averages all nights; `avg_daily_rate` averages only booked
nights. They answer different questions and must not be used interchangeably in
the same comparison. The occupancy marts use the former, the revenue marts the
latter, so a chart that mixes both (for example price-vs-occupancy next to an ADR
trend) is comparing two denominators.

The two definitions also cover **different populations**: `avg_price_per_night`
comes from the occupancy marts (every listing with calendar data) while ADR comes
from the revenue marts (priced listings only). Dividing revenue by the wider
occupancy night count — the obvious-looking shortcut — understates ADR by about
40% ($141 instead of $238). [`sql/queries/overall_kpis.sql`](../sql/queries/overall_kpis.sql)
therefore carries the revenue side's own night counts (`rev_booked_nights`,
`rev_available_nights`) so callers can keep the ratio inside one population.

---

## Limitation 4 — stale listings survive in the staging layer

`staging.listings` holds **37,432 rows** while the raw layer holds **22,050**.
The staging transform is an upsert (`ON CONFLICT ... DO UPDATE`) and never
deletes, so listings from earlier snapshots stay behind after they disappear from
the source. **15,382** of those ghost rows have no calendar data.

The marts join listings to the calendar, so ghosts never reach a metric — but any
query that reads `staging.listings` directly will over-count. The Data quality
page surfaces this count on every run.

---

## Limitation 5 — the revenue marts cover a subset of the market

**7,634** listings carry no `price_per_night` and are excluded from
`marts.revenue_by_listing`. ADR, RevPAR and `total_revenue` therefore describe
the priced subset only, while occupancy covers every listing with calendar data.
Segment-level revenue (for example by host size) is computed over the priced
subset and is not directly comparable with the occupancy columns for the same
segment.

---

## Limitation 6 — dropped rows and dormant listings

- **Calendar rows with a NULL availability flag** are removed by the staging
  filter (`WHERE available IS NOT NULL`). In the bundled snapshot this count is
  0, but a listing with a fully blank calendar would silently vanish from every
  metric.
- **1,156 listings show exactly 0% occupancy** — available every single night for
  a year. These are more likely dormant or mispriced than genuinely unbooked, so
  the bottom of any occupancy ranking should be read with care.

---

## Defects found and fixed while writing this document

Auditing the metrics against the data surfaced three bugs that were silently
producing wrong numbers. All three are fixed, and the fix is noted so the
reasoning is not lost.

1. **KPI totals counted the same nights three or four times.** `overall_kpis`
   returns weekly, monthly, quarterly and yearly rows in one result set. The
   Overview page summed the whole frame, so "Total revenue" read $1.6B (3x the
   true $538M) and "Booked nights" read 15.3M (4x the true 3.8M). The page now
   sums only the rows at the selected granularity.

2. **ADR mixed two populations.** Revenue (priced listings) was divided by booked
   nights (all listings), giving $141 instead of $238. `overall_kpis` now returns
   `rev_booked_nights` / `rev_available_nights` and the pages divide within the
   revenue population.

3. **Weekly rows carried quarterly revenue.** `marts.revenue_by_listing` has no
   `week_of_year`, so the join attached each quarter's revenue to every week in
   it. Weekly revenue is now explicitly NULL rather than silently wrong.

---

## What a future snapshot should fix, in order of value

1. **Ingest the per-night price columns** from the full `calendar.csv.gz`
   (`price`, `adjusted_price`). This removes Limitation 2 entirely and turns
   `total_revenue` from an estimate into a measurement.
2. **Separate `booked` from `blocked`.** Inside Airbnb does not publish the
   distinction, but it can be approximated (a night is a booking if it is
   bracketed by reviews or follows a minimum-stay pattern). This shrinks
   Limitation 1.
3. **Delete stale rows in the staging upsert** (or track `last_seen_at`) so
   `staging.listings` matches the current snapshot. This removes Limitation 4.
4. **Add a `reviews.csv` ingest** as an independent cross-check on occupancy,
   the same role `estimated_occupancy_l365d` plays above.
