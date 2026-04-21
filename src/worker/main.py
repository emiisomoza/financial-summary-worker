"""
Entry point for the financial-summary-worker.

Startup sequence:
1. Load environment variables from .env (if present — for local development)
2. Configure structured logging
3. Initialize the SQLite database (create table if not exists)
4. Start consuming from RabbitMQ

Why separate main.py from consumer.py?
- main.py owns setup/teardown (env, logging, DB init).
- consumer.py owns the message loop.
- Tests can import consumer.py and repository.py directly without triggering
  RabbitMQ connections or .env loading.
"""

import logging
import os
import sys

import structlog
from dotenv import load_dotenv

from worker import consumer, repository

# Load .env for local development.
# In Docker/production, environment variables are injected by the container runtime
# and this call is a no-op (load_dotenv does not override already-set variables).
load_dotenv()


def _configure_logging() -> None:
    """
    Configure structlog for structured JSON output.

    Security: the PII processor below strips sensitive fields from log records.
    user_email and user_name are never written to logs — only user_id (a UUID,
    not personally identifiable on its own in most jurisdictions).
    """
    _PII_FIELDS = {"user_email", "user_name", "to", "from"}

    def _redact_pii(logger: object, method: str, event_dict: dict) -> dict:
        for field in _PII_FIELDS:
            if field in event_dict:
                event_dict[field] = "[REDACTED]"
        return event_dict

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    def _rename_level(logger: object, method: str, event_dict: dict) -> dict:
        # Rename log_level → level to match Java structured log field names
        if "log_level" in event_dict:
            event_dict["level"] = event_dict.pop("log_level")
        return event_dict

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _rename_level,
            _redact_pii,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level, logging.INFO),
    )


def main() -> None:
    _configure_logging()

    log = structlog.get_logger()
    db_path = os.environ.get("DB_PATH", "./data/summaries.db")

    log.info("worker.starting", db_path=db_path)
    repository.init_db(db_path)
    log.info("db.initialized", db_path=db_path)

    consumer.start(db_path)


if __name__ == "__main__":
    main()
