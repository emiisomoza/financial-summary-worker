"""
Chart generation using matplotlib.

Why embed charts as base64 in the email instead of hosting them?
- No external URL needed — the image is self-contained in the email
- Works offline, behind firewalls, and in email clients that block external images
- No expiry risk (external image links can die)

The trade-off: larger email size. For 2 charts at ~30KB each, this adds ~60KB
to the email — acceptable for a financial summary.

Charts are only generated when history has >= 2 entries for the same currency.
With 1 or 0 entries, we return None and the template shows a placeholder message.
"""

import base64
import io
from decimal import Decimal

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from worker.models import SummaryMessage

# Use non-interactive backend (no display needed — we render to bytes)
matplotlib.use("Agg")

_BRAND_COLOR = "#2563EB"   # blue
_INCOME_COLOR = "#16A34A"  # green
_EXPENSE_COLOR = "#DC2626"  # red
_GRID_COLOR = "#E5E7EB"


def _fig_to_base64(fig: plt.Figure) -> str:
    """Render a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="white")
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return encoded


def _date_labels(history: list[SummaryMessage]) -> list[str]:
    return [msg.generated_at.strftime("%d %b") for msg in history]


def savings_rate_chart(history: list[SummaryMessage]) -> str | None:
    """
    Line chart: savings rate (%) over time.
    Returns base64 PNG or None if fewer than 2 data points.
    """
    if len(history) < 2:
        return None

    labels = _date_labels(history)
    rates = [float(msg.savings_rate) * 100 for msg in history]  # convert to %

    fig, ax = plt.subplots(figsize=(7, 3))
    ax.plot(labels, rates, color=_BRAND_COLOR, linewidth=2, marker="o", markersize=5)
    ax.fill_between(labels, rates, alpha=0.08, color=_BRAND_COLOR)
    ax.set_title("Savings Rate Trend", fontsize=13, fontweight="bold", pad=10)
    ax.set_ylabel("Savings Rate (%)", fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    ax.set_facecolor("white")
    ax.grid(axis="y", color=_GRID_COLOR, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()

    return _fig_to_base64(fig)


def income_expense_chart(history: list[SummaryMessage], currency: str) -> str | None:
    """
    Grouped bar chart: monthly income vs. monthly expenses over time.
    Returns base64 PNG or None if fewer than 2 data points.
    """
    if len(history) < 2:
        return None

    labels = _date_labels(history)
    incomes = [float(msg.monthly_income) for msg in history]
    expenses = [float(msg.monthly_expenses) for msg in history]

    x = range(len(labels))
    bar_width = 0.35

    fig, ax = plt.subplots(figsize=(7, 3))
    ax.bar([i - bar_width / 2 for i in x], incomes, bar_width,
           label="Income", color=_INCOME_COLOR, alpha=0.85)
    ax.bar([i + bar_width / 2 for i in x], expenses, bar_width,
           label="Expenses", color=_EXPENSE_COLOR, alpha=0.85)

    ax.set_title("Monthly Income vs Expenses", fontsize=13, fontweight="bold", pad=10)
    ax.set_ylabel(f"Amount ({currency})", fontsize=10)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.legend(fontsize=9)
    ax.set_facecolor("white")
    ax.grid(axis="y", color=_GRID_COLOR, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()

    return _fig_to_base64(fig)
