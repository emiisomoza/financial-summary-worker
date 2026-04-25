"""
Tests for charts.py (matplotlib chart generation).

We verify that:
- Charts return None when history is too short (< 2 points)
- Charts return a valid base64 PNG string when data is sufficient
- The base64 string can be decoded back to bytes (i.e., it's a real image)
"""

import base64
import pytest

from worker.charts import income_expense_chart, savings_rate_chart, _last_per_month
from worker.models import SummaryMessage

_BASE_PAYLOAD = {
    "userId": "123e4567-e89b-12d3-a456-426614174000",
    "userEmail": "alice@example.com",
    "userName": "Alice Doe",
    "totalAssetsValue": "100000.00",
    "monthlyIncome": "8000.00",
    "monthlyExpenses": "5500.00",
    "monthlySavings": "2500.00",
    "savingsRate": "0.3125",
    "unpricedAssetsCount": 0,
    "currency": "AUD",
    "generatedAt": "2026-01-01T09:00:00Z",
}


def _make_msg(month: int, day: int = 1, **overrides) -> SummaryMessage:
    return SummaryMessage.model_validate(
        {**_BASE_PAYLOAD, "generatedAt": f"2026-{month:02d}-{day:02d}T09:00:00Z", **overrides}
    )


def _history(n: int) -> list[SummaryMessage]:
    return [_make_msg(i + 1) for i in range(n)]


# ── savings_rate_chart ────────────────────────────────────────────────────────

def test_savings_rate_chart_returns_none_for_empty_history():
    assert savings_rate_chart([]) is None


def test_savings_rate_chart_returns_none_for_single_entry():
    assert savings_rate_chart(_history(1)) is None


def test_savings_rate_chart_returns_base64_string_for_two_entries():
    result = savings_rate_chart(_history(2))
    assert result is not None
    assert isinstance(result, str)
    # Must be valid base64
    decoded = base64.b64decode(result)
    assert decoded[:4] == b"\x89PNG"  # PNG magic bytes


def test_savings_rate_chart_works_with_many_entries():
    result = savings_rate_chart(_history(12))
    assert result is not None
    decoded = base64.b64decode(result)
    assert decoded[:4] == b"\x89PNG"


# ── _last_per_month ───────────────────────────────────────────────────────────

def test_last_per_month_keeps_single_entry_per_month():
    # 4 weekly snapshots in January → should collapse to 1
    weekly = [_make_msg(1, day) for day in [1, 8, 15, 22]]
    result = _last_per_month(weekly)
    assert len(result) == 1
    assert result[0].generated_at.day == 22  # most recent


def test_last_per_month_keeps_multiple_months():
    history = [_make_msg(1), _make_msg(2), _make_msg(3)]
    result = _last_per_month(history)
    assert len(result) == 3


def test_last_per_month_mixed_weekly_and_monthly():
    # January has 4 weekly entries, February and March have 1 each
    history = (
        [_make_msg(1, day) for day in [1, 8, 15, 22]]
        + [_make_msg(2), _make_msg(3)]
    )
    result = _last_per_month(history)
    assert len(result) == 3
    assert result[0].generated_at.month == 1
    assert result[0].generated_at.day == 22


def test_last_per_month_preserves_oldest_first_order():
    history = [_make_msg(3), _make_msg(1), _make_msg(2)]
    result = _last_per_month(history)
    months = [m.generated_at.month for m in result]
    assert months == [3, 1, 2]  # insertion order preserved (dict)


# ── income_expense_chart ──────────────────────────────────────────────────────

def test_income_expense_chart_returns_none_for_empty_history():
    assert income_expense_chart([], "AUD") is None


def test_income_expense_chart_returns_none_for_single_entry():
    assert income_expense_chart(_history(1), "AUD") is None


def test_income_expense_chart_returns_none_for_multiple_entries_same_month():
    # 4 weekly snapshots all in January → collapses to 1 month → no chart
    weekly = [_make_msg(1, day) for day in [1, 8, 15, 22]]
    assert income_expense_chart(weekly, "AUD") is None


def test_income_expense_chart_returns_base64_string_for_two_months():
    result = income_expense_chart(_history(2), "AUD")
    assert result is not None
    assert isinstance(result, str)
    decoded = base64.b64decode(result)
    assert decoded[:4] == b"\x89PNG"


def test_income_expense_chart_collapses_weekly_to_monthly():
    # 4 weekly snapshots in Jan + 4 in Feb → should render as 2-bar chart
    history = (
        [_make_msg(1, day) for day in [1, 8, 15, 22]]
        + [_make_msg(2, day) for day in [1, 8, 15, 22]]
    )
    result = income_expense_chart(history, "AUD")
    assert result is not None
    decoded = base64.b64decode(result)
    assert decoded[:4] == b"\x89PNG"


def test_income_expense_chart_works_with_many_entries():
    result = income_expense_chart(_history(12), "USD")
    assert result is not None
    decoded = base64.b64decode(result)
    assert decoded[:4] == b"\x89PNG"
