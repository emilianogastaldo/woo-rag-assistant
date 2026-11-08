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
from app.conversations import MemoryRateLimiter
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


def visitor_assertion(subject="guest:" + "a" * 64, expires=None, secret=BRIDGE_SECRET):
    payload = json.dumps({"sub": subject, "exp": int(time.time()) + 30
                          if expires is None else expires}).encode()
    return auth._b64encode(payload) + "." + auth._signature(b"rate-limit:" + payload, secret)


@pytest.mark.parametrize("authenticated", [False, True])
def test_bridge_visitors_have_independent_quotas(bridge, monkeypatch, authenticated):
    client, calls, _ = bridge
    monkeypatch.setattr(settings, "rate_limit_requests", 1)
    prefix = "auth:" if authenticated else "guest:"
    a = {"X-WRAG-Visitor": visitor_assertion(prefix + "a" * 64)}
    b = {"X-WRAG-Visitor": visitor_assertion(prefix + "b" * 64)}
    if authenticated:
        a["Authorization"] = "Bearer " + wp_token()
        b["Authorization"] = "Bearer " + wp_token("b@example.test", uid=102, sid="b" * 64)
    assert client.post("/chat", json={"message": "21"}, headers=a).status_code == 200
    blocked = client.post("/chat", json={"message": "21"}, headers=a)
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    assert client.post("/chat", json={"message": "22"}, headers=b).status_code == 200
    assert len(calls) == 2
    # Switching to guest/auth changes quota only; an assertion does not grant login.
    other = {"X-WRAG-Visitor": visitor_assertion(
        ("guest:" if authenticated else "auth:") + "a" * 64
    )}
    response = client.post("/chat", json={"message": "21"}, headers=other)
    assert response.status_code == 200 and response.json()["authenticated"] is False


def test_global_cap_covers_bridge_and_direct_requests_and_resets(bridge, monkeypatch):
    client, calls, _ = bridge
    monkeypatch.setattr(settings, "rate_limit_global_requests", 2)
    now = [0]
    main.app.state.global_rate_limiter = MemoryRateLimiter(clock=lambda: now[0])
    assert client.post("/chat", json={"message": "21"}).status_code == 200
    headers = {"X-WRAG-Visitor": visitor_assertion()}
    assert client.post("/chat", json={"message": "21"}, headers=headers).status_code == 200
    headers["X-WRAG-Visitor"] = visitor_assertion("guest:" + "b" * 64)
    response = client.post("/chat", json={"message": "21"}, headers=headers)
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    assert len(calls) == 2
    now[0] = settings.rate_limit_window_seconds + 1
    assert client.post("/chat", json={"message": "21"}, headers=headers).status_code == 200


@pytest.mark.parametrize("expires", [0, True, "later", None, 999999999999])
def test_invalid_visitor_expiry_rejected(bridge, expires):
    # Construct None literally rather than use the helper's default expiry.
    payload = json.dumps({"sub": "guest:" + "a" * 64, "exp": expires}).encode()
    assertion = auth._b64encode(payload) + "." + auth._signature(
        b"rate-limit:" + payload, BRIDGE_SECRET
    )
    with pytest.raises(auth.SessionError):
        auth.bridge_rate_identity(assertion)


def test_visitor_assertion_signature_subject_and_namespace(bridge, monkeypatch):
    assertion = visitor_assertion()
    assert auth.bridge_rate_identity(assertion) == "guest:" + "a" * 64
    for invalid in (
        "", "x" * 513, "garbage", assertion + "x",
        visitor_assertion(secret=settings.session_secret),
        visitor_assertion(subject="client-choice"),
        visitor_assertion(subject="auth:101"),
        wp_token(), wp_token()[3:], auth.issue_token("a@example.test"),
    ):
        with pytest.raises(auth.SessionError):
            auth.bridge_rate_identity(invalid)
    for token in (assertion, "wp." + assertion):
        with pytest.raises(auth.SessionError):
            auth.verify_token(token)
    monkeypatch.setattr(settings, "wrag_bridge_secret", "")
    with pytest.raises(auth.SessionError):
        auth.bridge_rate_identity(assertion)


def test_forged_assertions_and_forwarded_ips_share_direct_quota(bridge, monkeypatch):
    client, calls, _ = bridge
    monkeypatch.setattr(settings, "rate_limit_requests", 2)
    for suffix in ("a", "b"):
        response = client.post("/chat", json={"message": "21"}, headers={
            "X-WRAG-Visitor": "forged-" + suffix, "X-Forwarded-For": "192.0.2." + suffix,
        })
        assert response.status_code == 401
    assert client.post("/chat", json={"message": "21"}).status_code == 429
    # A valid bridge request is separate from the exhausted direct-peer quota.
    response = client.post("/chat", json={"message": "21"},
                           headers={"X-WRAG-Visitor": visitor_assertion()})
    assert response.status_code == 200 and len(calls) == 1


def test_invalid_bodies_consume_the_attested_quota(bridge, monkeypatch):
    client, calls, _ = bridge
    monkeypatch.setattr(settings, "rate_limit_requests", 1)
    headers = {"X-WRAG-Visitor": visitor_assertion()}
    assert client.post("/chat", content="not-json", headers=headers).status_code == 422
    assert client.post("/chat", json={"message": "21"}, headers=headers).status_code == 429
    assert calls == []
