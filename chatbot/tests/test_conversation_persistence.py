"""Persistenza e confini della chat dopo riavvio, con rete bloccata da conftest."""

import sqlite3
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent import AgentResult
from app.auth import session as auth
from app.config import settings
from app.conversations import ConversationError, SQLiteConversationStore


def test_restart_preserves_limits_and_discards_uncommitted_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "conversation_capacity", 1)
    monkeypatch.setattr(settings, "conversation_ttl_seconds", 5)
    monkeypatch.setattr(settings, "conversation_max_turns", 2)
    monkeypatch.setattr(settings, "history_max_bytes", 8)
    now = [100]
    path = tmp_path / "chat.sqlite3"
    store = SQLiteConversationStore(path, clock=lambda: now[0])
    row = store.acquire(None, "owner")
    cid = row.id
    store.commit(row, "ciao", "ok")
    expires = row.expires
    # Arresto durante un turno: busy non è uno stato persistente.
    store.close()
    store = SQLiteConversationStore(path, clock=lambda: now[0])
    try:
        with pytest.raises(ConversationError) as error:
            store.acquire(cid, "other")
        assert error.value.status == 404
        with pytest.raises(ConversationError) as error:
            store.acquire(None, "other")
        assert error.value.status == 503
        row = store.acquire(cid, "owner")
        assert [m.content for m in row.history] == ["ciao", "ok"]
        assert row.turns == 1 and row.expires == expires
        with pytest.raises(ConversationError) as error:
            store.acquire(cid, "owner")
        assert error.value.status == 409
        store.commit(row, "€", "sì")
        store.release(row)
    finally:
        store.close()
    store = SQLiteConversationStore(path, clock=lambda: now[0])
    try:
        assert [m.content for m in store.rows[cid].history] == ["€", "sì"]
        with pytest.raises(ConversationError) as error:
            store.acquire(cid, "owner")
        assert error.value.status == 409
        now[0] = expires
        with pytest.raises(ConversationError) as error:
            store.acquire(cid, "owner")
        assert error.value.status == 404
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
        assert store.acquire(None, "other").id != cid
    finally:
        store.close()


def test_single_worker_lock_and_failed_commit_are_safe(tmp_path):
    path = tmp_path / "chat.sqlite3"
    store = SQLiteConversationStore(path)
    try:
        with pytest.raises(BlockingIOError):
            SQLiteConversationStore(path)
        row = store.acquire(None, "owner")
        store.commit(row, "prima", "risposta")
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TRIGGER fail_commit BEFORE INSERT ON conversations
                       BEGIN SELECT RAISE(ABORT, 'synthetic disk failure'); END""")
        with pytest.raises(ConversationError) as error:
            store.commit(row, "perso", "non salvato")
        assert error.value.status == 503
        assert "synthetic" not in error.value.detail
        assert row.turns == 1
        assert [m.content for m in row.history] == ["prima", "risposta"]
    finally:
        store.close()
    store = SQLiteConversationStore(path)
    try:
        assert store.acquire(row.id, "owner").turns == 1
    finally:
        store.close()


@pytest.mark.parametrize("authenticated", [False, True])
def test_chat_followup_after_lifespan_restart(tmp_path, monkeypatch, authenticated):
    path = tmp_path / "chat.sqlite3"
    monkeypatch.setattr(settings, "conversation_db_path", str(path))
    monkeypatch.setattr(auth, "resolve_customer_id", AsyncMock(return_value=101))
    model = AsyncMock(return_value=AgentResult(reply="Risposta sintetica"))
    monkeypatch.setattr(main, "answer", model)
    headers = (
        {"Authorization": "Bearer " + auth.issue_token("a@example.com")} if authenticated else {}
    )
    with TestClient(main.app) as client:
        response = client.post("/chat", json={"message": "Spedite in Italia?"}, headers=headers)
        assert response.status_code == 200
        cid = response.json()["conversation_id"]
        cookies = dict(client.cookies)
    with TestClient(main.app) as client:
        client.cookies.update(cookies)
        response = client.post(
            "/chat", json={"message": "E quanto costa?", "conversation_id": cid}, headers=headers
        )
        assert response.status_code == 200
        assert [m.content for m in model.call_args.kwargs["history"]] == [
            "Spedite in Italia?", "Risposta sintetica"
        ]
        if authenticated:
            headers = {"Authorization": "Bearer " + auth.issue_token("a@example.com")}
        else:
            client.cookies.clear()
        assert client.post(
            "/chat", json={"message": "leggi", "conversation_id": cid}, headers=headers
        ).status_code == 404
        assert model.await_count == 2


def test_commit_error_returns_503_and_releases_conversation(tmp_path, monkeypatch):
    path = tmp_path / "chat.sqlite3"
    monkeypatch.setattr(settings, "conversation_db_path", str(path))
    monkeypatch.setattr(main, "answer", AsyncMock(return_value=AgentResult(reply="ok")))
    with TestClient(main.app) as client:
        cid = client.post("/chat", json={"message": "ciao"}).json()["conversation_id"]
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TRIGGER fail_commit BEFORE INSERT ON conversations
                       BEGIN SELECT RAISE(ABORT, 'synthetic disk failure'); END""")
        response = client.post("/chat", json={"message": "ancora", "conversation_id": cid})
        assert response.status_code == 503
        assert response.json() == {"detail": "Conversazioni temporaneamente non disponibili"}
        row = main.app.state.conversations.rows[cid]
        assert not row.busy and row.turns == 1
