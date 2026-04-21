"""
Tests for SummaryMessage Pydantic model.

These verify the security gate: valid messages are accepted, invalid ones
raise ValidationError before any processing happens.
"""

import pytest
from pydantic import ValidationError

from worker.models import SummaryMessage

VALID_PAYLOAD = {
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
    "generatedAt": "2026-04-12T09:00:00Z",
}


def test_valid_payload_is_accepted():
    msg = SummaryMessage.model_validate(VALID_PAYLOAD)
    assert str(msg.user_id) == "123e4567-e89b-12d3-a456-426614174000"
    assert msg.currency == "AUD"
    assert float(msg.savings_rate) == pytest.approx(0.3125)


def test_missing_required_field_raises():
    payload = {**VALID_PAYLOAD}
    del payload["userEmail"]
    with pytest.raises(ValidationError):
        SummaryMessage.model_validate(payload)


def test_invalid_email_raises():
    payload = {**VALID_PAYLOAD, "userEmail": "not-an-email"}
    with pytest.raises(ValidationError):
        SummaryMessage.model_validate(payload)


def test_invalid_uuid_raises():
    payload = {**VALID_PAYLOAD, "userId": "not-a-uuid"}
    with pytest.raises(ValidationError):
        SummaryMessage.model_validate(payload)


def test_currency_too_long_raises():
    payload = {**VALID_PAYLOAD, "currency": "AUDD"}
    with pytest.raises(ValidationError):
        SummaryMessage.model_validate(payload)


def test_negative_total_assets_raises():
    payload = {**VALID_PAYLOAD, "totalAssetsValue": "-1.00"}
    with pytest.raises(ValidationError):
        SummaryMessage.model_validate(payload)


def test_negative_monthly_savings_is_allowed():
    # spending more than earning is valid (negative savings)
    payload = {**VALID_PAYLOAD, "monthlySavings": "-500.00", "savingsRate": "-0.0625"}
    msg = SummaryMessage.model_validate(payload)
    assert float(msg.monthly_savings) == pytest.approx(-500.0)
