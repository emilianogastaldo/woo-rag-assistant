"""Minimize model data; identity and credentials never become conversational context."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar

from app.config import settings

_private_values: ContextVar[tuple[str, ...]] = ContextVar("private_values", default=())
EMAIL = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}")
TOKEN = re.compile(r"\b(?:sk-|ck_|cs_)[A-Za-z0-9_-]+|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
IDENTITY = re.compile(
    r"(?i)(?:customer[_ -]?id|email|authorization|session[_ -]?secret)\s*[:=]\s*[^\s,;]+"
)


@contextmanager
def privacy_scope(*values: str):
    token = _private_values.set((*_private_values.get(), *(v for v in values if v)))
    try:
        yield
    finally:
        _private_values.reset(token)


def redact(value: str) -> str:
    private = (
        *_private_values.get(),
        settings.session_secret,
        settings.openai_api_key,
        settings.wc_consumer_key,
        settings.wc_consumer_secret,
        settings.llama_cloud_api_key,
    )
    for secret in sorted(set(private), key=len, reverse=True):
        if secret:
            if secret.isdecimal():
                value = re.sub(r"(?<!\w)" + re.escape(secret) + r"(?!\w)", "[REDACTED]", value)
            else:
                value = value.replace(secret, "[REDACTED]")
    return IDENTITY.sub("[REDACTED]", TOKEN.sub("[REDACTED]", EMAIL.sub("[REDACTED]", value)))


def untrusted_data(value: str) -> str:
    # JSON escaping makes nested delimiters/roles literal data. Role remains ToolMessage.
    value = redact(value).encode()[: settings.tool_output_max_bytes].decode(errors="ignore")
    return json.dumps({"untrusted_data": value}, ensure_ascii=False)


def redact_values(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_values(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_values(item) for key, item in value.items()}
    return value
