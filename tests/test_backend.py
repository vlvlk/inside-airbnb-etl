"""Tests for the dashboard's query backends.

The dialect adapter and the result normalizer are pure functions, so they are
tested directly. The demo layer itself is exercised against the committed
Parquet files: if it is present, every dashboard query must run on it and the
headline figures must match the ones documented in ``docs/methodology.md``.
Those tests skip when the layer has not been built, so a clone that has not run
``python -m scripts.build_demo_marts`` still passes the rest of the suite.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from src.config import AppConfig
from src.dashboard import backend as backend_module
from src.dashboard.backend import (
    DEMO_FILES,
    DEMO_SCHEMAS,
    BackendUnavailable,
    DuckDbBackend,
    normalize_frame,
    select_backend,
    to_duckdb_sql,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = PROJECT_ROOT / "data" / "demo"
QUERIES_DIR = PROJECT_ROOT / "sql" / "queries"

#: The figures documented in ``docs/methodology.md`` for the bundled snapshot.
DOCUMENTED_OCCUPANCY = 0.474
DOCUMENTED_REVENUE = 538_161_557


def _demo_available() -> bool:
    """Whether the committed demo layer is present and complete."""
    return DEMO_DIR.is_dir() and all(
        (DEMO_DIR / name).exists() for name in DEMO_FILES.values()
    )


requires_demo = pytest.mark.skipif(
    not _demo_available(),
    reason="demo layer not built; run python -m scripts.build_demo_marts",
)


# ---------------------------------------------------------------------------
# Dialect adapter
# ---------------------------------------------------------------------------


def test_to_duckdb_sql_rewrites_nulls_not_distinct() -> None:
    """``UNIQUE NULLS NOT DISTINCT`` has no DuckDB form and becomes ``UNIQUE``."""
    sql = "UNIQUE NULLS NOT DISTINCT (listing_id, year, month)"
    assert to_duckdb_sql(sql) == "UNIQUE (listing_id, year, month)"


def test_to_duckdb_sql_rewrites_bind_markers() -> None:
    """``:name`` becomes ``$name`` so DuckDB can bind it."""
    assert to_duckdb_sql("LIMIT :limit") == "LIMIT $limit"


def test_to_duckdb_sql_keeps_postgres_casts() -> None:
    """The ``::`` cast operator must survive: only single colons are markers.

    ``booked_nights::NUMERIC`` is the exact shape used throughout
    ``sql/05_transform_marts.sql``; rewriting it to ``$:NUMERIC`` would break
    every marts query.
    """
    sql = "SELECT booked_nights::NUMERIC / NULLIF(total_nights, 0) AS rate"
    assert to_duckdb_sql(sql) == sql


def test_to_duckdb_sql_handles_casts_and_markers_together() -> None:
    sql = "SELECT x::NUMERIC AS v FROM t WHERE id = :id LIMIT :limit"
    assert to_duckdb_sql(sql) == (
        "SELECT x::NUMERIC AS v FROM t WHERE id = $id LIMIT $limit"
    )


def test_to_duckdb_sql_is_case_insensitive_for_nulls_not_distinct() -> None:
    """The clause is matched case-insensitively; the replacement is ``UNIQUE``."""
    assert to_duckdb_sql("unique nulls not distinct (a)") == "UNIQUE (a)"
    assert to_duckdb_sql("Unique Nulls Not Distinct (a)") == "UNIQUE (a)"


# ---------------------------------------------------------------------------
# Result normalization
# ---------------------------------------------------------------------------


def test_normalize_frame_converts_decimal_columns_to_float() -> None:
    """PostgreSQL NUMERIC arrives as ``Decimal``; the dashboard needs floats."""
    df = pd.DataFrame({"rate": [Decimal("0.474")], "nights": [10]})
    result = normalize_frame(df)

    assert result["rate"].dtype == "float64"
    assert result["rate"].iloc[0] == pytest.approx(0.474)
    # Integer columns are left alone.
    assert result["nights"].dtype.kind in {"i", "u"}


def test_normalize_frame_keeps_mixed_columns_as_decimal_detected() -> None:
    """A column with any Decimal is converted whole, NULLs included."""
    df = pd.DataFrame({"rate": [Decimal("1.5"), None]})
    result = normalize_frame(df)

    assert result["rate"].dtype == "float64"
    assert pd.isna(result["rate"].iloc[1])


def test_normalize_frame_is_a_noop_for_plain_frames() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": ["x", "y"]})
    assert normalize_frame(df).equals(df)


def test_normalize_frame_handles_empty_frames() -> None:
    empty = pd.DataFrame()
    assert normalize_frame(empty).empty


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def test_select_backend_rejects_unknown_source() -> None:
    config = AppConfig("configs/config.yaml", dashboard={"source": "mysql"})
    with pytest.raises(BackendUnavailable, match="Unknown dashboard.source"):
        select_backend(config)


def test_select_backend_duckdb_requires_the_layer(tmp_path: Path) -> None:
    """An explicit ``duckdb`` never falls back: a missing layer is an error."""
    config = AppConfig(
        "configs/config.yaml",
        dashboard={"source": "duckdb", "demo_dir": str(tmp_path / "missing")},
    )
    with pytest.raises(BackendUnavailable, match="demo layer not found"):
        select_backend(config)


def test_select_backend_auto_falls_back_to_duckdb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``auto`` prefers PostgreSQL but survives it being unreachable.

    This is the behaviour that makes a fresh clone work without Docker, so it is
    worth pinning: a Postgres failure must not propagate.
    """
    config = AppConfig("configs/config.yaml", dashboard={"source": "auto"})

    def unavailable(_config: AppConfig) -> object:
        raise BackendUnavailable("connection refused")

    sentinel = object()
    monkeypatch.setattr(backend_module, "make_postgres_backend", unavailable)
    monkeypatch.setattr(backend_module, "make_duckdb_backend", lambda _config: sentinel)

    assert select_backend(config) is sentinel


def test_select_backend_postgres_does_not_fall_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ``postgres`` surfaces the error instead of hiding it."""

    def unavailable(_config: AppConfig) -> object:
        raise BackendUnavailable("connection refused")

    monkeypatch.setattr(backend_module, "make_postgres_backend", unavailable)
    config = AppConfig("configs/config.yaml", dashboard={"source": "postgres"})

    with pytest.raises(BackendUnavailable):
        select_backend(config)


# ---------------------------------------------------------------------------
# Demo layer
# ---------------------------------------------------------------------------


@requires_demo
def test_demo_layer_exposes_every_schema_and_table() -> None:
    backend = DuckDbBackend(DEMO_DIR)
    try:
        for qualified_name in DEMO_FILES:
            schema, table = qualified_name.split(".")
            assert schema in DEMO_SCHEMAS
            # A view that cannot be queried would raise here.
            backend.execute(f"SELECT * FROM {qualified_name} LIMIT 1")
    finally:
        backend.close()


@requires_demo
def test_demo_layer_answers_every_dashboard_query() -> None:
    """Every ``sql/queries/*.sql`` file must run on the demo layer.

    This is the contract that keeps the demo honest: the layer is only useful if
    it answers the same questions PostgreSQL does, so the test walks the whole
    query directory rather than a hand-picked subset.
    """
    backend = DuckDbBackend(DEMO_DIR)
    try:
        for path in sorted(QUERIES_DIR.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            params = {"limit": 20} if ":limit" in sql else None
            result = backend.execute(sql, params)
            assert isinstance(result, pd.DataFrame), path.name
            assert not result.empty, f"{path.name} returned no rows"
    finally:
        backend.close()


def test_every_demo_file_has_an_export_projection() -> None:
    """The build script must know how to export every table the backend reads.

    :data:`DEMO_FILES` (what the backend reads) and ``DEMO_EXPORTS`` (what the
    build script writes) are two halves of one contract. A table added to the
    first without the second would build a layer with a missing file, so the two
    are compared here rather than discovered at runtime.
    """
    from scripts.build_demo_marts import DEMO_EXPORTS

    assert set(DEMO_EXPORTS) == set(DEMO_FILES)


@requires_demo
def test_demo_layer_reproduces_documented_figures() -> None:
    """The demo layer must land on the numbers in ``docs/methodology.md``.

    Occupancy and revenue are the two headline figures the README quotes, so a
    drift here means the demo no longer represents the pipeline's output.
    """
    backend = DuckDbBackend(DEMO_DIR)
    try:
        kpis = backend.execute((QUERIES_DIR / "overall_kpis.sql").read_text())
    finally:
        backend.close()

    yearly = kpis[kpis["granularity"] == "year"]
    occupancy = yearly["booked_nights"].sum() / yearly["total_nights"].sum()
    revenue = yearly["total_revenue"].sum()

    assert round(occupancy, 3) == DOCUMENTED_OCCUPANCY
    assert round(revenue) == DOCUMENTED_REVENUE


@requires_demo
def test_demo_layer_returns_floats_not_decimals() -> None:
    """The backend normalizes NUMERIC columns, so the pages get plain floats.

    ``Decimal('NaN')`` is not recognised by ``pandas.isna``, which the pages rely
    on for their empty states; a Decimal leaking through would silently break
    them.
    """
    backend = DuckDbBackend(DEMO_DIR)
    try:
        frame = backend.execute((QUERIES_DIR / "seasonality.sql").read_text())
    finally:
        backend.close()

    assert frame["occupancy_rate"].dtype == "float64"
    assert not any(isinstance(v, Decimal) for v in frame["avg_price_per_night"])


@requires_demo
def test_demo_layer_supports_bind_parameters() -> None:
    """``:limit`` must survive the translation and actually bound the result."""
    backend = DuckDbBackend(DEMO_DIR)
    try:
        sql = (QUERIES_DIR / "top_listings_by_revpar.sql").read_text()
        result = backend.execute(sql, {"limit": 5})
    finally:
        backend.close()

    assert len(result) == 5
