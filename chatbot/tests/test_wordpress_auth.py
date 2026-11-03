"""Synthetic WordPress assertions and real ASGI order isolation; no provider calls."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.agent import AgentResult, build_toolset
from app.auth import session as auth
from app.config import Settings, settings
from app.tools.orders import ORDER_NOT_FOUND, OrderService
from tests.conftest import FakeWooClient, make_order

BRIDGE_SECRET = "synthetic-wordpress-bridge-secret-32chars"


def wp_token(email="a@example.test", sid="a" * 64, expires=None, secret=BRIDGE_SECRET, uid=101):
    payload = json.dumps(
        {"sub": email, "uid": uid, "sid": sid, "exp": expires or int(time.time()) + 30}
    ).encode()
    return "wp." + auth._b64encode(payload) + "." + auth._signature(payload, secret)


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(settings, "wrag_bridge_secret", BRIDGE_SECRET)
    auth._customer_id_cache.clear()
    woo = FakeWooClient({
        "customers": lambda p: [{"id": 101 if p["email"] == "a@example.test" else 102}],
        # Deliberately return both accounts' data: OrderService must filter again.
        "orders": [make_order(21, 101), make_order(22, 102)],
    })
    monkeypatch.setattr(main.app.state, "woo_client", woo, raising=False)
    calls = []

    async def scoped_answer(message, session=None, history=None):
        tools = build_toolset(session)
        names = [tool.name for tool in tools.tools]
        calls.append((session, history, names))
        if session is None:
            assert "stato_ordine" not in names
            return AgentResult(reply="Accedi al negozio")
        service = OrderService(session.customer_id, woo)
        return AgentResult(reply=await service.get_order(int(message)), tools_used=["stato_ordine"])

    monkeypatch.setattr(main, "answer", scoped_answer)
    yield TestClient(main.app), calls, woo
    auth._customer_id_cache.clear()


def test_wp_token_namespace_lifetime_and_config(bridge, monkeypatch):
    from app.privacy import redact

    assert BRIDGE_SECRET not in redact("prefix" + BRIDGE_SECRET + "suffix")
    assert auth.verify_token(wp_token()) == "a@example.test"
    for token in (
        wp_token(secret=settings.session_secret),
        wp_token(sid="client-choice"),
        wp_token(uid=True),
        wp_token(uid=0),
        wp_token(expires=int(time.time()) - 1),
        wp_token(expires=int(time.time()) + 120),
        wp_token()[3:],
    ):
        with pytest.raises(auth.SessionError):
            auth.verify_token(token)
    monkeypatch.setattr(settings, "wrag_bridge_secret", "")
    with pytest.raises(auth.SessionError):
        auth.verify_token(wp_token())
    for secret in ("short", "s" * 32):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, session_secret=secret, wrag_bridge_secret=secret)


def test_wp_session_order_and_conversation_isolation(bridge):
    client, calls, woo = bridge
    def header(token):
        return {"Authorization": "Bearer " + token}
    a = wp_token()
    first = client.post("/chat", json={"message": "21"}, headers=header(a))
    assert first.status_code == 200 and "Ordine #21" in first.json()["reply"]
    cid = first.json()["conversation_id"]
    # Renewing a short assertion keeps history only within the same WP login session.
    renewed = wp_token(expires=int(time.time()) + 40)
    own = client.post(
        "/chat", json={"message": "22", "conversation_id": cid}, headers=header(renewed)
    )
    assert own.status_code == 200 and own.json()["reply"] == ORDER_NOT_FOUND
    assert len(calls[-1][1]) == 2
    assert woo.params_for("orders")["customer"] == 101
    other_customer = wp_token("b@example.test", sid="b" * 64, uid=102)
    other_login = wp_token(sid="c" * 64)
    for token in (other_customer, other_login, None):
        response = client.post("/chat", json={"message": "21", "conversation_id": cid},
                               headers=header(token) if token else {})
        assert response.status_code == 404
    assert len(calls) == 2
    b = client.post("/chat", json={"message": "21"}, headers=header(other_customer))
    assert b.json()["reply"] == ORDER_NOT_FOUND
    assert client.post("/chat", json={"message": "21"}).json()["authenticated"] is False


def test_wp_expiry_and_browser_identity_never_authorize(bridge):
    client, calls, _ = bridge
    expired = wp_token(expires=int(time.time()) - 1)
    assert client.post("/chat", json={"message": "21"},
                       headers={"Authorization": "Bearer " + expired}).status_code == 401
    for identity in ({"customer_id": 101}, {"email": "a@example.test"}):
        assert client.post("/chat", json={"message": "21", **identity}).status_code == 422
    assert calls == []


def test_wp_cached_customer_mapping_must_match_signed_native_user(bridge):
    client, calls, _ = bridge
    auth._customer_id_cache["a@example.test"] = (999, time.monotonic() + 300)
    response = client.post("/chat", json={"message": "21"},
                           headers={"Authorization": "Bearer " + wp_token()})
    assert response.status_code == 401
    assert calls == []
