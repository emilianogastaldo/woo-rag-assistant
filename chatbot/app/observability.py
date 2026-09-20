"""Request correlation and structured, redacted operational logging."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
conversation_id_var: ContextVar[str] = ContextVar("conversation_id", default="-")

logger = logging.getLogger("woo_rag.operations")


@contextmanager
def correlation(request_id: str, conversation_id: str) -> Iterator[None]:
    request_token = request_id_var.set(request_id)
    conversation_token = conversation_id_var.set(conversation_id)
    try:
        yield
    finally:
        conversation_id_var.reset(conversation_token)
        request_id_var.reset(request_token)


def log_event(*, event: str, outcome: str, duration_ms: float, tool: str | None = None,
              failure: str | None = None, attempt: int | None = None) -> None:
    """Log only a fixed metadata allowlist; arguments, URLs and exceptions stay out."""
    record: dict[str, str | int | float | None] = {
        "event": event,
        "request_id": request_id_var.get(),
        "conversation_id": conversation_id_var.get(),
        "tool": tool,
        "duration_ms": round(duration_ms, 3),
        "outcome": outcome,
    }
    if failure is not None:
        record["failure"] = failure
    if attempt is not None:
        record["attempt"] = attempt
    logger.info(json.dumps(record, separators=(",", ":"), ensure_ascii=True))
