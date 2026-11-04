# Configuration

Configuration lives in one typed object (`src.config.AppConfig`) built from `configs/config.yaml` and optional environment overrides. Values are resolved through an explicit precedence chain, highest priority first:

1. CLI / init arguments (`--config`, `AppConfig(..., database={...})`)
2. process environment variables
3. `.env` file
4. `configs/config.yaml`: the primary declarative file
5. defaults declared in the code

Unknown keys in `config.yaml` raise an error, so typos surface immediately instead of being silently ignored. The config object is immutable once built.

## YAML config

This is the file to edit. It is loaded by default, no flag needed.

```yaml
database:
  host: localhost
  port: 5432
  name: airbnb
  user: airbnb
  password: airbnb

data:
  data_path: ./data                 # raw/ and processed/ are derived from this
  listings_file: listings.parquet   # .csv / .csv.gz also work
  calendar_file: calendar.parquet

dashboard:
  source: auto           # auto | postgres | duckdb
  demo_dir: data/demo    # Parquet demo layer (used by the duckdb source)

pipeline:
  batch_size: 100000     # rows per COPY/INSERT batch
  chunk_size: 250000     # rows read per pandas pass
  validate_data: true
  skip_invalid_rows: false
  use_copy: true         # COPY FROM STDIN (false = row-wise INSERT fallback)

logging:
  level: INFO
```

## Environment overrides

Optional. Use these to override `config.yaml` for CI, Docker or one-off runs without editing the file. See `configs/.env.example` for the full list.

```bash
# Database (overrides database.*)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=airbnb
POSTGRES_USER=airbnb
POSTGRES_PASSWORD=airbnb

# Data root (overrides data.data_path)
DATA_PATH=./data

# Dashboard data source (overrides dashboard.*)
DASHBOARD_SOURCE=auto
DASHBOARD_DEMO_DIR=data/demo

# Pipeline (overrides pipeline.*)
BATCH_SIZE=100000
CHUNK_SIZE=250000
VALIDATE_DATA=true
SKIP_INVALID_ROWS=false
USE_COPY=true

# Logging (overrides logging.level)
LOG_LEVEL=INFO
```

## Related

- [Setup](setup.md) for local development and Docker
- [Schema](schema.md) for what each layer holds
