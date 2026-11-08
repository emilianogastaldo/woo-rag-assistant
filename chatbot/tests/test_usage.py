"""Persistent runtime quotas and provider accounting, with no real network."""
import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from app import agent, main
from app.config import settings
from app.conversations import ConversationError, SQLiteConversationStore
from app.rag.reader import KnowledgeReader
from app.resilience import BudgetExhausted, FailureKind, RecoverableFailure
from app.usage import usage_scope


@pytest.fixture
def store(tmp_path):
    store = SQLiteConversationStore(tmp_path / "chat.sqlite3")
    yield store
    store.close()


def total(store):
    with sqlite3.connect(store.path) as db:
        return db.execute("SELECT COALESCE(SUM(units), 0) FROM daily_usage").fetchone()[0]


def test_daily_reservations_atomic_restart_and_utc_rollover(tmp_path):
    now = [86400]
    path = tmp_path / "chat.sqlite3"
    store = SQLiteConversationStore(path, clock=lambda: now[0])
    def reserve(_):
        try:
            store.reserve_usage(10, 30)
            return True
        except BudgetExhausted:
            return False
    with ThreadPoolExecutor(max_workers=5) as workers:
        assert sum(workers.map(reserve, range(10))) == 3
    assert total(store) == 30
    store.close()
    store = SQLiteConversationStore(path, clock=lambda: now[0])
    try:
        with pytest.raises(BudgetExhausted):
            store.reserve_usage(1, 30)
        now[0] += 86400
        store.reserve_usage(30, 30)
        assert total(store) == 60
    finally:
        store.close()


async def test_retry_reservations_keep_unknown_usage_and_log_only_metadata(store, caplog):
    model = AsyncMock()
    model.ainvoke.side_effect = [
        RecoverableFailure(FailureKind.PROVIDER_UNAVAILABLE, retryable=True),
        AIMessage(content="private answer", usage_metadata={
            "input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
        }),
    ]
    with caplog.at_level("INFO", logger="woo_rag.operations"), usage_scope(store) as usage:
        await agent._invoke_model(model, [HumanMessage(content="secret@example.test")],
                                  token_budget=[100000])
        usage.outcome = "answered"
    assert usage.model_calls == 2 and usage.missing_model_usage == 1
    assert usage.input_tokens == 7 and usage.output_tokens == 3
    assert total(store) == usage.reserved_units > 0
    row = json.loads(caplog.records[-1].message)
    assert row["event"] == "usage" and row["missing_model_usage"] == 1
    assert "private answer" not in caplog.text and "secret@example.test" not in caplog.text


async def test_embedding_units_reserved_before_dispatch_and_missing_usage_explicit(
    store, monkeypatch,
):
    reader = KnowledgeReader()
    embedding = AsyncMock()
    embedding.aembed_query.return_value = [0.1]
    monkeypatch.setattr("app.rag.reader.get_embeddings", lambda: embedding)
    monkeypatch.setattr(reader, "_collection", AsyncMock(return_value="collection"))
    monkeypatch.setattr(reader, "_request", AsyncMock(return_value={
        "documents": [[]], "metadatas": [[]], "distances": [[]],
    }))
    monkeypatch.setattr(settings, "provider_daily_unit_limit", 4)
    with usage_scope(store) as usage:
        assert await reader.asimilarity_search_with_score("€", 1) == []
        with pytest.raises(BudgetExhausted):
            await reader.asimilarity_search_with_score("€", 1)
    assert embedding.aembed_query.await_count == 1
    assert usage.embedding_calls == usage.missing_embedding_usage == 1
    assert usage.reserved_units == total(store) == 3


async def test_concurrent_turns_and_storage_error_fail_before_dispatch(store, monkeypatch):
    monkeypatch.setattr(settings, "provider_daily_unit_limit", 1)
    model = AsyncMock()
    async def turn():
        with usage_scope(store):
            return await agent.answer("ciao", toolset=agent.Toolset(), llm=model)
    replies = await asyncio.gather(turn(), turn())
    assert all(result.reply == agent.FALLBACK_REPLY for result in replies)
    model.ainvoke.assert_not_awaited()
    assert total(store) == 0
    monkeypatch.setattr(settings, "provider_daily_unit_limit", 0)
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER fail_usage BEFORE INSERT ON daily_usage "
                   "BEGIN SELECT RAISE(ABORT, 'private failure'); END")
    with pytest.raises(ConversationError), usage_scope(store):
        await agent.answer("ciao", toolset=agent.Toolset(), llm=model)
    model.ainvoke.assert_not_awaited()


def test_runtime_multiple_turns_missing_usage_and_persistent_cap(store, monkeypatch, caplog):
    monkeypatch.setattr(main.app.state, "conversations", store)
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content="risposta")
    monkeypatch.setattr(agent, "_build_llm", lambda tools: model)
    with caplog.at_level("INFO", logger="woo_rag.operations"):
        client = TestClient(main.app)
        assert client.post("/chat", json={"message": "ciao"}).status_code == 200
        used = total(store)
        monkeypatch.setattr(settings, "provider_daily_unit_limit", used)
        blocked = client.post("/chat", json={"message": "ancora"})
    assert blocked.json()["reply"] == agent.FALLBACK_REPLY
    assert model.ainvoke.await_count == 1 and total(store) == used
    records = [json.loads(r.message) for r in caplog.records]
    usage = [r for r in records if r["event"] == "usage"]
    assert usage[0]["missing_model_usage"] == 1 and usage[0]["outcome"] == "answered"
    assert usage[1]["outcome"] == "daily_limit" and usage[1]["model_calls"] == 0
