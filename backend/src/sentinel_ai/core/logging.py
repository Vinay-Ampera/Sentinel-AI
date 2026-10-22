"""Logging setup with credential redaction."""

import logging
import re

_URL_CREDENTIALS = re.compile(r"(\w+(?:\+\w+)?://[^:/\s@]*:)[^@\s]+(@)")


class RedactingFilter(logging.Filter):
    """Masks passwords embedded in URLs (e.g. postgresql://user:SECRET@host)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _URL_CREDENTIALS.sub(r"\1***\2", message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    for existing in root.handlers:
        if not any(isinstance(f, RedactingFilter) for f in existing.filters):
            existing.addFilter(RedactingFilter())
