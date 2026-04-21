"""
Tests for mailer.py (SMTP email sending).

smtplib.SMTP is fully mocked — no network connection is made.
We verify:
- STARTTLS is called (TLS enforced)
- login() is called with the right credentials
- sendmail() is called with the right sender and recipient
- The email body contains the expected HTML
- Missing required env vars raise KeyError before any SMTP connection
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from worker import mailer

_ENV = {
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "user@example.com",
    "SMTP_PASSWORD": "secret",
    "EMAIL_FROM": "noreply@example.com",
}


@pytest.fixture(autouse=True)
def smtp_env(monkeypatch):
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def mock_smtp(mocker):
    mock_instance = MagicMock()
    mock_class = mocker.patch("worker.mailer.smtplib.SMTP")
    mock_class.return_value.__enter__ = MagicMock(return_value=mock_instance)
    mock_class.return_value.__exit__ = MagicMock(return_value=False)
    return mock_instance


# ── TLS and auth ──────────────────────────────────────────────────────────────

def test_starttls_is_called(mock_smtp):
    mailer.send("bob@example.com", "Subject", "<p>Hello</p>")
    mock_smtp.starttls.assert_called_once()


def test_login_is_called_with_correct_credentials(mock_smtp):
    mailer.send("bob@example.com", "Subject", "<p>Hello</p>")
    mock_smtp.login.assert_called_once_with("user@example.com", "secret")


def test_ehlo_is_called(mock_smtp):
    mailer.send("bob@example.com", "Subject", "<p>Hello</p>")
    assert mock_smtp.ehlo.call_count >= 1


# ── sendmail ──────────────────────────────────────────────────────────────────

def test_sendmail_uses_correct_from_and_to(mock_smtp):
    mailer.send("bob@example.com", "Subject", "<p>Hello</p>")
    args = mock_smtp.sendmail.call_args
    from_addr, to_addrs, _ = args[0]
    assert from_addr == "noreply@example.com"
    assert "bob@example.com" in to_addrs


def test_sendmail_includes_html_body(mock_smtp):
    import email as _email
    mailer.send("bob@example.com", "Subject", "<p>Hello World</p>")
    raw_message = mock_smtp.sendmail.call_args[0][2]
    parsed = _email.message_from_string(raw_message)
    for part in parsed.walk():
        if part.get_content_type() == "text/html":
            assert "Hello World" in part.get_payload(decode=True).decode("utf-8")
            return
    pytest.fail("No text/html part found in email")


def test_sendmail_includes_subject(mock_smtp):
    mailer.send("bob@example.com", "My Subject", "<p>body</p>")
    raw_message = mock_smtp.sendmail.call_args[0][2]
    assert "My Subject" in raw_message


def test_sendmail_content_type_is_html(mock_smtp):
    mailer.send("bob@example.com", "Subject", "<p>body</p>")
    raw_message = mock_smtp.sendmail.call_args[0][2]
    assert "text/html" in raw_message


# ── missing env vars ──────────────────────────────────────────────────────────

def test_missing_smtp_host_raises(monkeypatch, mocker):
    monkeypatch.delenv("SMTP_HOST")
    mocker.patch("worker.mailer.smtplib.SMTP")
    with pytest.raises(KeyError):
        mailer.send("bob@example.com", "Subject", "<p>body</p>")


def test_missing_smtp_password_raises(monkeypatch, mocker):
    monkeypatch.delenv("SMTP_PASSWORD")
    mocker.patch("worker.mailer.smtplib.SMTP")
    with pytest.raises(KeyError):
        mailer.send("bob@example.com", "Subject", "<p>body</p>")


def test_missing_email_from_raises(monkeypatch, mocker):
    monkeypatch.delenv("EMAIL_FROM")
    mocker.patch("worker.mailer.smtplib.SMTP")
    with pytest.raises(KeyError):
        mailer.send("bob@example.com", "Subject", "<p>body</p>")
