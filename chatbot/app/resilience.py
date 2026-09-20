"""Bounded retries and stable failure types shared by agent, retrieval and tools."""
from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from enum import StrEnum

import httpx
import openai

from app.observability import log_event


class FailureKind(StrEnum):
    VALIDATION = "validation"
    TIMEOUT = "timeout"
    HTTP_CLIENT = "http_4xx"
    HTTP_SERVER = "http_5xx"
    RATE_LIMIT = "rate_limit"
    CHROMA_UNAVAILABLE = "chroma_unavailable"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MALFORMED_RESPONSE = "malformed_response"
    UNKNOWN_TOOL = "unknown_tool"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MAX_STEPS = "max_steps"
    REPEATED_ERROR = "repeated_error"


class RecoverableFailure(Exception):
    def __init__(self, kind: FailureKind, *, retryable: bool = False,
                 retry_after: float | None = None) -> None:
        super().__init__(kind.value)
        self.kind = kind
        self.retryable = retryable
        self.retry_after = retry_after


class BudgetExhausted(RecoverableFailure):
    def __init__(self) -> None:
        super().__init__(FailureKind.BUDGET_EXHAUSTED)


@dataclass
class AttemptBudget:
    max_attempts: int
    max_retries: int
    deadline_seconds: float
    started_at: float = field(default_factory=time.monotonic)
    attempts: int = 0
    retries: int = 0

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline_seconds - (time.monotonic() - self.started_at))

    def consume(self, *, retry: bool = False) -> int:
        if (self.remaining_seconds <= 0 or self.attempts >= self.max_attempts
                or (retry and self.retries >= self.max_retries)):
            log_event(event="budget", outcome="stopped", duration_ms=0,
                      failure=FailureKind.BUDGET_EXHAUSTED, attempt=self.attempts)
            raise BudgetExhausted()
        self.attempts += 1
        if retry:
            self.retries += 1
        return self.attempts


_budget_var: ContextVar[AttemptBudget | None] = ContextVar("attempt_budget", default=None)


def current_budget() -> AttemptBudget | None:
    return _budget_var.get()


@contextmanager
def budget_scope(budget: AttemptBudget) -> Iterator[AttemptBudget]:
    token = _budget_var.set(budget)
    try:
        yield budget
    finally:
        _budget_var.reset(token)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


async def retry_call[T](
    operation: str,
    call: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    timeout_seconds: float,
    idempotent: bool,
    first_attempt_is_retry: bool = False,
    budget: AttemptBudget | None = None,
) -> T:
    """Retry one read-only boundary while consuming the request-wide retry budget."""
    active = budget or current_budget() or AttemptBudget(
        max_attempts=max_retries + 1,
        max_retries=max_retries,
        deadline_seconds=timeout_seconds * (max_retries + 1),
    )
    for retry_number in range(max_retries + 1):
        is_retry = first_attempt_is_retry or retry_number > 0
        attempt = active.consume(retry=is_retry)
        timeout = min(timeout_seconds, active.remaining_seconds)
        if timeout <= 0:
            raise BudgetExhausted()
        started = time.perf_counter()
        try:
            async with asyncio.timeout(timeout):
                result = await call()
        except TimeoutError as exc:
            failure = RecoverableFailure(FailureKind.TIMEOUT, retryable=True)
            log_event(
                event=operation,
                outcome="error",
                duration_ms=(time.perf_counter() - started) * 1000,
                failure=failure.kind,
                attempt=attempt,
            )
            caught: RecoverableFailure = failure
            cause: BaseException = exc
        except RecoverableFailure as exc:
            log_event(
                event=operation,
                outcome="error",
                duration_ms=(time.perf_counter() - started) * 1000,
                failure=exc.kind,
                attempt=attempt,
            )
            caught, cause = exc, exc
        else:
            log_event(
                event=operation,
                outcome="ok",
                duration_ms=(time.perf_counter() - started) * 1000,
                attempt=attempt,
            )
            return result
        if (not idempotent or not caught.retryable or retry_number >= max_retries):
            raise caught from cause
        if active.retries >= active.max_retries or active.attempts >= active.max_attempts:
            raise BudgetExhausted()
        remaining = active.remaining_seconds
        requested_delay = caught.retry_after or 0.0
        delay = min(requested_delay, remaining)
        if delay > 0:
            await asyncio.sleep(delay)
        if requested_delay >= remaining:
            # Timers may wake slightly early; never shorten the server's Retry-After.
            raise BudgetExhausted()
    raise AssertionError("unreachable")


async def provider_call(operation, call):
    from app.config import settings

    async def mapped():
        try:
            return await call()
        except (openai.APITimeoutError, httpx.TimeoutException) as exc:
            raise RecoverableFailure(FailureKind.TIMEOUT, retryable=True) from exc
        except openai.APIResponseValidationError as exc:
            raise RecoverableFailure(FailureKind.MALFORMED_RESPONSE) from exc
        except openai.APIConnectionError as exc:
            raise RecoverableFailure(FailureKind.PROVIDER_UNAVAILABLE, retryable=True) from exc
        except openai.APIStatusError as exc:
            raise RecoverableFailure(
                FailureKind.RATE_LIMIT if exc.status_code == 429
                else FailureKind.PROVIDER_UNAVAILABLE,
                retryable=exc.status_code == 429 or exc.status_code >= 500,
                retry_after=parse_retry_after(exc.response.headers.get("Retry-After")),
            ) from exc

    return await retry_call(operation, mapped, max_retries=settings.provider_retry_attempts,
                            timeout_seconds=settings.provider_timeout_seconds, idempotent=True)


TOOL_MESSAGES = {
    FailureKind.VALIDATION: (
        "Argomenti dello strumento mancanti o non validi. Correggili e riprova."
    ),
    FailureKind.TIMEOUT: "Servizio temporaneamente non disponibile: tempo di attesa scaduto.",
    FailureKind.HTTP_CLIENT: (
        "Il servizio ha rifiutato la richiesta. Verifica i dati senza inventare risultati."
    ),
    FailureKind.HTTP_SERVER: "Servizio temporaneamente non disponibile. Riprova piu tardi.",
    FailureKind.RATE_LIMIT: "Servizio temporaneamente occupato. Riprova piu tardi.",
    FailureKind.CHROMA_UNAVAILABLE: (
        "Knowledge base temporaneamente non disponibile. Non presentare questo errore "
        "come assenza di risultati."
    ),
    FailureKind.PROVIDER_UNAVAILABLE: "Modello temporaneamente non disponibile.",
    FailureKind.MALFORMED_RESPONSE: (
        "Il servizio ha restituito dati non leggibili. Non inventare risultati."
    ),
    FailureKind.UNKNOWN_TOOL: "Strumento non disponibile per questa conversazione.",
    FailureKind.BUDGET_EXHAUSTED: (
        "Budget massimo dei tentativi esaurito. Interrompi le chiamate agli strumenti."
    ),
}


def tool_failure_message(kind: FailureKind) -> str:
    return TOOL_MESSAGES.get(kind, "Servizio temporaneamente non disponibile.")
