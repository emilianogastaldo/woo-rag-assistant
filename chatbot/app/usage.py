"""Runtime provider reservations and content-free usage counters for HTTP chat."""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass

from app.config import settings
from app.observability import log_event
from app.resilience import BudgetExhausted, current_budget


@dataclass
class Usage:
    model_calls: int = 0
    embedding_calls: int = 0
    reserved_units: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    missing_model_usage: int = 0
    missing_embedding_usage: int = 0
    outcome: str = "error"


_active: ContextVar[tuple | None] = ContextVar("runtime_usage", default=None)


@contextmanager
def usage_scope(store):
    usage = Usage()
    token = _active.set((store, usage))
    started = time.perf_counter()
    try:
        yield usage
    except BaseException:
        if usage.outcome != "daily_limit":
            usage.outcome = "error"
        raise
    finally:
        _active.reset(token)
        counters = asdict(usage)
        outcome = counters.pop("outcome")
        budget = current_budget()
        log_event(event="usage", outcome=outcome,
                  duration_ms=(time.perf_counter() - started) * 1000,
                  attempt=budget.attempts if budget else 0, usage=counters)


def reserve_provider_units(operation: str, units: int) -> None:
    active = _active.get()
    if active is None:
        return  # Offline ingestion/eval have their own explicit budgets.
    store, usage = active
    try:
        store.reserve_usage(units, settings.provider_daily_unit_limit)
    except BudgetExhausted:
        usage.outcome = "daily_limit"
        raise
    usage.reserved_units += units
    if operation == "model":
        usage.model_calls += 1
        usage.missing_model_usage += 1
    else:
        # LangChain aembed_query returns vectors, without provider usage metadata.
        usage.embedding_calls += 1
        usage.missing_embedding_usage += 1


def record_model_usage(metadata) -> None:
    active = _active.get()
    if active is None or not isinstance(metadata, dict):
        return
    counts = [metadata.get(name) for name in ("input_tokens", "output_tokens")]
    if all(type(count) is int and count >= 0 for count in counts):
        usage = active[1]
        usage.input_tokens += counts[0]
        usage.output_tokens += counts[1]
        usage.missing_model_usage -= 1
