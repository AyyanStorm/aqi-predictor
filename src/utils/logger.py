import json
import logging
import os
from typing import Optional

# Import at runtime to avoid circular imports
_request_context = None

def _get_request_id() -> str:
    """Get request ID from context if available."""
    try:
        global _request_context
        if _request_context is None:
            from src.utils import request_context as _rc
            _request_context = _rc
        return _request_context.get_request_id()
    except Exception:
        return 'unknown'


class _JsonFormatter(logging.Formatter):
    """JSON-structured formatter — one searchable object per log line.

    Enabled with LOG_FORMAT=json (default: plain key=value text, which
    is also grep-able on Render). Structured fields passed via
    log_event(..., **fields) are merged into the JSON payload so
    log-drain tools (or Render's log search) can filter on them.
    """

    def format(self, record):
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": _get_request_id(),
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def get_logger(name, structured=None):
    """Return a configured logger.

    structured=True/False overrides; None falls back to the
    LOG_FORMAT=json env var (plain text otherwise).
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler()
        use_json = (
            structured
            if structured is not None
            else os.environ.get("LOG_FORMAT", "").lower() == "json"
        )
        if use_json:
            handler.setFormatter(_JsonFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)s | %(name)s | [%(request_id)s] %(message)s",
                    defaults={'request_id': 'unknown'}
                )
            )
        logger.addHandler(handler)

    return logger


class RequestIDFilter(logging.Filter):
    """Logging filter that adds request ID to all log records."""

    def filter(self, record):
        """Add request ID to log record.
        
        Args:
            record: Log record to enhance
            
        Returns:
            bool: True to allow log (always)
        """
        if not hasattr(record, 'request_id'):
            record.request_id = _get_request_id()
        return True


def log_event(logger, event, level=logging.INFO, **fields):
    """Emit a structured log line: event=... plus any key=value fields.

    Example:
        log_event(logger, "forecast_request", city="Karachi",
                  status="ok", duration_ms=123.4)
    -> "event=forecast_request city=Karachi status=ok duration_ms=123.4"
       (or a JSON object when LOG_FORMAT=json).
    """
    fields["event"] = event
    msg = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.log(level, msg, extra={"fields": fields})
