"""Tool ordini: sola lettura e sempre scoped sul cliente della sessione.

Sicurezza (vedi CLAUDE.md):
  - il customer ID è iniettato dal costruttore, mai passato dal modello;
  - la query REST filtra sempre per `customer`, e il risultato è ricontrollato
    lato codice su `customer_id` e `id` prima di essere restituito;
  - l'ordine di un altro cliente produce "ordine non trovato", mai un messaggio
    di autorizzazione negata: non si conferma nemmeno che l'ordine esista.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.tools.woo_client import WooClient

ORDER_NOT_FOUND = (
    "Nessun ordine con questo numero risulta associato all'account. "
    "Comunica al cliente che l'ordine non è stato trovato e invitalo a "
    "verificare il numero."
)

NO_ORDERS = "L'account non ha ordini registrati."

STATUS_LABELS = {
    "pending": "in attesa di pagamento",
    "processing": "in lavorazione",
    "on-hold": "sospeso",
    "completed": "completato (consegnato)",
    "cancelled": "annullato",
    "refunded": "rimborsato",
    "failed": "pagamento fallito",
    "trash": "eliminato",
}


def _format_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def format_order(order: dict[str, Any]) -> str:
    items = ", ".join(
        f"{item.get('quantity', 1)}× {item.get('name', 'articolo')}"
        for item in order.get("line_items", [])
    )
    status = order.get("status", "")
    lines = [
        f"Ordine #{order.get('number', order.get('id'))}",
        f"Stato: {STATUS_LABELS.get(status, status)}",
        f"Data ordine: {_format_date(order.get('date_created')) or 'n/d'}",
    ]
    completed_at = _format_date(order.get("date_completed"))
    if completed_at:
        lines.append(f"Data completamento/consegna: {completed_at}")
    lines.append(f"Articoli: {items or 'nessuno'}")
    lines.append(f"Totale: {order.get('total', 'n/d')} {order.get('currency', '')}".strip())
    return "\n".join(lines)


class OrderService:
    """Accesso agli ordini del solo cliente passato al costruttore."""

    def __init__(self, customer_id: int, client: WooClient | None = None) -> None:
        self._customer_id = int(customer_id)
        self._woo = client or WooClient()

    def _belongs_to_customer(self, order: dict[str, Any]) -> bool:
        return int(order.get("customer_id", 0)) == self._customer_id

    async def get_order(self, order_number: int) -> str:
        try:
            wanted = int(order_number)
        except (TypeError, ValueError):
            return ORDER_NOT_FOUND

        rows = await self._woo.get_json(
            "orders",
            {"customer": self._customer_id, "include": wanted, "per_page": 1},
        )
        for order in rows or []:
            if int(order.get("id", 0)) == wanted and self._belongs_to_customer(order):
                return format_order(order)
        return ORDER_NOT_FOUND

    async def list_orders(self, limit: int = 5) -> str:
        rows = await self._woo.get_json(
            "orders",
            {"customer": self._customer_id, "per_page": limit, "orderby": "date", "order": "desc"},
        )
        owned = [order for order in rows or [] if self._belongs_to_customer(order)]
        if not owned:
            return NO_ORDERS
        return "\n\n".join(format_order(order) for order in owned)
