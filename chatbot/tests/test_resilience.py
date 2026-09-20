"""Failure taxonomy, bounded retry budget and redacted observability."""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from app import main
from app.agent import FALLBACK_REPLY, UNCITED_REPLY, answer
from app.config import RetrievalConfig, settings
from app.observability import correlation
from app.rag.chain import NO_RESULTS, KnowledgeBase, RetrievalResult
from app.resilience import (
    AttemptBudget,
    BudgetExhausted,
    FailureKind,
    RecoverableFailure,
    budget_scope,
    retry_call,
)
from app.tools.woo_client import WooClient
from tests.test_agent import FakeKnowledgeBase, FakeLLM, anon_toolset


class EmptyStore:
    async def asimilarity_search_with_score(self, query, k=4):
        return []


class InspectingLLM:
    def __init__(self, calls):
        self.calls = list(calls)
        self.seen = []

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        return self.calls.pop(0)


def tool_call(name, args, identifier):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": identifier}],
    )


async def test_missing_and_invalid_tool_arguments_become_useful_tool_output():
    llm = InspectingLLM([
        tool_call("verifica_disponibilita_prodotto", {}, "missing"),
        AIMessage(content="Correggi la richiesta."),
    ])
    result = await answer("stock?", toolset=anon_toolset(), llm=llm)
    tool_message = next(message for message in llm.seen[1] if isinstance(message, ToolMessage))
    assert "mancanti o non validi" in tool_message.content
    assert result.reply == "Correggi la richiesta."


async def test_unknown_tool_is_reported_without_execution():
    llm = InspectingLLM([
        tool_call("tool_inventato", {"secret": "do-not-log"}, "unknown"),
        AIMessage(content="Strumento non disponibile."),
    ])
    result = await answer("prova", toolset=anon_toolset(), llm=llm)
    tool_message = next(message for message in llm.seen[1] if isinstance(message, ToolMessage))
    assert json.loads(tool_message.content)["untrusted_data"] == (
        "Strumento non disponibile per questa conversazione."
    )
    assert result.tools_used == []


@pytest.mark.parametrize(
    ("status", "kind", "requests"),
    [(400, FailureKind.HTTP_CLIENT, 1), (503, FailureKind.HTTP_SERVER, 2),
     (429, FailureKind.RATE_LIMIT, 2)],
)
async def test_http_status_taxonomy_and_retry_exhaustion(status, kind, requests):
    seen = 0

    def handler(request):
        nonlocal seen
        seen += 1
        return httpx.Response(status, headers={"Retry-After": "0"})

    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    woo = WooClient(
        base_url="http://woo.invalid",
        consumer_key="synthetic",
        consumer_secret="synthetic",
        retry_attempts=1,
        client=transport_client,
    )
    with pytest.raises(RecoverableFailure) as raised:
        await woo.get_json("products")
    assert raised.value.kind == kind
    assert seen == requests
    await transport_client.aclose()


async def test_timeout_and_malformed_json_are_distinct():
    def timeout_handler(request):
        raise httpx.ReadTimeout("hidden", request=request)

    timeout_http = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    woo = WooClient(base_url="http://woo.invalid", retry_attempts=0, client=timeout_http)
    with pytest.raises(RecoverableFailure) as timeout:
        await woo.get_json("products")
    assert timeout.value.kind == FailureKind.TIMEOUT
    await timeout_http.aclose()

    malformed_http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"{"))
    )
    woo = WooClient(base_url="http://woo.invalid", retry_attempts=1, client=malformed_http)
    with pytest.raises(RecoverableFailure) as malformed:
        await woo.get_json("products")
    assert malformed.value.kind == FailureKind.MALFORMED_RESPONSE
    await malformed_http.aclose()


async def test_retry_can_recover_and_client_is_reused_then_closed():
    seen = 0

    def handler(request):
        nonlocal seen
        seen += 1
        if seen == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=[])

    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    woo = WooClient(base_url="http://woo.invalid", retry_attempts=1, client=transport_client)
    assert await woo.get_json("products") == []
    assert await woo.get_json("orders") == []
    assert seen == 3
    assert not transport_client.is_closed
    await transport_client.aclose()
    assert transport_client.is_closed


async def test_retrieval_retry_and_http_retry_share_one_budget():
    budget = AttemptBudget(max_attempts=10, max_retries=1, deadline_seconds=5)
    kb = KnowledgeBase(
        EmptyStore(),
        config=RetrievalConfig(strategy="semantic", retry_attempts=1),
    )
    seen = 0

    def handler(request):
        nonlocal seen
        seen += 1
        return httpx.Response(503)

    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    woo = WooClient(base_url="http://woo.invalid", retry_attempts=1, client=transport_client)
    with budget_scope(budget):
        result = await kb.search("Vorrei restituire")
        assert len(result.attempts) == 2
        with pytest.raises(BudgetExhausted):
            await woo.get_json("products")
    assert budget.retries == 1
    assert seen == 1
    await transport_client.aclose()


async def test_chroma_unavailable_is_not_reported_as_no_results():
    class BrokenKnowledgeBase:
        async def search(self, query, k=None):
            raise RecoverableFailure(FailureKind.CHROMA_UNAVAILABLE)

    llm = InspectingLLM([
        tool_call("cerca_informazioni_negozio", {"domanda": "resi"}, "rag"),
        AIMessage(content="La knowledge base non e disponibile."),
    ])
    result = await answer(
        "resi",
        toolset=anon_toolset(knowledge_base=BrokenKnowledgeBase()),
        llm=llm,
    )
    tool_message = next(message for message in llm.seen[1] if isinstance(message, ToolMessage))
    assert "temporaneamente non disponibile" in tool_message.content
    assert NO_RESULTS not in tool_message.content
    assert result.reply == FALLBACK_REPLY


async def test_no_results_keeps_the_abstention_contract():
    kb = FakeKnowledgeBase(RetrievalResult(context=NO_RESULTS))
    llm = FakeLLM(
        tool_call("cerca_informazioni_negozio", {"domanda": "meteoriti"}, "rag"),
        AIMessage(content="Non lo so, contatta l'assistenza."),
    )
    result = await answer("meteoriti", toolset=anon_toolset(knowledge_base=kb), llm=llm)
    assert result.reply == UNCITED_REPLY


async def test_model_error_retry_exhaustion_returns_stable_fallback():
    class BrokenModel:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            raise RecoverableFailure(FailureKind.PROVIDER_UNAVAILABLE, retryable=True)

    model = BrokenModel()
    result = await answer("ciao", toolset=anon_toolset(), llm=model)
    assert result.reply == FALLBACK_REPLY
    assert model.calls == settings.provider_retry_attempts + 1


async def test_repeated_tool_error_and_max_steps_stop_the_loop(monkeypatch):
    repeated = FakeLLM(
        tool_call("tool_inventato", {}, "one"),
        tool_call("tool_inventato", {}, "two"),
        AIMessage(content="non raggiunta"),
    )
    result = await answer("prova", toolset=anon_toolset(), llm=repeated)
    assert result.reply == FALLBACK_REPLY
    assert len(repeated.seen) == settings.agent_max_repeated_errors

    monkeypatch.setattr(settings, "agent_max_steps", 2)
    looping = FakeLLM(
        tool_call("verifica_disponibilita_prodotto", {"prodotto": "A"}, "one"),
        tool_call("verifica_disponibilita_prodotto", {"prodotto": "B"}, "two"),
    )
    result = await answer(
        "stock", toolset=anon_toolset(), llm=looping
    )
    assert result.reply == FALLBACK_REPLY
    assert len(looping.seen) == 2


async def test_attempt_budget_stops_before_an_extra_model_call():
    model = FakeLLM(
        tool_call("verifica_disponibilita_prodotto", {"prodotto": "A"}, "one"),
        AIMessage(content="non raggiunta"),
    )
    budget = AttemptBudget(max_attempts=1, max_retries=0, deadline_seconds=5)
    result = await answer("stock", toolset=anon_toolset(), llm=model, budget=budget)
    assert result.reply == FALLBACK_REPLY
    assert len(model.seen) == 1


async def test_structured_logs_contain_ids_but_not_secrets(caplog):
    secret = "consumer-secret-never-log"
    transport_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    woo = WooClient(
        base_url="http://woo.invalid",
        consumer_key="key-never-log",
        consumer_secret=secret,
        retry_attempts=0,
        client=transport_client,
    )
    with caplog.at_level(logging.INFO, logger="woo_rag.operations"):
        with correlation("req-123", "conv-456"):
            with pytest.raises(RecoverableFailure):
                await woo.get_json("products", {"search": "private-query"})
    payload = json.loads(caplog.records[-1].message)
    assert payload["request_id"] == "req-123"
    assert payload["conversation_id"] == "conv-456"
    joined = " ".join(record.message for record in caplog.records)
    assert secret not in joined and "private-query" not in joined and "key-never-log" not in joined
    await transport_client.aclose()


def test_endpoint_uses_stable_503_and_request_id_for_session_dependency(monkeypatch):
    async def unavailable(token, client=None):
        raise RecoverableFailure(FailureKind.HTTP_SERVER)

    monkeypatch.setattr(main, "resolve_session", unavailable)
    response = TestClient(main.app).post(
        "/chat",
        json={"message": "ordine"},
        headers={"Authorization": "Bearer valid-looking", "X-Request-ID": "req-test"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": FALLBACK_REPLY}
    assert response.headers["X-Request-ID"] != "req-test"
    assert "Traceback" not in response.text


def test_application_lifespan_closes_owned_http_clients():
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        woo_http = main.app.state.woo_client._client
        provider_http = main.app.state.provider_http_client
        assert not woo_http.is_closed and not provider_http.is_closed
    assert woo_http.is_closed and provider_http.is_closed


async def test_deadline_cancels_tool_and_programming_errors_propagate():
    from langchain_core.tools import StructuredTool

    from app.agent import Toolset

    cancelled = asyncio.Event()

    async def hanging():
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    tool = StructuredTool.from_function(coroutine=hanging, name="hang", description="test")
    result = await answer("x", toolset=Toolset(tools=[tool]),
                          llm=FakeLLM(tool_call("hang", {}, "x")),
                          budget=AttemptBudget(10, 2, .02))
    assert result.reply == FALLBACK_REPLY and cancelled.is_set()

    async def broken():
        raise TypeError("programming bug")

    tool = StructuredTool.from_function(coroutine=broken, name="broken", description="test")
    with pytest.raises(TypeError, match="programming bug"):
        await answer("x", toolset=Toolset(tools=[tool]),
                     llm=FakeLLM(tool_call("broken", {}, "x")))


async def test_retry_after_deadline_and_non_idempotent_operations():
    count = 0

    async def fail():
        nonlocal count
        count += 1
        raise RecoverableFailure(FailureKind.RATE_LIMIT, retryable=True, retry_after=10)

    with pytest.raises(BudgetExhausted):
        await retry_call("test", fail, max_retries=2, timeout_seconds=1, idempotent=True,
                         budget=AttemptBudget(10, 2, .02))
    assert count == 1
    with pytest.raises(RecoverableFailure):
        await retry_call("test", fail, max_retries=2, timeout_seconds=1, idempotent=False)
    assert count == 2


async def test_many_tool_calls_cannot_bypass_budget_or_log_untrusted_names(caplog):
    from app.agent import Toolset

    message = AIMessage(content="", tool_calls=[
        {"name": "sensitive-secret", "args": {}, "id": str(i)} for i in range(100)
    ])
    with caplog.at_level(logging.INFO, logger="woo_rag.operations"):
        result = await answer("x", toolset=Toolset(), llm=FakeLLM(message),
                              budget=AttemptBudget(2, 0, 1))
    assert result.reply == FALLBACK_REPLY
    assert "sensitive-secret" not in caplog.text
