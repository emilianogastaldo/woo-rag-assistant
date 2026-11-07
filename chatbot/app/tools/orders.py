"""Tool ordini: sola lettura e sempre scoped sul cliente della sessione.

Sicurezza (vedi CLAUDE.md):
  - il customer ID è iniettato dal costruttore, mai passato dal modello;
  - la query REST filtra sempre per `customer`, e il risultato è ricontrollato
    lato codice su `customer_id` e `id` prima di essere restituito;
  - l'ordine di un altro cliente produce "ordine non trovato", mai un messaggio
    di autorizzazione negata: non si conferma nemmeno che l'ordine esista.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.config import settings
from app.resilience import FailureKind, RecoverableFailure
from app.tools.payloads import validate_rows
from app.tools.woo_client import WooClient, shared_woo_client

ORDER_NOT_FOUND = (
    "Nessun ordine con questo numero risulta associato all'account. "
    "Comunica al cliente che l'ordine non è stato trovato e invitalo a "
    "verificare il numero."
)

MAX_SEARCH_PAGES = 5
SEARCH_PAGE_SIZE = 20
SEARCH_LIMIT = "Ricerca limitata ai 100 ordini più recenti dell'account; contatta l'assistenza."


class OrderLookup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    numero_ordine: (
        Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")]
        | Annotated[int, Field(gt=0)]
    ) = Field(description="Numero pubblico esatto come stringa; intero solo per ID interno legacy")


class OrderList(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    date_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    page: int = Field(default=1, ge=1, le=50)
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("date_from", "date_to")
    @classmethod
    def valid_calendar_date(cls, value):
        if value is not None:
            parsed = date.fromisoformat(value)
            if parsed.year in {1, 9999}:
                raise ValueError("date year must be between 0002 and 9998")
        return value

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        return self


# Convenzione del negozio: questo metadata viene scritto dall'integrazione di
# tracking soltanto dopo la conferma di consegna del corriere. WooCommerce non
# espone una data di consegna standard, quindi date_completed non è un sostituto.
DELIVERY_DATE_META_KEY = "_wrag_delivery_date"
RETURN_WINDOW_DAYS = 30

STATUS_LABELS = {
    "pending": "in attesa di pagamento",
    "processing": "in lavorazione",
    "on-hold": "sospeso",
    "completed": "completato",
    "cancelled": "annullato",
    "refunded": "rimborsato",
    "failed": "pagamento fallito",
    "trash": "eliminato",
}


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_date(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.strftime("%d/%m/%Y")
    return str(value) if value else None


def _verified_delivery_at(order: dict[str, Any]) -> datetime | None:
    """Restituisce solo la consegna esplicitamente confermata dal tracking.

    ``date_completed`` rappresenta il completamento amministrativo dell'ordine
    e non viene mai usata qui: non prova che il pacco sia stato consegnato.
    """
    metadata = order.get("meta_data", [])
    if not isinstance(metadata, list):
        return None

    for metadata_item in metadata:
        if not isinstance(metadata_item, dict):
            continue
        if metadata_item.get("key") == DELIVERY_DATE_META_KEY:
            return _parse_datetime(metadata_item.get("value"))
    return None


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
        lines.append(f"Data completamento: {completed_at}")
    delivered_at = _verified_delivery_at(order)
    if delivered_at:
        lines.append(f"Data consegna verificata: {delivered_at.strftime('%d/%m/%Y')}")
        deadline = delivered_at + timedelta(days=RETURN_WINDOW_DAYS)
        lines.append(
            f"Scadenza reso ({RETURN_WINDOW_DAYS} giorni dalla consegna verificata): "
            f"{deadline.strftime('%d/%m/%Y')}"
        )
    else:
        lines.append("Data consegna verificata: non disponibile")
        lines.append(
            "Scadenza reso: non calcolabile senza una data di consegna verificata; "
            "contatta l'assistenza."
        )
    lines.append(f"Articoli: {items or 'nessuno'}")
    lines.append(f"Totale: {order.get('total', 'n/d')} {order.get('currency', '')}".strip())
    return "\n".join(lines)


class OrderService:
    """Accesso agli ordini del solo cliente passato al costruttore."""

    def __init__(self, customer_id: int, client: WooClient | None = None) -> None:
        self._customer_id = int(customer_id)
        self._woo = client or shared_woo_client()

    def _belongs_to_customer(self, order: dict[str, Any]) -> bool:
        return order.get("customer_id") == self._customer_id

    async def get_order(self, order_number: str | int) -> str:
        try:
            wanted = OrderLookup(numero_ordine=order_number).numero_ordine
        except ValidationError:
            return ORDER_NOT_FOUND

        if isinstance(wanted, int):
            rows = validate_rows("orders", await self._woo.get_json(
                "orders", {"customer": self._customer_id, "include": wanted, "per_page": 1},
            ))
            matches = [o for o in rows if o["id"] == wanted and self._belongs_to_customer(o)]
            return format_order(matches[0]) if len(matches) == 1 else ORDER_NOT_FOUND

        matches = {}
        for page in range(1, MAX_SEARCH_PAGES + 1):
            rows = validate_rows("orders", await self._woo.get_json("orders", {
                "customer": self._customer_id, "per_page": SEARCH_PAGE_SIZE,
                "page": page, "orderby": "date", "order": "desc",
            }))
            if len(rows) > SEARCH_PAGE_SIZE:
                raise RecoverableFailure(FailureKind.MALFORMED_RESPONSE)
            for order in rows:
                if self._belongs_to_customer(order) and order.get("number") == wanted:
                    matches[order["id"]] = order
            if len(matches) > 1:
                return "Numero d'ordine ambiguo nell'account; contatta l'assistenza."
            if len(rows) < SEARCH_PAGE_SIZE:
                break
        else:
            return ORDER_NOT_FOUND + "\n" + SEARCH_LIMIT
        return format_order(next(iter(matches.values()))) if matches else ORDER_NOT_FOUND

    async def list_orders(self, limit: int = 5, *, date_from: str | None = None,
                          date_to: str | None = None, page: int = 1) -> str:
        query = OrderList(limit=limit, date_from=date_from, date_to=date_to, page=page)
        params = {"customer": self._customer_id, "per_page": query.limit, "page": query.page,
                  "orderby": "date", "order": "desc", "dates_are_gmt": "true"}
        zone = ZoneInfo(settings.wc_order_timezone)
        for value, key, boundary, offset in (
            (query.date_from, "after", time.min, -1),
            (query.date_to, "before", time(23, 59, 59), 1),
        ):
            if value:
                local = datetime.combine(date.fromisoformat(value), boundary, tzinfo=zone)
                # WooCommerce before/after are exclusive; widen by one second for whole days.
                bound = local.astimezone(UTC) + timedelta(seconds=offset)
                params[key] = bound.isoformat(timespec="seconds").removesuffix("+00:00")
        rows = validate_rows("orders", await self._woo.get_json("orders", params))
        owned = []
        for order in rows:
            if not self._belongs_to_customer(order):
                continue
            if query.date_from or query.date_to:
                created = _parse_datetime(order.get("date_created_gmt"))
                if created:
                    created = (created if created.tzinfo else
                               created.replace(tzinfo=UTC)).astimezone(zone)
                else:
                    created = _parse_datetime(order.get("date_created"))
                    if created and created.tzinfo:
                        created = created.astimezone(zone)
                if not created:
                    raise RecoverableFailure(FailureKind.MALFORMED_RESPONSE)
                local_date = created.date().isoformat()
                if ((query.date_from and local_date < query.date_from)
                        or (query.date_to and local_date > query.date_to)):
                    continue
            owned.append(order)
        result = ("\n\n".join(format_order(order) for order in owned[:query.limit]) if owned else
                  "Nessun ordine trovato nei filtri e nella pagina richiesti.")
        result += f"\n\nPagina {query.page}; date nel fuso {settings.wc_order_timezone}."
        if len(rows) >= query.limit:
            result += (" Risultati potenzialmente parziali; richiedi la pagina successiva."
                       if query.page < 50 else " Limite di 50 pagine raggiunto; restringi le date.")
        return result
