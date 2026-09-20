"""Sessione server-side: validazione del token e risoluzione del customer ID.

Regola non negoziabile: il customer ID non arriva mai dal client e non è mai
visibile al modello. Il client presenta solo un token firmato; il backend ne
verifica la firma, ne estrae l'identità e risolve il customer ID su WooCommerce.

Per la demo l'autenticazione è mockata: `POST /demo/login` emette un token per uno
dei clienti creati dal seed. Il token è comunque firmato HMAC-SHA256 con
`SESSION_SECRET`, quindi non è falsificabile lato client: cambia la provenienza
dell'identità, non il modo in cui viene verificata.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass

from app.config import settings
from app.resilience import FailureKind, RecoverableFailure
from app.tools.woo_client import WooClient, shared_woo_client

# Clienti demo creati da seed/seed.php (chiave -> email).
DEMO_CUSTOMERS: dict[str, str] = {
    "A": "mario.rossi@example.com",
    "B": "luigi.verdi@example.com",
}


class SessionError(Exception):
    """Token assente, malformato, scaduto o con firma non valida."""


@dataclass(frozen=True)
class Session:
    email: str
    customer_id: int


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _signature(payload: bytes) -> str:
    digest = hmac.new(settings.session_secret.encode(), payload, hashlib.sha256).digest()
    return _b64encode(digest)


def issue_token(email: str, ttl_seconds: int | None = None) -> str:
    """Emette un token di sessione firmato per l'email indicata."""
    expires_at = int(time.time()) + (
        settings.session_ttl_seconds if ttl_seconds is None else ttl_seconds
    )
    payload = json.dumps(
        {"sub": email, "exp": expires_at, "sid": secrets.token_urlsafe(24)}, separators=(",", ":")
    ).encode()
    return f"{_b64encode(payload)}.{_signature(payload)}"


def verify_token(token: str) -> str:
    """Verifica firma e scadenza, restituisce l'email. Solleva `SessionError`."""
    if len(token) > 4096:
        raise SessionError("token malformato")
    try:
        payload_b64, signature = token.split(".", 1)
        payload = _b64decode(payload_b64)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise SessionError("token malformato") from exc

    if not signature.isascii() or not hmac.compare_digest(_signature(payload), signature):
        raise SessionError("firma non valida")
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise SessionError("token malformato") from exc
    if not isinstance(data, dict) or not isinstance(data.get("sub"), str):
        raise SessionError("token malformato")
    if type(data.get("exp")) is not int or not data["sub"]:
        raise SessionError("token malformato")
    if data["exp"] <= time.time():
        raise SessionError("sessione scaduta")
    return data["sub"]


_customer_id_cache: OrderedDict[str, tuple[int, float]] = OrderedDict()


async def resolve_customer_id(email: str, client: WooClient | None = None) -> int | None:
    """Risolve l'ID cliente WooCommerce a partire dall'email (con cache)."""
    now = time.monotonic()
    for key, (_, expires) in list(_customer_id_cache.items()):
        if expires <= now:
            del _customer_id_cache[key]
    if email in _customer_id_cache:
        _customer_id_cache.move_to_end(email)
        return _customer_id_cache[email][0]

    woo = client or shared_woo_client()
    rows = await woo.get_json("customers", {"email": email, "role": "all", "per_page": 1})
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RecoverableFailure(FailureKind.MALFORMED_RESPONSE)
    if not rows:
        return None
    customer_id = int(rows[0]["id"])
    while len(_customer_id_cache) >= settings.customer_cache_capacity:
        _customer_id_cache.popitem(last=False)
    _customer_id_cache[email] = customer_id, time.monotonic() + settings.customer_cache_ttl_seconds
    return customer_id


async def resolve_session(token: str | None, client: WooClient | None = None) -> Session | None:
    """Da token a sessione. `None` se il token manca (utente anonimo, caso legittimo)."""
    if not token:
        return None
    email = verify_token(token)
    customer_id = await resolve_customer_id(email, client)
    if customer_id is None:
        raise SessionError("cliente non trovato")
    return Session(email=email, customer_id=customer_id)
