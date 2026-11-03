"""Preflight, usage e scenari live verificati con soli provider sintetici."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from evals.costs import EMBEDDING_INPUT_MAX_BYTES, measured_cost
from evals.fixtures import ScriptedLLM
from evals.live import MeasuredEmbeddings, MeasuredModel
from evals.metrics import aggregate, load_cases
from evals.run_agent_eval import HERE, estimate, evaluate, main
from langchain_core.messages import AIMessage

from app.config import settings

EXTRA = HERE / "issue17.jsonl"


async def test_original_and_contextual_cases_pass_offline_without_network():
    cases = load_cases(HERE / "golden.jsonl") + load_cases(EXTRA)
    report = await evaluate(cases, repeats=3)
    assert len(report["rows"]) == 102
    assert all(row["passed"] for row in report["rows"])
    assert report["cost"] is None


async def test_history_reaches_model_without_being_added_to_report(monkeypatch):
    original = ScriptedLLM.ainvoke
    seen = []

    async def recording(self, messages):
        seen.extend(str(message.content) for message in messages)
        return await original(self, messages)

    monkeypatch.setattr(ScriptedLLM, "ainvoke", recording)
    case = load_cases(EXTRA)[1]
    report = await evaluate([case])
    assert all(turn.content in seen for turn in case.history)
    serialized = json.dumps(report)
    assert all(turn.content not in serialized for turn in case.history)


def test_smoke_and_baseline_preflight_are_conservative(monkeypatch):
    monkeypatch.setattr(settings, "openai_model", "gpt-4.1-mini")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-3-small")
    smoke = estimate(6, 1, 4)
    assert smoke["generation_requests_max"] == 36
    assert smoke["embedding_requests_max"] == 73
    assert smoke["generation_input_tokens_max"] == 600000
    assert 0.28 < smoke["estimated_usd_max"] < 0.30
    assert smoke["provider_work_seconds_max"] == 210
    assert 4.7 < estimate(34, 3, 4)["estimated_usd_max"] < 5
    monkeypatch.setattr(settings, "model_max_output_tokens", 1024)
    assert estimate(6, 1, 4)["generation_output_tokens_max"] == 36864
    monkeypatch.setattr(settings, "openai_model", "unknown-model")
    assert estimate(6, 1, 4)["estimated_usd_max"] is None


@pytest.mark.parametrize("ceiling", [None, 0.01, -1, float("nan"), float("inf")])
async def test_cost_preflight_rejects_before_constructing_provider(monkeypatch, ceiling):
    def forbidden():
        pytest.fail("provider must not be constructed")

    monkeypatch.setattr("evals.live.prepare_store", forbidden)
    with pytest.raises(ValueError, match="budget"):
        await evaluate(load_cases(EXTRA), live=True, allow_external=True,
                       max_estimated_usd=ceiling)


async def test_live_setup_has_its_own_deadline(monkeypatch):
    async def stalled_setup():
        await asyncio.sleep(1)

    monkeypatch.setattr("evals.live.prepare_store", stalled_setup)
    monkeypatch.setattr("evals.run_agent_eval.SETUP_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(TimeoutError):
        await evaluate(load_cases(EXTRA)[:1], live=True, allow_external=True,
                       max_estimated_usd=0.30)


def test_cli_filters_appends_and_requires_live_cost_consent(tmp_path, capsys):
    assert main(["--extra-golden", str(EXTRA), "--case", "followup-order", "--estimate"]) == 0
    assert json.loads(capsys.readouterr().out)["cases"] == 1
    with pytest.raises(SystemExit):
        main(["--live", "--allow-external"])
    assert main(["--extra-golden", str(HERE / "golden.jsonl"), "--estimate"]) == 2
    assert main(["--case", "missing", "--estimate"]) == 2
    output = tmp_path / "offline.json"
    assert main(["--extra-golden", str(EXTRA), "--case", "ambiguous-request",
                 "--output", str(output)]) == 0
    assert json.loads(output.read_text())["rows"][0]["passed"]


async def test_embedding_usage_counts_batch_and_queries_without_payloads(monkeypatch):
    client = SimpleNamespace(
        embeddings=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(
            usage=SimpleNamespace(total_tokens=7),
            data=[SimpleNamespace(index=0, embedding=[1.0, 0.0])],
        ))), close=AsyncMock(),
    )
    monkeypatch.setattr("evals.live.AsyncOpenAI", lambda **kwargs: client)
    embeddings = MeasuredEmbeddings()
    assert await embeddings.aembed_query("sintetico") == [1.0, 0.0]
    assert embeddings.input_tokens == 7
    assert embeddings.requests_without_usage == 0
    with pytest.raises(ValueError, match="limit"):
        await embeddings.aembed_query("à" * EMBEDDING_INPUT_MAX_BYTES)
    assert client.embeddings.create.await_count == 1
    client.embeddings.create.side_effect = TimeoutError("SECRET")
    with pytest.raises(TimeoutError):
        await embeddings.aembed_query("sintetico")
    assert embeddings.requests_without_usage == 1
    await embeddings.aclose()
    client.close.assert_awaited_once()


async def test_generation_unknown_usage_is_reported_separately():
    model = MeasuredModel(SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(
        content="sintetico", usage_metadata={
            "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
        },
    ))))
    await model.ainvoke([])
    assert model.requests_without_usage == 0
    model.model.ainvoke.return_value = AIMessage(content="usage assente")
    await model.ainvoke([])
    assert model.requests_without_usage == 1
    rows = [{"metrics": {"input_tokens": 10, "output_tokens": 5}}]
    cost = measured_cost(rows, SimpleNamespace(embeddings=SimpleNamespace(input_tokens=7)),
                         model.requests_without_usage)
    assert cost["embedding_input_tokens"] == 7
    assert cost["requests_without_usage"] == 1
    assert cost["usage_complete"] is False
    assert cost["billing_cap"] is False


def test_latency_percentiles_use_all_runs_including_failed_rows():
    from evals.metrics import COUNTERS, QUALITY

    rows = [{"passed": i != 20, "metrics": {
        **dict.fromkeys((*QUALITY, *COUNTERS), 0), "latency_ms": i,
    }} for i in range(1, 21)]
    latency = aggregate(rows)["latency_ms"]
    assert latency == {"mean": 10.5, "n": 20, "p50": 10.5, "p95": 19, "max": 20}
