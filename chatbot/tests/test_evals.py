"""Regressioni del loop e sensibilità delle metriche, senza rete né judge LLM."""

import copy
import json
import socket
import sys
from dataclasses import replace

import pytest
from evals.fixtures import PLANS, RAG, FakeStore, FakeWoo, ScriptedLLM
from evals.metrics import RecordingStore, compare, load_cases, score
from evals.run_agent_eval import HERE, estimate, evaluate, main
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.agent import AgentResult, AgentTrace, answer, build_toolset
from app.config import settings
from app.rag.chain import KnowledgeBase
from app.rag.chunks import split_documents
from app.tools.catalog import CatalogService

CASES = load_cases(HERE / "golden.jsonl")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
async def test_golden_agent_loop(case):
    report = await evaluate([case])
    row = report["rows"][0]
    assert row["passed"], row
    assert row["metrics"]["llm_calls"] == (2 if PLANS[case.id] else 1)
    assert row["metrics"]["tool_calls"] == len(PLANS[case.id])
    assert row["metrics"]["unavailable_tool_calls"] == (case.id == "adv-unavailable")
    assert report["embedding_calls"] == 0


def test_network_guard_blocks_dns_and_connections():
    with pytest.raises(RuntimeError, match="network disabled"):
        socket.getaddrinfo("example.invalid", 443)
    with socket.socket() as sock, pytest.raises(RuntimeError, match="network disabled"):
        sock.connect(("127.0.0.1", 9))


async def test_live_requires_consent_even_in_python_api():
    with pytest.raises(ValueError, match="allow-external"):
        await evaluate(CASES, live=True)


def test_cli_opt_in_and_estimate_do_not_construct_clients(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("evaluation must not start")

    monkeypatch.setattr("evals.run_agent_eval.evaluate", forbidden)
    with pytest.raises(SystemExit) as exc:
        main(["--live"])
    assert exc.value.code == 2
    assert main(["--live", "--estimate", "--repeats", "3"]) == 0
    text = capsys.readouterr().out
    assert json.loads(text)["generation_requests_max"] == 360
    with pytest.raises(SystemExit):
        main(["--repeats", "0"])


async def test_repetitions_have_identical_quality_and_counts():
    report = await evaluate(CASES, repeats=2)
    for i in range(0, len(report["rows"]), 2):
        first, second = copy.deepcopy(report["rows"][i : i + 2])
        for row in (first, second):
            row.pop("repeat")
            row["metrics"].pop("latency_ms")
        assert first == second


def sample_score(reply=None, tools=None, sources=None):
    case = CASES[0]
    retrieval = RecordingStore(None)
    doc = split_documents([Document(
        page_content="fixture",
        metadata={
            "title": "Spedizioni",
            "source": "https://demo.invalid/shipping",
            "type": "page",
        },
    )])[0]
    identifier = doc.metadata["chunk_id"]
    irrelevant = Document(page_content="altro", metadata={"title": "Altro", "source": "other"})
    retrieval.results = [[(irrelevant, 0.1), (doc, 0.2)]]
    result = AgentResult(
        reply=(f"La spedizione costa 4,90 € sotto i 49 €. [{identifier}]"
               if reply is None else reply),
        tools_used=[RAG] if tools is None else tools,
        sources=[{
            "title": "Spedizioni", "url": "https://demo.invalid/shipping", "type": "page",
            "chunk_ids": [identifier],
        }]
        if sources is None
        else sources,
    )
    return score(case, result, retrieval, AgentTrace(llm_calls=2), 0, 1.0)


def test_metrics_detect_wrong_route_answer_citations_and_rank():
    good = sample_score()
    assert good["passed"]
    assert good["metrics"]["mrr"] == 0.5
    assert good["metrics"]["hit_at_k"] == 1
    bad = sample_score(
        reply="Gratis per tutti",
        tools=[],
        sources=[
            {"title": "Spedizioni", "url": "https://demo.invalid/shipping"},
            {"title": "Inventata", "url": "https://demo.invalid/fake"},
        ],
    )
    assert not bad["passed"]
    assert bad["metrics"]["routing_accuracy"] == 0
    assert bad["metrics"]["answer_correct"] == 0
    assert bad["metrics"]["citation_precision"] == 0
    assert bad["metrics"]["citation_validity"] == 0
    assert sample_score(sources=[])["metrics"]["citation_recall"] == 0


async def test_changed_expectations_fail_instead_of_teaching_fake_model():
    case = CASES[0].model_copy(update={"answer_all": ["99,99"], "expected_source": "Inventata"})
    row = (await evaluate([case]))["rows"][0]
    assert row["metrics"]["answer_correct"] == 0
    assert row["metrics"]["hit_at_k"] == 0
    assert row["metrics"]["citation_precision"] == 0
    assert not row["passed"]


async def test_empty_retrieval_and_loop_exhaustion_fail_expected_answer(monkeypatch):
    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr(FakeStore, "asimilarity_search_with_score", empty)
    row = (await evaluate([CASES[0]]))["rows"][0]
    assert not row["passed"]
    assert row["metrics"]["hit_at_k"] == 0
    monkeypatch.setattr(settings, "agent_max_steps", 1)
    row = (await evaluate([CASES[0]]))["rows"][0]
    assert not row["passed"]
    assert row["metrics"]["llm_calls"] == 1


@pytest.mark.parametrize("replacement", ["", "[chunk-inventato]"])
async def test_eval_detects_missing_or_fabricated_text_citations(monkeypatch, replacement):
    import re

    original = ScriptedLLM.ainvoke

    async def omit(self, messages):
        result = await original(self, messages)
        if not result.tool_calls:
            result.content = re.sub(r"\[chunk-[^\]]+\]", replacement, result.content)
        return result

    monkeypatch.setattr(ScriptedLLM, "ainvoke", omit)
    row = (await evaluate([CASES[0]]))["rows"][0]
    assert not row["passed"]
    assert row["metrics"]["hit_at_k"] == 1
    assert row["metrics"]["citation_recall"] == 0
    assert row["metrics"]["citation_validity"] == 0


def test_eval_rejects_sources_without_explicit_citations_and_unattributed_ids():
    assert sample_score(reply="4,90 € sotto 49 €")["metrics"]["citation_validity"] == 0
    assert sample_score(sources=[])["metrics"]["citation_validity"] == 0


async def test_eval_detects_extra_retrieved_but_uncited_source(monkeypatch):
    from evals import run_agent_eval

    original = run_agent_eval.answer

    async def append_source(*args, **kwargs):
        result = await original(*args, **kwargs)
        result.sources.append({
            "title": "Resi e Rimborsi", "url": "https://demo.invalid/docs/1", "type": "page",
            "chunk_ids": ["chunk-inventato"],
        })
        return result

    monkeypatch.setattr(run_agent_eval, "answer", append_source)
    row = (await evaluate([CASES[0]]))["rows"][0]
    assert row["metrics"]["citation_precision"] == 0.5
    assert row["metrics"]["citation_validity"] == 0
    assert not row["passed"]


async def test_exception_is_failure_without_secret_in_report(monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("sk-SECRET https://user:password@example.invalid ?token=SECRET")

    monkeypatch.setattr(ScriptedLLM, "ainvoke", broken)
    report = await evaluate(CASES[:2])
    assert len(report["rows"]) == 2
    assert all(not row["passed"] for row in report["rows"])
    serialized = json.dumps(report)
    assert "SECRET" not in serialized
    assert "password" not in serialized
    assert all(row["error"] == "execution_error" for row in report["rows"])


async def test_reply_metadata_and_configuration_secrets_not_serialized(monkeypatch):
    original = ScriptedLLM.ainvoke

    async def inject(self, messages):
        result = await original(self, messages)
        if not result.tool_calls:
            result.content += " SECRET_TOKEN customer@example.com"
        return result

    monkeypatch.setattr(ScriptedLLM, "ainvoke", inject)
    monkeypatch.setattr(settings, "openai_api_key", "SECRET_TOKEN")
    monkeypatch.setattr(settings, "wc_consumer_secret", "SECRET_TOKEN")
    serialized = json.dumps(await evaluate(CASES[:1]))
    assert "SECRET_TOKEN" not in serialized
    assert "customer@example.com" not in serialized
    assert CASES[0].question not in serialized


async def test_baseline_reports_regression_for_single_question():
    before = await evaluate(CASES[:2])
    after = copy.deepcopy(before)
    after["rows"][1]["metrics"]["answer_correct"] = 0
    after["rows"][1]["passed"] = False
    delta = compare(before, after)
    assert delta[0]["regressions"] == []
    assert delta[1]["id"] == "ship-02"
    assert "answer_correct" in delta[1]["regressions"]
    assert delta[1]["delta"]["answer_correct"] == -1
    for key in ("mode", "fixture_digest", "dataset_digest", "schema_version", "repeats"):
        incompatible = {**before, key: "different"}
        with pytest.raises(ValueError, match="incompatible"):
            compare(incompatible, after)
    with pytest.raises(ValueError, match="case repetitions"):
        compare(before, {**after, "rows": after["rows"][:1]})


def test_cli_writes_report_and_checks_baseline_before_running(tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    assert main(["--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["summary"]["pass_rate"]["mean"] == 1
    report["mode"] = "incompatible"
    output.write_text(json.dumps(report))

    def forbidden(*args, **kwargs):
        pytest.fail("incompatible baseline must be rejected before evaluation")

    monkeypatch.setattr("evals.run_agent_eval.evaluate", forbidden)
    assert main(["--baseline", str(output)]) == 2


async def test_trace_counts_tokens_and_unavailable_calls():
    class Model:
        calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            return AIMessage(
                content="accedi" if self.calls > 1 else "",
                tool_calls=[]
                if self.calls > 1
                else [{"id": "x", "name": "stato_ordine", "args": {"numero_ordine": 22}}],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )

    trace = AgentTrace()
    toolset = build_toolset(
        None, knowledge_base=KnowledgeBase(store=FakeStore()), catalog=CatalogService(FakeWoo())
    )
    result = await answer("ordine", toolset=toolset, llm=Model(), trace=trace)
    assert result.tools_used == []
    assert replace(trace) == AgentTrace(2, 1, 1, 20, 10)
    assert estimate(30, 3, 4)["embedding_requests_max"] == 361


async def test_live_cosine_ranking_with_fake_embeddings():
    from evals.live import LiveStore

    class Embeddings:
        async def aembed_query(self, query):
            return [1.0, 0.0]

    docs = [Document(page_content=key) for key in ("opposite", "same", "orthogonal")]
    store = LiveStore(Embeddings(), docs, [[-1, 0], [1, 0], [0, 1]])
    hits = await store.asimilarity_search_with_score("query", k=2)
    assert [(doc.page_content, score) for doc, score in hits] == [("same", 0), ("orthogonal", 1)]
    assert store.embedding_calls == 1


async def test_live_runner_can_be_exercised_without_external_api(monkeypatch):
    from evals import live

    class Store(FakeStore):
        embedding_calls = 0

        async def asimilarity_search_with_score(self, query, k=4):
            self.embedding_calls += 1
            return await super().asimilarity_search_with_score(query, k=k)

    async def prepare():
        return Store()

    monkeypatch.setattr(live, "prepare_store", prepare)
    monkeypatch.setattr(live, "build_model", lambda tools: ScriptedLLM("ship-01"))
    report = await evaluate(CASES[:1], repeats=2, live=True, allow_external=True)
    assert report["mode"] == "live-synthetic"
    assert report["embedding_calls"] == 3
    assert all(row["passed"] for row in report["rows"])


def test_legacy_retrieval_eval_also_requires_opt_in(monkeypatch, capsys):
    from evals import run_eval

    monkeypatch.setattr(sys, "argv", ["run_eval.py"])
    with pytest.raises(SystemExit) as exc:
        run_eval.main()
    assert exc.value.code == 2
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--estimate"])
    run_eval.main()
    assert "embedding" in capsys.readouterr().out


def test_dataset_validation_rejects_duplicates_and_inconsistent_routes(tmp_path):
    path = tmp_path / "invalid.jsonl"
    path.write_text(CASES[0].model_dump_json() + "\n" + CASES[0].model_dump_json())
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)
    path.write_text(CASES[0].model_copy(update={"expected_route": "none"}).model_dump_json())
    with pytest.raises(ValueError, match="disagree"):
        load_cases(path)
