# Setup

The Toronto snapshot ships with the repository as Parquet, so a fresh clone runs end to end with no download step and no network access. Two paths are supported: a dashboard without a database, and the full PostgreSQL pipeline through Docker.

## Run the dashboard without a database

No database, no Docker, no 8M-row load:

```bash
uv sync
streamlit run src/dashboard/app.py
```

The dashboard reads a committed Parquet demo layer (`data/demo/`, ~14 MB) built from the same snapshot. Every query, chart and metric is the same one the PostgreSQL path produces: the SQL files in [`sql/queries/`](../sql/queries/overall_kpis.sql:1) are shared, and the build script verifies the demo layer against the figures in [`methodology.md`](methodology.md:1) before writing it. The sidebar shows a **Demo data** badge so it is always clear which source is live.

To rebuild the demo layer after changing the pipeline:

```bash
python -m scripts.build_demo_marts --force
```

## Prerequisites

- Docker & Docker Compose (for the PostgreSQL path)
- Python 3.12 (for local development)

## Run with Docker (recommended)

```bash
# Start PostgreSQL, run the pipeline, then serve the dashboard on :8501
docker-compose -f docker/docker-compose.yml up --build
```

The `dashboard` service waits for the pipeline (`app`) to finish before it starts, so `http://localhost:8501` is ready once the load completes. To run only the ETL step, start the `app` service on its own:

```bash
docker-compose -f docker/docker-compose.yml up --build app
```

**Restarting the dashboard re-runs the whole ETL.** `docker compose up dashboard` also starts the `app` dependency, because the dashboard waits for it with `condition: service_completed_successfully`. Compose therefore reloads all 8.0M calendar rows (~7 minutes) before the dashboard comes back, which looks like a hang but is a full reload. When the mart data is already loaded and only the dashboard code changed, skip the dependency:

```bash
docker compose -f docker/docker-compose.yml up -d --no-deps --build dashboard
```

This rebuilds and restarts only the dashboard container and leaves the loaded database untouched.

## Local development

```bash
# 1. Install dependencies
uv sync --extra dev

# 2. Start PostgreSQL
docker-compose -f docker/docker-compose.yml up -d postgres

# 3. Run pipeline (configs/config.yaml is used by default)
python -m src.pipeline

# 4. Explore the results in the dashboard
streamlit run src/dashboard/app.py

# Optional: override settings via .env
cp configs/.env.example .env
```

## Bundled dataset

The committed artifacts come from the Inside Airbnb snapshot for **Toronto, Canada**: listings scraped **2026-09-16**, calendar covering **2026-09-17 → 2027-09-17** ([source](https://insideairbnb.com/get-the-data)):

| File | Rows | Columns | Size |
| ------ | ------ | --------- | ------ |
| `data/raw/listings.parquet` | 22,050 | 90 (all CSV columns) | 7.4 MB |
| `data/raw/calendar.parquet` | 8,048,251 | 5 | 2.1 MB |

Parquet keeps the repository small: the same data as `csv.gz` is 31.7 MB, so the committed form is ~3.3x lighter. The listings file keeps every column, so the raw layer stays a 1:1 copy of the CSV.

A copy of the same snapshot is also published on [Kaggle](https://www.kaggle.com/datasets/vladimirkondratev/inside-airbnb-toronto-sep-2026/) if you prefer downloading it from there.

## Switch to another city or snapshot

Download the `csv.gz` files from Inside Airbnb and rebuild the artifacts:

```bash
python scripts/csv_to_parquet.py
# or point it at explicit files
python scripts/csv_to_parquet.py --listings /tmp/listings.csv.gz --calendar /tmp/calendar.csv.gz
```

The extractor is chosen from the configured extension, so pointing `data.listings_file` at a `.csv` / `.csv.gz` file makes the pipeline read the original downloads directly.

A full pipeline run **replaces** the loaded snapshot: `raw`, `staging` and `marts` are truncated before the load, so a listing that disappeared from the source, or every row of a previous city, cannot survive the upsert and leak into the dashboard. This is controlled by `pipeline.replace_on_load` (`REPLACE_ON_LOAD`), on by default; set it to `false` only for a deliberate incremental append.

The dashboard reads PostgreSQL when it is reachable and falls back to the committed Parquet demo layer otherwise (`dashboard.source: auto`). The demo layer is a static artifact built from one snapshot, so after switching to a new city rebuild it locally to match:

```bash
python -m scripts.build_demo_marts --force
```

The build verifies the result against the Toronto figures in [`methodology.md`](methodology.md:1) and refuses to write a layer that does not reproduce them. When the demo layer is built from a *different* city, pass `--no-verify` so the build skips that snapshot-specific check:

```bash
python -m scripts.build_demo_marts --force --no-verify
```

## Related

- [Configuration](configuration.md) for `config.yaml` and environment overrides
- [Schema](schema.md) for the raw, staging and marts tables
- [Performance](performance.md) for load tuning and benchmarks
