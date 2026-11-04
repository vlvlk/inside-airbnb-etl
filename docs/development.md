# Development

## Testing

The test and lint tooling lives in the `dev` extra, so install it first:

```bash
uv sync --extra dev
```

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_models.py -v
```

## Code quality

```bash
# Lint
ruff check src tests

# Format
ruff format src tests

# Type check
pyright
```

CI runs `ruff check .`, `pyright` and `pytest` on every push, so keep the tree ruff-format clean before opening a pull request.

> **Note:** `pandas==3.1.0` ships without a `py.typed` marker, so the `pandas-stubs` package (installed with the `dev` extra) is required for accurate type checking of pandas code.

## Running the pipeline

Full pipeline (initial load):

```bash
python -m src.pipeline
```

Or with custom config:

```bash
python -m src.pipeline --config configs/config.yaml
```

Incremental update:

```bash
python -m src.pipeline --incremental
```

Programmatic usage:

```python
from src.pipeline import ETLPipeline
from pathlib import Path

pipeline = ETLPipeline(Path("configs/config.yaml"))
pipeline.run_full_pipeline()
```

## Adding new transformations

1. Add DDL to `sql/03_ddl_marts.sql` (if new table)
2. Add transformation logic to `sql/05_transform_marts.sql`
3. Run pipeline to test

## Related

- [Setup](setup.md) for the local environment
- [Schema](schema.md) for the layer each script writes
