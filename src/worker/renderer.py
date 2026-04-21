"""
HTML email renderer using Jinja2.

Why Jinja2?
- Auto-escaping (autoescape=True) means every {{ variable }} is HTML-escaped
  automatically. Even if user_name contained '<script>alert(1)</script>',
  it would render as plain text — no XSS possible in the email.
- Templates live in /templates/, separate from code — easy to iterate on the
  design without touching Python logic.

The renderer receives the current summary and history, delegates to charts.py
for image generation, then passes all data to the Jinja2 template.
"""

from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from worker.charts import income_expense_chart, savings_rate_chart
from worker.models import SummaryMessage

# Templates directory is two levels up from this file (src/worker/ → project root)
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),  # auto-escape all .html templates
)


def _format_decimal(value: Decimal) -> str:
    """Format a Decimal as a human-readable number with 2 decimal places."""
    return f"{value:,.2f}"


def render(msg: SummaryMessage, history: list[SummaryMessage]) -> str:
    """
    Render the summary_email.html template with current data and historical charts.

    Args:
        msg: The current summary message (latest snapshot).
        history: All snapshots for this user+currency (including current), oldest first.
                 If len(history) < 2, charts are not shown.

    Returns:
        Fully rendered HTML string ready to send as email body.
    """
    charts_available = len(history) >= 2

    savings_chart_b64 = savings_rate_chart(history) if charts_available else None
    income_chart_b64 = income_expense_chart(history, msg.currency) if charts_available else None

    savings_rate_pct = round(float(msg.savings_rate) * 100, 1)

    template = _env.get_template("summary_email.html")
    return template.render(
        user_name=msg.user_name,
        currency=msg.currency,
        generated_at_formatted=msg.generated_at.strftime("%d %b %Y, %H:%M"),
        total_assets_value=_format_decimal(msg.total_assets_value),
        monthly_income=_format_decimal(msg.monthly_income),
        monthly_expenses=_format_decimal(msg.monthly_expenses),
        monthly_savings=_format_decimal(msg.monthly_savings),
        monthly_savings_raw=float(msg.monthly_savings),  # for sign check in template
        savings_rate_pct=savings_rate_pct,
        unpriced_assets_count=msg.unpriced_assets_count,
        charts_available=charts_available,
        savings_rate_chart=savings_chart_b64,
        income_expense_chart=income_chart_b64,
    )
