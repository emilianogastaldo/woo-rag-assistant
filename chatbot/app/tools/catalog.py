"""Tool catalogo: disponibilità e prezzo in tempo reale.

Lo stock è stato *dinamico*: non viene indicizzato nel RAG (dove sarebbe subito
obsoleto) ma letto al momento dalle API WooCommerce. Il tool è disponibile anche
agli utenti anonimi: non espone nulla di riservato.
"""
from __future__ import annotations

from typing import Any

from app.tools.woo_client import WooClient

NOT_FOUND = (
    "Nessun prodotto corrispondente nel catalogo. Comunica che non risulta a "
    "catalogo e non inventare disponibilità o prezzi."
)

STOCK_LABELS = {
    "instock": "disponibile",
    "outofstock": "esaurito",
    "onbackorder": "ordinabile su prenotazione",
}


def format_product(product: dict[str, Any]) -> str:
    stock_status = product.get("stock_status", "")
    lines = [
        f"Prodotto: {product.get('name', 'n/d')} (SKU {product.get('sku') or 'n/d'})",
        f"Disponibilità: {STOCK_LABELS.get(stock_status, stock_status or 'n/d')}",
    ]
    quantity = product.get("stock_quantity")
    if quantity is not None:
        lines.append(f"Pezzi a magazzino: {quantity}")
    if product.get("price"):
        lines.append(f"Prezzo: {product['price']} EUR")
    if product.get("permalink"):
        lines.append(f"Scheda: {product['permalink']}")
    return "\n".join(lines)


class CatalogService:
    def __init__(self, client: WooClient | None = None) -> None:
        self._woo = client or WooClient()

    async def check_availability(self, product: str, limit: int = 3) -> str:
        query = (product or "").strip()
        if not query:
            return NOT_FOUND

        rows = await self._woo.get_json(
            "products", {"sku": query, "status": "publish", "per_page": 1}
        )
        if not rows:
            rows = await self._woo.get_json(
                "products", {"search": query, "status": "publish", "per_page": limit}
            )
        if not rows:
            return NOT_FOUND
        return "\n\n".join(format_product(row) for row in rows)
