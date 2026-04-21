"""
SMTP email sender.

Security decisions:
- STARTTLS is always enforced (port 587). Plaintext SMTP is not supported.
- Credentials come exclusively from environment variables — never hardcoded.
- The recipient address and email body are NEVER logged.
  Logs only contain the subject and outcome (success/error).

Why smtplib (stdlib) instead of a third-party library?
- Zero extra dependency for the core functionality.
- Works with any SMTP provider (Gmail, Resend relay, Sendgrid relay, Mailtrap).
- To switch providers, only the .env credentials change — no code changes needed.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send(to: str, subject: str, html_body: str) -> None:
    """
    Send an HTML email via STARTTLS SMTP.

    Configuration (from environment):
        SMTP_HOST     — SMTP server hostname
        SMTP_PORT     — SMTP port (default: 587)
        SMTP_USER     — SMTP username / login
        SMTP_PASSWORD — SMTP password
        EMAIL_FROM    — Sender address shown in the From header

    Raises:
        smtplib.SMTPException on connection or send failure.
        The caller (consumer.py) catches this and NACKs the message.
    """
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    from_addr = os.environ["EMAIL_FROM"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(host, port) as smtp:
        smtp.ehlo()
        smtp.starttls()   # upgrade to TLS — required, no plaintext fallback
        smtp.ehlo()
        smtp.login(user, password)
        smtp.sendmail(from_addr, [to], msg.as_string())
