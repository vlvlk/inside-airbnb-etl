"""Tests for the dashboard's pure data helpers.

These cover the granularity logic that maps the marts' NULL-encoded period
columns onto a single ``granularity`` label, plus the SQL query loader. They do
not touch the database: :func:`run_query` is exercised against a temporary SQL
file to verify the file lookup and bind-parameter plumbing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard import data


def _frame() -> pd.DataFrame:
    """A frame with one row per granularity, mirroring the marts shape."""
    return pd.DataFrame(
        {
            "year": [2026, 2026, 2026, 2026],
            "month": [9, None, None, None],
            "week_of_year": [None, 36, None, None],
            "quarter": [3, 3, 3, None],
            "value": [1, 2, 3, 4],
        }
    )


def test_add_granularity_labels_every_level() -> None:
    labelled = data.add_granularity(_frame())
    assert labelled["granularity"].tolist() == ["month", "week", "quarter", "year"]


def test_add_granularity_without_week_column() -> None:
    """Frames lacking ``week_of_year`` (e.g. revenue) still classify correctly."""
    df = pd.DataFrame(
        {
            "year": [2026, 2026, 2026],
            "month": [9, None, None],
            "quarter": [3, 3, None],
        }
    )
    labelled = data.add_granularity(df)
    assert labelled["granularity"].tolist() == ["month", "quarter", "year"]


def test_add_granularity_empty_frame() -> None:
    empty = pd.DataFrame({"year": [], "month": [], "quarter": []})
    result = data.add_granularity(empty)
    assert result.empty
    assert "granularity" in result.columns


def test_filter_granularity_keeps_one_level() -> None:
    labelled = data.add_granularity(_frame())
    months = data.filter_granularity(labelled, "month")
    assert len(months) == 1
    assert months.iloc[0]["value"] == 1


def test_filter_granularity_adds_label_if_missing() -> None:
    """An unlabelled frame is labelled on the fly before filtering."""
    quarters = data.filter_granularity(_frame(), "quarter")
    assert len(quarters) == 1
    assert quarters.iloc[0]["value"] == 3


def test_add_period_monthly() -> None:
    df = pd.DataFrame({"year": [2026], "month": [9], "quarter": [3]})
    period = data.add_period(df)["period"].iloc[0]
    assert period == pd.Timestamp("2026-09-01")


def test_add_period_weekly_uses_iso_week() -> None:
    df = pd.DataFrame(
        {"year": [2026], "month": [None], "week_of_year": [36], "quarter": [3]}
    )
    period = data.add_period(df)["period"].iloc[0]
    assert period == pd.Timestamp("2026-08-31")  # Monday of ISO week 36


def test_available_years_union_and_sorted() -> None:
    a = pd.DataFrame({"year": [2027, 2026]})
    b = pd.DataFrame({"year": [2026, 2028]})
    assert data.available_years(a, b) == [2026, 2027, 2028]


def test_available_years_skips_empty() -> None:
    assert data.available_years(pd.DataFrame()) == []


def test_run_query_reads_file_and_binds_params(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run_query`` loads the named SQL file and forwards bind parameters."""
    (tmp_path / "probe.sql").write_text("SELECT :value AS value", encoding="utf-8")
    monkeypatch.setattr(data, "QUERIES_DIR", tmp_path)

    class _Conn:
        def __enter__(self) -> "_Conn":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    class _Engine:
        def connect(self) -> _Conn:
            return _Conn()

    captured: dict[str, object] = {}

    def fake_read_sql(sql: object, conn: object, params: object) -> pd.DataFrame:
        captured["sql"] = str(sql)
        captured["params"] = params
        return pd.DataFrame({"value": [42]})

    monkeypatch.setattr(data, "get_engine", lambda: _Engine())
    monkeypatch.setattr(data.pd, "read_sql", fake_read_sql)

    result = data.run_query("probe", {"value": 42})

    assert result.iloc[0]["value"] == 42
    assert captured["params"] == {"value": 42}
    assert "SELECT" in str(captured["sql"])
