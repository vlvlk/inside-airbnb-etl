"""Tests for the dashboard's pure data helpers.

These cover the granularity logic that maps the marts' NULL-encoded period
columns onto a single ``granularity`` label, plus the SQL query loader. They do
not touch the database: :func:`run_query` is exercised against a temporary SQL
file to verify the file lookup and bind-parameter plumbing.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest

from src.dashboard import data, ui


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


def test_add_period_handles_nullable_float_columns() -> None:
    """SQL returns NULLs as float64, so the period columns may hold NaN.

    The frame mixes a monthly row, a weekly row and a quarterly row, which is
    exactly the shape of the marts tables.
    """
    df = pd.DataFrame(
        {
            "year": [2026.0, 2026.0, 2026.0],
            "month": [9.0, float("nan"), float("nan")],
            "week_of_year": [float("nan"), 36.0, float("nan")],
            "quarter": [3.0, 3.0, 3.0],
        }
    )
    periods = data.add_period(df)["period"].tolist()
    assert periods[0] == pd.Timestamp("2026-09-01")
    assert periods[1] == pd.Timestamp("2026-08-31")  # Monday of ISO week 36
    assert pd.isna(periods[2])


def test_add_period_ignores_extra_columns() -> None:
    """Only year/month/day may reach ``to_datetime``; other columns are fine."""
    df = pd.DataFrame(
        {"year": [2026], "month": [9], "occupancy_rate": [0.5], "listing_id": [1]}
    )
    period = data.add_period(df)["period"].iloc[0]
    assert period == pd.Timestamp("2026-09-01")


def test_seasonality_chart_labels_months() -> None:
    """Month numbers are rendered as short English names on the x axis."""
    df = pd.DataFrame(
        {
            "month": [1.0, 6.0, 12.0],
            "occupancy_rate": [0.4, 0.7, 0.9],
            "booked_nights": [10, 20, 30],
        }
    )
    chart = ui.seasonality_chart(df, alt_text="Occupancy by month").to_dict()
    values = next(iter(chart["datasets"].values()))
    assert [row["month_name"] for row in values] == ["Jan", "Jun", "Dec"]


def test_seasonality_chart_keeps_null_month_missing() -> None:
    """A NULL month stays missing instead of raising while casting."""
    df = pd.DataFrame(
        {
            "month": [1.0, None],
            "occupancy_rate": [0.4, 0.5],
            "booked_nights": [10, 5],
        }
    )
    chart = ui.seasonality_chart(df, alt_text="Occupancy by month").to_dict()
    values = next(iter(chart["datasets"].values()))
    assert values[0]["month_name"] == "Jan"
    assert values[1]["month_name"] is None


def test_filter_granularity_avoids_double_counting() -> None:
    """Summing one granularity must not triple-count the same nights.

    ``overall_kpis`` returns weekly, monthly, quarterly and yearly rows together.
    Filtering to a single level is what keeps a KPI sum equal to the true total
    instead of counting every night three or four times.
    """
    df = pd.DataFrame(
        {
            "year": [2026, 2026, 2026],
            "month": [None, None, None],
            "week_of_year": [None, None, None],
            "quarter": [None, 3, 3],
            "total_nights": [100, 100, 100],
        }
    )
    yearly = data.filter_granularity(df, "year")
    assert int(yearly["total_nights"].sum()) == 100
    assert int(df["total_nights"].sum()) == 300  # the bug this guards against


def test_available_years_union_and_sorted() -> None:
    a = pd.DataFrame({"year": [2027, 2026]})
    b = pd.DataFrame({"year": [2026, 2028]})
    assert data.available_years(a, b) == [2026, 2027, 2028]


def test_available_years_skips_empty() -> None:
    assert data.available_years(pd.DataFrame()) == []


def test_run_query_reads_file_and_delegates_to_backend(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run_query`` loads the named SQL file and hands it to the backend.

    The backend is the only thing that varies between PostgreSQL and DuckDB, so
    this test pins the contract: the file is read, the SQL text and the bind
    parameters both reach the backend, and the returned frame is passed through.
    """
    (tmp_path / "probe.sql").write_text("SELECT :value AS value", encoding="utf-8")
    monkeypatch.setattr(data, "QUERIES_DIR", tmp_path)

    captured: dict[str, object] = {}

    class _Backend:
        def execute(
            self, sql: str, params: dict[str, object] | None = None
        ) -> pd.DataFrame:
            captured["sql"] = sql
            captured["params"] = params
            return pd.DataFrame({"value": [42]})

    monkeypatch.setattr(data, "get_backend", lambda: _Backend())

    result = data.run_query("probe", {"value": 42})

    assert result.iloc[0]["value"] == 42
    assert captured["params"] == {"value": 42}
    assert "SELECT" in str(captured["sql"])


def test_run_query_returns_empty_frame_without_a_backend(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No backend is an empty frame, not an exception.

    The pages already render a "run the pipeline first" warning for empty
    loaders, which is the right message when neither engine is available. A
    raised error would replace that guidance with a traceback.
    """
    (tmp_path / "probe.sql").write_text("SELECT 1", encoding="utf-8")
    monkeypatch.setattr(data, "QUERIES_DIR", tmp_path)
    monkeypatch.setattr(data, "get_backend", lambda: None)

    result = data.run_query("probe")

    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_stringify_ids_casts_identifier_columns_to_text() -> None:
    """``listing_id``/``host_id`` become text so the frontend keeps every digit.

    The values exceed JavaScript's ``Number.MAX_SAFE_INTEGER`` (2**53 - 1), which
    Streamlit otherwise renders as an error cell with inconsistent alignment.
    """
    df = pd.DataFrame(
        {
            "listing_id": [40835718, 999980707820268957],
            "host_id": [123, 456],
            "occupancy_rate": [0.4, 0.5],
        }
    )
    result = ui.stringify_ids(df)

    assert result["listing_id"].tolist() == ["40835718", "999980707820268957"]
    assert result["host_id"].tolist() == ["123", "456"]
    # Non-identifier columns are untouched.
    assert result["occupancy_rate"].tolist() == [0.4, 0.5]
    # The original frame is not mutated in place.
    assert df["listing_id"].dtype.kind in {"i", "u"}


def test_stringify_ids_is_a_noop_without_identifier_columns() -> None:
    df = pd.DataFrame({"neighbourhood": ["A"], "occupancy_rate": [0.4]})
    result = ui.stringify_ids(df)
    assert result.equals(df)


def test_format_money_md_escapes_the_dollar_sign() -> None:
    """Money shown through ``st.markdown`` must not open a KaTeX expression.

    A *pair* of unescaped ``$`` signs makes Streamlit parse everything between
    them as LaTeX, which drops the spaces (``a night against`` becomes
    ``anightagainst``) and turns ``;`` into a thin space. The Markdown variant
    escapes the currency symbol so the surrounding prose survives.
    """
    assert ui.format_money(1234) == "$1,234"
    assert ui.format_money_md(1234) == r"\$1,234"
    # Every '$' is escaped, so no bare '$' is left to open a math expression.
    assert re.search(r"(?<!\\)\$", ui.format_money_md(1234)) is None


def test_format_money_md_handles_missing_values() -> None:
    """``n/a`` carries no ``$``, so escaping leaves it untouched."""
    assert ui.format_money_md(None) == "n/a"
    assert ui.format_money_md(float("nan")) == "n/a"


def test_escape_dollars_leaves_no_bare_dollar() -> None:
    """Dynamic text (a database error, say) is escaped before it hits Markdown."""
    assert ui.escape_dollars("bind marker $name") == r"bind marker \$name"
    assert ui.escape_dollars("no currency here") == "no currency here"
    assert re.search(r"(?<!\\)\$", ui.escape_dollars("a $ b $ c")) is None


#: Streamlit commands that render their argument as Markdown, and therefore
#: parse a ``$...$`` pair as an inline LaTeX expression.
_MARKDOWN_COMMANDS = frozenset(
    {"markdown", "caption", "write", "info", "warning", "success", "error"}
)


def test_no_markdown_command_receives_unescaped_format_money() -> None:
    """Guard the regression: money in a Markdown context must be escaped.

    ``st.markdown`` and friends run their input through KaTeX, so two unescaped
    ``$`` signs turn the prose between them into a formula — spaces are dropped
    and ``;`` becomes a thin space. Every dashboard page is parsed here and any
    ``ui.format_money(...)`` passed to a Markdown-rendering command is reported,
    because that context has to use ``ui.format_money_md`` instead. Widgets that
    do not parse Markdown (``st.metric``, ``st.column_config``, Altair titles)
    keep the plain variant.
    """
    dashboard_dir = Path(ui.__file__).parent
    offenders: list[str] = []

    for path in sorted(dashboard_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_markdown_command = (
                isinstance(func, ast.Attribute)
                and func.attr in _MARKDOWN_COMMANDS
                and isinstance(func.value, ast.Name)
                and func.value.id == "st"
            )
            if not is_markdown_command:
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Attribute) and inner.attr == "format_money":
                    offenders.append(
                        f"{path.relative_to(dashboard_dir.parent.parent)}:{inner.lineno}"
                    )

    assert offenders == [], (
        "ui.format_money() reaches a Markdown-rendering command; use "
        f"ui.format_money_md() instead: {offenders}"
    )


def test_occupancy_column_config_types_ids_as_text() -> None:
    """The shared config renders ids as text, not as numbers.

    ``st.column_config.TextColumn`` returns a plain config dict, so the column
    type is read from its ``type_config`` entry. The return type of
    ``occupancy_column_config`` is a wide union of column-config TypedDicts, so
    the frame is narrowed to a plain mapping before indexing into it.
    """
    config = cast("dict[str, Any]", ui.occupancy_column_config())
    assert config["listing_id"]["type_config"]["type"] == "text"
    assert config["host_id"]["type_config"]["type"] == "text"
    # Guard the regression: a number column would re-introduce the 2**53 error.
    assert config["occupancy_rate"]["type_config"]["type"] == "number"


def test_grouped_bar_chart_encodes_category_and_group() -> None:
    """The host-segment chart groups bars by year and pins the segment order."""
    df = pd.DataFrame(
        {
            "host_segment": ["Single listing", "Professional (5+ listings)"],
            "year": [2026, 2026],
            "occupancy_rate": [0.5, 0.43],
        }
    )
    chart = ui.grouped_bar_chart(
        df,
        category_col="host_segment",
        value_col="occupancy_rate",
        group_col="year",
        category_order=ui.HOST_SEGMENT_ORDER,
    ).to_dict()

    encoding = chart["encoding"]
    assert encoding["x"]["field"] == "host_segment"
    assert encoding["x"]["sort"] == list(ui.HOST_SEGMENT_ORDER)
    assert encoding["xOffset"]["field"] == "year"
    assert encoding["y"]["field"] == "occupancy_rate"


def test_load_host_segmentation_delegates_to_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run_query(name: str, params: object = None) -> pd.DataFrame:
        captured["name"] = name
        return pd.DataFrame({"host_segment": ["Single listing"]})

    monkeypatch.setattr(data, "run_query", fake_run_query)
    result = data.load_host_segmentation()

    assert captured["name"] == "host_segmentation"
    assert result.iloc[0]["host_segment"] == "Single listing"


def test_load_data_quality_delegates_to_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run_query(name: str, params: object = None) -> pd.DataFrame:
        captured["name"] = name
        return pd.DataFrame({"check_name": ["Listings in raw layer"], "value": [22050]})

    monkeypatch.setattr(data, "run_query", fake_run_query)
    result = data.load_data_quality()

    assert captured["name"] == "data_quality"
    assert int(result.iloc[0]["value"]) == 22050
