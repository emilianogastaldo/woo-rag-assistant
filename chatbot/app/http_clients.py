"""Request-scoped access to application-owned HTTP clients."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

_provider_client: ContextVar[httpx.AsyncClient | None] = ContextVar(
    "provider_http_client", default=None
)


@contextmanager
def provider_client_scope(client: httpx.AsyncClient) -> Iterator[None]:
    token = _provider_client.set(client)
    try:
        yield
    finally:
        _provider_client.reset(token)


def current_provider_client() -> httpx.AsyncClient | None:
    return _provider_client.get()
