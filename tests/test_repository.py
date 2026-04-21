"""
Tests for repository.py (SQLite persistence layer).

Uses a temporary in-memory SQLite database per test — no files written to disk,
no teardown needed.
"""

import pytest
from decimal import Decimal
from uuid import UUID

from worker.models import SummaryMessage
from worker import repository

DB = ":memory:"

VALID_PAYLOAD = {
    "userId": "123e4567-e89b-12d3-a456-426614174000",
    "userEmail": "alice@example.com",
    "userName": "Alice Doe",
    "totalAssetsValue": "125000.00",
    "monthlyIncome": "8000.00",
    "monthlyExpenses": "5500.00",
    "monthlySavings": "2500.00",
    "savingsRate": "0.3125",
    "unpricedAssetsCount": 2,
    "currency": "AUD",
    "generatedAt": "2026-01-01T09:00:00Z",
}


def _make_msg(**overrides) -> SummaryMessage:
    return SummaryMessage.model_validate({**VALID_PAYLOAD, **overrides})


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    repository.init_db(db_path)
    return db_path


# ── init_db ───────────────────────────────────────────────────────────────────

def test_init_db_creates_table(db):
    import sqlite3
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='summary_history'"
        ).fetchall()
    assert len(rows) == 1


def test_init_db_is_idempotent(db):
    # Calling init_db twice must not raise
    repository.init_db(db)


# ── insert ────────────────────────────────────────────────────────────────────

def test_insert_stores_row(db):
    msg = _make_msg()
    repository.insert(msg, db)

    import sqlite3
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT * FROM summary_history").fetchall()
    assert len(rows) == 1


def test_insert_multiple_rows(db):
    repository.insert(_make_msg(generatedAt="2026-01-01T09:00:00Z"), db)
    repository.insert(_make_msg(generatedAt="2026-02-01T09:00:00Z"), db)

    import sqlite3
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM summary_history").fetchone()[0]
    assert count == 2


# ── get_history ───────────────────────────────────────────────────────────────

def test_get_history_returns_empty_when_no_data(db):
    result = repository.get_history(UUID(VALID_PAYLOAD["userId"]), "AUD", db)
    assert result == []


def test_get_history_returns_inserted_message(db):
    msg = _make_msg()
    repository.insert(msg, db)

    history = repository.get_history(msg.user_id, "AUD", db)
    assert len(history) == 1
    assert history[0].currency == "AUD"
    assert history[0].monthly_income == Decimal("8000.00")


def test_get_history_ordered_oldest_first(db):
    repository.insert(_make_msg(generatedAt="2026-03-01T09:00:00Z"), db)
    repository.insert(_make_msg(generatedAt="2026-01-01T09:00:00Z"), db)
    repository.insert(_make_msg(generatedAt="2026-02-01T09:00:00Z"), db)

    history = repository.get_history(UUID(VALID_PAYLOAD["userId"]), "AUD", db)
    dates = [h.generated_at.month for h in history]
    assert dates == [1, 2, 3]


def test_get_history_filters_by_currency(db):
    repository.insert(_make_msg(currency="AUD"), db)
    repository.insert(_make_msg(currency="USD"), db)

    aud_history = repository.get_history(UUID(VALID_PAYLOAD["userId"]), "AUD", db)
    usd_history = repository.get_history(UUID(VALID_PAYLOAD["userId"]), "USD", db)

    assert len(aud_history) == 1
    assert len(usd_history) == 1
    assert aud_history[0].currency == "AUD"
    assert usd_history[0].currency == "USD"


def test_get_history_filters_by_user_id(db):
    user_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    user_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    repository.insert(_make_msg(userId=user_a), db)
    repository.insert(_make_msg(userId=user_b), db)

    history_a = repository.get_history(UUID(user_a), "AUD", db)
    history_b = repository.get_history(UUID(user_b), "AUD", db)

    assert len(history_a) == 1
    assert len(history_b) == 1


def test_get_history_respects_limit(db):
    for i in range(14):  # 14 entries across two years
        year = 2025 + i // 12
        month = (i % 12) + 1
        repository.insert(_make_msg(generatedAt=f"{year}-{month:02d}-01T09:00:00Z"), db)

    history = repository.get_history(UUID(VALID_PAYLOAD["userId"]), "AUD", db, limit=12)
    assert len(history) == 12


def test_get_history_preserves_decimal_precision(db):
    msg = _make_msg(totalAssetsValue="99999.99", savingsRate="0.3125")
    repository.insert(msg, db)

    history = repository.get_history(msg.user_id, "AUD", db)
    assert history[0].total_assets_value == Decimal("99999.99")
    assert history[0].savings_rate == Decimal("0.3125")
