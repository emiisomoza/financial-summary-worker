"""
Tests for consumer._handle_message.

We mock all I/O (repository, renderer, mailer) and the pika channel so that:
- No RabbitMQ connection is needed
- No SQLite file is written
- No email is sent

Each test drives _handle_message directly and asserts ACK or NACK was called.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from worker.consumer import _handle_message

_VALID_PAYLOAD = {
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

DB = ":memory:"


def _make_channel() -> MagicMock:
    channel = MagicMock()
    channel.basic_ack = MagicMock()
    channel.basic_nack = MagicMock()
    return channel


def _make_method(delivery_tag: int = 1) -> MagicMock:
    method = MagicMock()
    method.delivery_tag = delivery_tag
    return method


# ── happy path ────────────────────────────────────────────────────────────────

def test_valid_message_is_acked(mocker):
    mocker.patch("worker.consumer.repository.insert")
    mocker.patch("worker.consumer.repository.get_history", return_value=[])
    mocker.patch("worker.consumer.renderer.render", return_value="<html></html>")
    mocker.patch("worker.consumer.mailer.send")

    channel = _make_channel()
    _handle_message(channel, _make_method(), None, json.dumps(_VALID_PAYLOAD).encode(), DB)

    channel.basic_ack.assert_called_once_with(delivery_tag=1)
    channel.basic_nack.assert_not_called()


def test_valid_message_calls_insert(mocker):
    mock_insert = mocker.patch("worker.consumer.repository.insert")
    mocker.patch("worker.consumer.repository.get_history", return_value=[])
    mocker.patch("worker.consumer.renderer.render", return_value="<html></html>")
    mocker.patch("worker.consumer.mailer.send")

    channel = _make_channel()
    _handle_message(channel, _make_method(), None, json.dumps(_VALID_PAYLOAD).encode(), DB)

    mock_insert.assert_called_once()


def test_valid_message_calls_mailer(mocker):
    mocker.patch("worker.consumer.repository.insert")
    mocker.patch("worker.consumer.repository.get_history", return_value=[])
    mocker.patch("worker.consumer.renderer.render", return_value="<html></html>")
    mock_send = mocker.patch("worker.consumer.mailer.send")

    channel = _make_channel()
    _handle_message(channel, _make_method(), None, json.dumps(_VALID_PAYLOAD).encode(), DB)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args
    assert call_kwargs.kwargs["subject"] == "Your Financial Summary"
    assert call_kwargs.kwargs["html_body"] == "<html></html>"


# ── validation failure → NACK ─────────────────────────────────────────────────

def test_invalid_json_is_nacked(mocker):
    channel = _make_channel()
    _handle_message(channel, _make_method(), None, b"not valid json", DB)

    channel.basic_nack.assert_called_once_with(delivery_tag=1, requeue=False)
    channel.basic_ack.assert_not_called()


def test_missing_field_is_nacked(mocker):
    payload = {**_VALID_PAYLOAD}
    del payload["userEmail"]

    channel = _make_channel()
    _handle_message(channel, _make_method(), None, json.dumps(payload).encode(), DB)

    channel.basic_nack.assert_called_once_with(delivery_tag=1, requeue=False)
    channel.basic_ack.assert_not_called()


def test_invalid_email_is_nacked(mocker):
    payload = {**_VALID_PAYLOAD, "userEmail": "not-an-email"}

    channel = _make_channel()
    _handle_message(channel, _make_method(), None, json.dumps(payload).encode(), DB)

    channel.basic_nack.assert_called_once_with(delivery_tag=1, requeue=False)
    channel.basic_ack.assert_not_called()


def test_negative_total_assets_is_nacked(mocker):
    payload = {**_VALID_PAYLOAD, "totalAssetsValue": "-1.00"}

    channel = _make_channel()
    _handle_message(channel, _make_method(), None, json.dumps(payload).encode(), DB)

    channel.basic_nack.assert_called_once_with(delivery_tag=1, requeue=False)
    channel.basic_ack.assert_not_called()


# ── downstream failure → NACK ─────────────────────────────────────────────────

def test_mailer_failure_is_nacked(mocker):
    mocker.patch("worker.consumer.repository.insert")
    mocker.patch("worker.consumer.repository.get_history", return_value=[])
    mocker.patch("worker.consumer.renderer.render", return_value="<html></html>")
    mocker.patch("worker.consumer.mailer.send", side_effect=Exception("SMTP error"))

    channel = _make_channel()
    _handle_message(channel, _make_method(), None, json.dumps(_VALID_PAYLOAD).encode(), DB)

    channel.basic_nack.assert_called_once_with(delivery_tag=1, requeue=False)
    channel.basic_ack.assert_not_called()


def test_repository_insert_failure_is_nacked(mocker):
    mocker.patch("worker.consumer.repository.insert", side_effect=Exception("DB error"))

    channel = _make_channel()
    _handle_message(channel, _make_method(), None, json.dumps(_VALID_PAYLOAD).encode(), DB)

    channel.basic_nack.assert_called_once_with(delivery_tag=1, requeue=False)
    channel.basic_ack.assert_not_called()


def test_renderer_failure_is_nacked(mocker):
    mocker.patch("worker.consumer.repository.insert")
    mocker.patch("worker.consumer.repository.get_history", return_value=[])
    mocker.patch("worker.consumer.renderer.render", side_effect=Exception("template error"))

    channel = _make_channel()
    _handle_message(channel, _make_method(), None, json.dumps(_VALID_PAYLOAD).encode(), DB)

    channel.basic_nack.assert_called_once_with(delivery_tag=1, requeue=False)
    channel.basic_ack.assert_not_called()


# ── delivery tag forwarded correctly ─────────────────────────────────────────

def test_ack_uses_correct_delivery_tag(mocker):
    mocker.patch("worker.consumer.repository.insert")
    mocker.patch("worker.consumer.repository.get_history", return_value=[])
    mocker.patch("worker.consumer.renderer.render", return_value="<html></html>")
    mocker.patch("worker.consumer.mailer.send")

    channel = _make_channel()
    _handle_message(channel, _make_method(delivery_tag=42), None, json.dumps(_VALID_PAYLOAD).encode(), DB)

    channel.basic_ack.assert_called_once_with(delivery_tag=42)


def test_nack_uses_correct_delivery_tag(mocker):
    channel = _make_channel()
    _handle_message(channel, _make_method(delivery_tag=99), None, b"bad json", DB)

    channel.basic_nack.assert_called_once_with(delivery_tag=99, requeue=False)
