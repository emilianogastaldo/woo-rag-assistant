"""Endpoint HTTP: sessione dall'header, login demo, propagazione delle fonti."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent import AgentResult
from app.auth.session import Session, issue_token


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture
def stub_answer(monkeypatch):
    calls: list[dict] = []

    async def fake_answer(message, session=None, history=None, toolset=None, llm=None):
        calls.append({"message": message, "session": session, "history": history or []})
        return AgentResult(
            reply="risposta",
            sources=[{"title": "Spedizioni", "url": "http://x", "type": "page"}],
            tools_used=["cerca_informazioni_negozio"],
        )

    monkeypatch.setattr(main, "answer", fake_answer)
    return calls


def test_health(client: TestClient):
    assert client.get("/health").json() == {"status": "ok"}


def test_login_demo_emette_un_token(client: TestClient):
    body = client.post("/demo/login", json={"customer": "A"}).json()
    assert body["email"] == "mario.rossi@example.com"
    assert body["token"].count(".") == 1


def test_login_demo_cliente_sconosciuto(client: TestClient):
    assert client.post("/demo/login", json={"customer": "Z"}).status_code == 404


def test_chat_anonima_non_ha_sessione(client: TestClient, stub_answer):
    response = client.post("/chat", json={"message": "quanto costa la spedizione?"})
    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["sources"][0]["title"] == "Spedizioni"
    assert stub_answer[0]["session"] is None


def test_chat_autenticata_risolve_la_sessione_server_side(
    client: TestClient, stub_answer, monkeypatch
):
    async def fake_resolve(token, client=None):
        assert token == "token-valido"
        return Session(email="mario.rossi@example.com", customer_id=12)

    monkeypatch.setattr(main, "resolve_session", fake_resolve)
    response = client.post(
        "/chat",
        json={"message": "a che punto è l'ordine 22?"},
        headers={"Authorization": "Bearer token-valido"},
    )
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert stub_answer[0]["session"].customer_id == 12


def test_token_non_valido_restituisce_401(client: TestClient, stub_answer):
    response = client.post(
        "/chat",
        json={"message": "ciao"},
        headers={"Authorization": "Bearer token-falsificato"},
    )
    assert response.status_code == 401
    assert stub_answer == []


def test_token_scaduto_restituisce_401(client: TestClient, stub_answer):
    scaduto = issue_token("mario.rossi@example.com", ttl_seconds=-10)
    response = client.post(
        "/chat", json={"message": "ciao"}, headers={"Authorization": f"Bearer {scaduto}"}
    )
    assert response.status_code == 401


def test_il_customer_id_nel_payload_viene_ignorato(client: TestClient, stub_answer):
    """Il body non è una fonte di identità: campi extra non passano."""
    response = client.post("/chat", json={"message": "ciao", "customer_id": 13})
    assert response.status_code == 200
    assert stub_answer[0]["session"] is None


def test_storia_convertita_in_messaggi(client: TestClient, stub_answer):
    client.post(
        "/chat",
        json={
            "message": "e per i resi?",
            "history": [
                {"role": "user", "content": "quanto costa la spedizione?"},
                {"role": "assistant", "content": "4,90 €"},
            ],
        },
    )
    history = stub_answer[0]["history"]
    assert [m.type for m in history] == ["human", "ai"]


def test_messaggio_vuoto_rifiutato(client: TestClient, stub_answer):
    assert client.post("/chat", json={"message": ""}).status_code == 422
