"""Fixture condivise: doppi di test per WooCommerce e per il vector store.

Nessun test tocca la rete: né WooCommerce, né ChromaDB, né OpenAI.
"""
from __future__ import annotations

from typing import Any

import pytest


class FakeWooClient:
    """Sostituto di `WooClient` che registra le chiamate e restituisce dati finti."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    async def get_json(self, path: str, params: dict | None = None) -> Any:
        self.calls.append((path, dict(params or {})))
        value = self.responses.get(path, [])
        return value(params or {}) if callable(value) else value

    def params_for(self, path: str) -> dict:
        for called_path, params in self.calls:
            if called_path == path:
                return params
        raise AssertionError(f"nessuna chiamata a {path}: {self.calls}")


def make_order(order_id: int, customer_id: int, **overrides: Any) -> dict:
    order = {
        "id": order_id,
        "number": str(order_id),
        "customer_id": customer_id,
        "status": "processing",
        "currency": "EUR",
        "total": "59.00",
        "date_created": "2026-07-11T09:30:00",
        "date_completed": None,
        "line_items": [{"name": "Zaino Urban", "quantity": 1, "sku": "BACKPACK-URBAN"}],
    }
    order.update(overrides)
    return order


@pytest.fixture
def woo() -> FakeWooClient:
    return FakeWooClient()
