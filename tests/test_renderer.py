"""
Tests for renderer.py (Jinja2 HTML email rendering).

Covers:
- Basic rendering (key values appear in output)
- Chart placeholder shown when history < 2
- Charts embedded when history >= 2
- XSS: user-controlled fields are HTML-escaped (Jinja2 autoescape)
- Unpriced assets warning appears/disappears correctly
- Negative savings rate applies 'negative' CSS class
"""

import pytest

from worker.models import SummaryMessage
from worker import renderer

_BASE_PAYLOAD = {
    "userId": "123e4567-e89b-12d3-a456-426614174000",
    "userEmail": "alice@example.com",
    "userName": "Alice Doe",
    "totalAssetsValue": "125000.00",
    "monthlyIncome": "8000.00",
    "monthlyExpenses": "5500.00",
    "monthlySavings": "2500.00",
    "savingsRate": "0.3125",
    "unpricedAssetsCount": 0,
    "currency": "AUD",
    "generatedAt": "2026-04-01T09:00:00Z",
}


def _make_msg(**overrides) -> SummaryMessage:
    return SummaryMessage.model_validate({**_BASE_PAYLOAD, **overrides})


def _history(n: int) -> list[SummaryMessage]:
    msgs = []
    for i in range(n):
        msgs.append(_make_msg(generatedAt=f"2026-{i + 1:02d}-01T09:00:00Z"))
    return msgs


# ── basic rendering ───────────────────────────────────────────────────────────

def test_render_contains_user_name():
    msg = _make_msg()
    html = renderer.render(msg, [msg])
    assert "Alice Doe" in html


def test_render_contains_currency():
    msg = _make_msg()
    html = renderer.render(msg, [msg])
    assert "AUD" in html


def test_render_contains_total_assets():
    msg = _make_msg()
    html = renderer.render(msg, [msg])
    assert "125,000.00" in html


def test_render_contains_monthly_income():
    msg = _make_msg()
    html = renderer.render(msg, [msg])
    assert "8,000.00" in html


def test_render_contains_savings_rate_percent():
    msg = _make_msg()
    html = renderer.render(msg, [msg])
    assert "31.2%" in html


# ── chart placeholder / embedded charts ───────────────────────────────────────

def test_render_shows_placeholder_with_no_history():
    msg = _make_msg()
    html = renderer.render(msg, [])
    assert "Charts will appear once" in html


def test_render_shows_placeholder_with_single_history_entry():
    msg = _make_msg()
    html = renderer.render(msg, [msg])
    assert "Charts will appear once" in html


def test_render_embeds_charts_with_two_history_entries():
    history = _history(2)
    msg = history[-1]
    html = renderer.render(msg, history)
    assert "data:image/png;base64," in html
    # The placeholder message (not the CSS class) must be absent
    assert "Charts will appear once" not in html


def test_render_embeds_both_charts_with_sufficient_history():
    history = _history(6)
    msg = history[-1]
    html = renderer.render(msg, history)
    # Both charts should be embedded — expect two base64 image tags
    assert html.count("data:image/png;base64,") == 2


# ── unpriced assets warning ───────────────────────────────────────────────────

def test_render_no_warning_when_unpriced_assets_zero():
    msg = _make_msg(unpricedAssetsCount=0)
    html = renderer.render(msg, [msg])
    assert "could not be priced" not in html


def test_render_warning_when_unpriced_assets_present():
    msg = _make_msg(unpricedAssetsCount=3)
    html = renderer.render(msg, [msg])
    assert "could not be priced" in html
    assert "3 assets" in html


def test_render_singular_warning_for_one_unpriced_asset():
    msg = _make_msg(unpricedAssetsCount=1)
    html = renderer.render(msg, [msg])
    assert "1 asset" in html
    assert "is excluded" in html


# ── negative savings ──────────────────────────────────────────────────────────

def test_render_negative_savings_applies_negative_class():
    msg = _make_msg(monthlySavings="-500.00", savingsRate="-0.0625")
    html = renderer.render(msg, [msg])
    # Monthly savings value block should have class="kpi-value negative"
    assert "negative" in html


# ── XSS escaping ──────────────────────────────────────────────────────────────

def test_render_escapes_xss_in_user_name():
    msg = _make_msg(userName="<script>alert(1)</script>")
    html = renderer.render(msg, [msg])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_escapes_xss_in_currency():
    msg = _make_msg(currency="<b>")  # 3 chars, passes validation
    html = renderer.render(msg, [msg])
    assert "<b>" not in html
    assert "&lt;b&gt;" in html
