"""Sessione: firma, scadenza e risoluzione del customer ID."""
from __future__ import annotations

import pytest

from app.auth import session as session_module
from app.auth.session import (
    Session,
    SessionError,
    issue_token,
    resolve_session,
    verify_token,
)
from tests.conftest import FakeWooClient


@pytest.fixture(autouse=True)
def _clear_cache():
    session_module._customer_id_cache.clear()
    yield
    session_module._customer_id_cache.clear()


def test_token_roundtrip():
    token = issue_token("mario.rossi@example.com")
    assert verify_token(token) == "mario.rossi@example.com"


def test_token_con_firma_manomessa_viene_rifiutato():
    payload, _, _signature = issue_token("mario.rossi@example.com").partition(".")
    forged = issue_token("luigi.verdi@example.com").split(".")[1]
    with pytest.raises(SessionError):
        verify_token(f"{payload}.{forged}")


def test_payload_modificato_viene_rifiutato():
    """Cambiare l'identità nel payload invalida la firma: niente impersonificazione."""
    import base64
    import json

    token = issue_token("mario.rossi@example.com")
    _, _, signature = token.partition(".")
    tampered_payload = json.dumps({"sub": "luigi.verdi@example.com", "exp": 9999999999})
    encoded = base64.urlsafe_b64encode(tampered_payload.encode()).decode().rstrip("=")
    with pytest.raises(SessionError):
        verify_token(f"{encoded}.{signature}")


def test_token_scaduto():
    with pytest.raises(SessionError, match="scaduta"):
        verify_token(issue_token("mario.rossi@example.com", ttl_seconds=-10))


def test_token_malformato():
    with pytest.raises(SessionError):
        verify_token("non-un-token")


async def test_sessione_assente_per_utente_anonimo():
    assert await resolve_session(None) is None
    assert await resolve_session("") is None


async def test_resolve_session_risolve_il_customer_id():
    woo = FakeWooClient({"customers": [{"id": 12, "email": "mario.rossi@example.com"}]})
    result = await resolve_session(issue_token("mario.rossi@example.com"), client=woo)
    assert result == Session(email="mario.rossi@example.com", customer_id=12)
    assert woo.params_for("customers")["email"] == "mario.rossi@example.com"


async def test_email_sconosciuta_non_produce_sessione():
    woo = FakeWooClient({"customers": []})
    with pytest.raises(SessionError):
        await resolve_session(issue_token("ignoto@example.com"), client=woo)
