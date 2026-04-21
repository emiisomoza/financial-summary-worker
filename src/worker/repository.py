"""
SQLite repository for storing summary history.

Why SQLite?
- Zero infrastructure: no separate DB container needed
- Standard library: `sqlite3` is built into Python, no extra dependency
- Persistent across restarts via Docker volume mount
- Sufficient for the read pattern: we query the last 12 rows per user per currency

The database file path is configured via DB_PATH env var (default: ./data/summaries.db).
In Docker, this path is a mounted volume so data survives container restarts.

Key design: history is always queried filtered by (user_id, currency).
If the user changes currency, the new currency starts fresh — we never mix
different currencies in the same chart.
"""

import sqlite3
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from worker.models import SummaryMessage


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # allows column access by name
    return conn


def init_db(db_path: str) -> None:
    """
    Create the summary_history table if it doesn't exist.
    Called once at startup before the consumer starts.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summary_history (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          TEXT    NOT NULL,
                user_email       TEXT    NOT NULL,
                user_name        TEXT    NOT NULL,
                currency         TEXT    NOT NULL,
                total_assets     TEXT    NOT NULL,
                monthly_income   TEXT    NOT NULL,
                monthly_expenses TEXT    NOT NULL,
                monthly_savings  TEXT    NOT NULL,
                savings_rate     TEXT    NOT NULL,
                generated_at     TEXT    NOT NULL
            )
        """)
        # Index makes the history query fast even with many rows
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_currency
            ON summary_history (user_id, currency, generated_at)
        """)


def insert(msg: SummaryMessage, db_path: str) -> None:
    """Persist a summary snapshot. Called before email generation."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO summary_history
                (user_id, user_email, user_name, currency,
                 total_assets, monthly_income, monthly_expenses,
                 monthly_savings, savings_rate, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(msg.user_id),
                str(msg.user_email),
                msg.user_name,
                msg.currency,
                str(msg.total_assets_value),
                str(msg.monthly_income),
                str(msg.monthly_expenses),
                str(msg.monthly_savings),
                str(msg.savings_rate),
                msg.generated_at.isoformat(),
            ),
        )


def get_history(user_id: UUID, currency: str, db_path: str, limit: int = 12) -> list[SummaryMessage]:
    """
    Return the last `limit` snapshots for a user in a specific currency,
    ordered oldest-first (for chart rendering, left = older, right = newer).

    Filtering by currency is intentional: if the user switches from AUD to USD,
    the new currency starts fresh rather than mixing incomparable values in the chart.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT user_id, user_email, user_name, currency,
                   total_assets, monthly_income, monthly_expenses,
                   monthly_savings, savings_rate, generated_at
            FROM summary_history
            WHERE user_id = ? AND currency = ?
            ORDER BY generated_at DESC
            LIMIT ?
            """,
            (str(user_id), currency, limit),
        ).fetchall()

    # Reverse so oldest entry is first (left side of chart)
    return [_row_to_message(row) for row in reversed(rows)]


def _row_to_message(row: sqlite3.Row) -> SummaryMessage:
    return SummaryMessage.model_validate(
        {
            "userId": row["user_id"],
            "userEmail": row["user_email"],
            "userName": row["user_name"],
            "currency": row["currency"],
            "totalAssetsValue": Decimal(row["total_assets"]),
            "monthlyIncome": Decimal(row["monthly_income"]),
            "monthlyExpenses": Decimal(row["monthly_expenses"]),
            "monthlySavings": Decimal(row["monthly_savings"]),
            "savingsRate": Decimal(row["savings_rate"]),
            "unpricedAssetsCount": 0,  # not stored, not needed for charts
            "generatedAt": row["generated_at"],
        }
    )
