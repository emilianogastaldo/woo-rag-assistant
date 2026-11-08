"""Idle cleanup and authenticated erasure, without providers or external data."""
import asyncio
import sqlite3
import time
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent import AgentResult
from app.auth import session as auth
from app.config import settings
from app.conversations import ConversationError, SQLiteConversationStore
from tests.test_wordpress_auth import BRIDGE_SECRET, wp_token


def stored_rows(store):
    with sqlite3.connect(store.path) as db:
        return db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "conversation_db_path", str(tmp_path / "chat.sqlite3"))
    monkeypatch.setattr(main, "answer", AsyncMock(return_value=AgentResult(reply="synthetic")))
    monkeypatch.setattr(auth, "resolve_customer_id", AsyncMock(
        side_effect=lambda email, client=None: 101 if email.startswith("a@") else 102,
    ))
    with TestClient(main.app) as client:
        yield client


def test_delete_ownership_idempotency_busy_and_invalid_sessions(client):
    a = {"Authorization": "Bearer " + auth.issue_token("a@example.test")}
    b = {"Authorization": "Bearer " + auth.issue_token("b@example.test")}
    cid = client.post("/chat", json={"message": "private"}, headers=a).json()["conversation_id"]
    store = main.app.state.conversations
    store.rows[cid].busy = True
    assert client.delete("/chat/" + cid, headers=b).status_code == 204
    assert cid in store.rows and stored_rows(store) == 1
    assert client.delete("/chat/" + cid, headers=a).status_code == 409
    store.rows[cid].busy = False
    for headers in ({}, {"Authorization": "Bearer forged"}, {
        "Authorization": "Bearer " + auth.issue_token("a@example.test", ttl_seconds=-1),
    }):
        assert client.delete("/chat/" + cid, headers=headers).status_code == 401
    assert client.delete("/chat/" + cid, headers=a).status_code == 204
    assert client.delete("/chat/" + cid, headers=a).status_code == 204
    assert cid not in store.rows and stored_rows(store) == 0
    assert client.post("/chat", json={"message": "read", "conversation_id": cid},
                       headers=a).status_code == 404
    assert main.answer.await_count == 1


def test_delete_guest_and_wordpress_ownership(client, monkeypatch):
    guest = client.post("/chat", json={"message": "hello"}).json()["conversation_id"]
    # A distinct valid guest session cannot delete the owner's conversation.
    foreign = TestClient(main.app)
    foreign.cookies.set("wrag_guest", auth.issue_token("guest:other"))
    assert foreign.delete("/chat/" + guest).status_code == 204
    assert guest in main.app.state.conversations.rows
    assert client.delete("/chat/" + guest).status_code == 204
    assert stored_rows(main.app.state.conversations) == 0
    monkeypatch.setattr(settings, "wrag_bridge_secret", BRIDGE_SECRET)
    headers = {"Authorization": "Bearer " + wp_token()}
    cid = client.post("/chat", json={"message": "hi"}, headers=headers).json()["conversation_id"]
    other_login = {"Authorization": "Bearer " + wp_token(sid="c" * 64)}
    assert client.delete("/chat/" + cid, headers=other_login).status_code == 204
    assert cid in main.app.state.conversations.rows
    renewed = {"Authorization": "Bearer " + wp_token(expires=int(time.time()) + 40)}
    assert client.delete("/chat/" + cid, headers=renewed).status_code == 204
    assert stored_rows(main.app.state.conversations) == 0


async def test_idle_purge_recovers_from_failure_and_cannot_resurrect_expired_turn(
    tmp_path, monkeypatch, caplog,
):
    now = [100]
    monkeypatch.setattr(settings, "conversation_ttl_seconds", 1)
    monkeypatch.setattr(settings, "conversation_purge_interval_seconds", 0.01)
    store = SQLiteConversationStore(tmp_path / "chat.sqlite3", clock=lambda: now[0])
    row = store.acquire(None, "owner")
    store.commit(row, "old", "answer")
    original = store.purge_expired
    purge_calls = []
    def purge():
        purge_calls.append(1)
        if len(purge_calls) == 1:
            raise ConversationError(503, "private storage message")
        original()
    monkeypatch.setattr(store, "purge_expired", purge)
    now[0] = 102
    task = asyncio.create_task(main.purge_conversations(store))
    try:
        with caplog.at_level("INFO", logger="woo_rag.operations"):
            async with asyncio.timeout(1):
                while stored_rows(store):
                    await asyncio.sleep(0.01)
        assert len(purge_calls) >= 2
        store.commit(row, "late message", "late response")
        store.release(row)
        assert stored_rows(store) == 0 and row.id not in store.rows
        assert "storage_unavailable" in caplog.text
        assert "private storage message" not in caplog.text
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        store.close()


def test_lifespan_runs_idle_purge_and_closes_task(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "conversation_db_path", str(tmp_path / "chat.sqlite3"))
    monkeypatch.setattr(main, "answer", AsyncMock(return_value=AgentResult(reply="synthetic")))
    monkeypatch.setattr(settings, "conversation_purge_interval_seconds", 0.01)
    with TestClient(main.app) as client:
        store = main.app.state.conversations
        cid = client.post("/chat", json={"message": "hello"}).json()["conversation_id"]
        store.clock = lambda: time.time() + settings.conversation_ttl_seconds + 1
        deadline = time.monotonic() + 1
        while cid in store.rows and time.monotonic() < deadline:
            time.sleep(0.01)
        assert cid not in store.rows and stored_rows(store) == 0
    assert store._lock is None


def test_failed_delete_preserves_committed_conversation(tmp_path):
    store = SQLiteConversationStore(tmp_path / "chat.sqlite3")
    try:
        row = store.acquire(None, "owner")
        store.commit(row, "message", "reply")
        store.release(row)
        with sqlite3.connect(store.path) as db:
            db.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON conversations "
                       "BEGIN SELECT RAISE(ABORT, 'storage error'); END")
        with pytest.raises(ConversationError):
            store.delete(row.id, "owner")
        assert row.id in store.rows and stored_rows(store) == 1
    finally:
        store.close()
