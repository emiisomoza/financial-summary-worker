"""
Pydantic model for the SummaryMessage published by the Java API.

This is the first and most critical security gate: every message from the queue
is validated here before any processing happens. Malformed messages are rejected
at this boundary rather than propagating through the system.

The Java API publishes camelCase JSON, so we use alias_generator to map
camelCase keys to snake_case Python attributes automatically.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel


class SummaryMessage(BaseModel):
    """
    Represents a financial summary snapshot published to `summary.notifications`.

    Field mapping (JSON → Python):
        userId             → user_id
        userEmail          → user_email
        userName           → user_name
        totalAssetsValue   → total_assets_value
        monthlyIncome      → monthly_income
        monthlyExpenses    → monthly_expenses
        monthlySavings     → monthly_savings
        savingsRate        → savings_rate  (0.0 to 1.0, e.g. 0.3125 = 31.25%)
        unpricedAssetsCount → unpriced_assets_count
        currency           → currency  (3-char ISO code, e.g. "AUD")
        generatedAt        → generated_at
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,  # also accept snake_case in tests
    )

    user_id: UUID
    user_email: EmailStr
    user_name: str = Field(min_length=1, max_length=200)
    total_assets_value: Decimal = Field(ge=0)
    monthly_income: Decimal = Field(ge=0)
    monthly_expenses: Decimal = Field(ge=0)
    monthly_savings: Decimal  # can be negative (spending more than earning)
    savings_rate: Decimal = Field(ge=-10, le=10)  # sanity bounds
    unpriced_assets_count: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    generated_at: datetime
