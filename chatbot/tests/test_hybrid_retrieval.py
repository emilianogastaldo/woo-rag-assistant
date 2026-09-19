"""Deterministic algorithm, evidence, retry and diagnostics contracts (no network)."""
from __future__ import annotations

import math
from copy import deepcopy

import pytest
from evals.diagnostics import classify_failure, describe_attempt
from evals.metrics import RecordingKnowledgeBase, RecordingStore, admitted_documents
from evals.retrieval_fixtures import CASES, VectorStore, corpus
from evals.run_retrieval_eval import evaluate_retrieval
from langchain_core.documents import Document
from pydantic import ValidationError

from app.agent import UNCITED_REPLY, answer, build_toolset
from app.config import RetrievalConfig, Settings
from app.rag.chain import KnowledgeBase
from app.rag.chunks import split_documents
from app.rag.lexical import BM25Index, code_tokens, documents_from_records, tokenize
from app.rag.retrieval import evidence_gate, rank_candidates, reformulate
from tests.test_agent import FakeLLM
from tests.test_citations import call


def chunks(*texts):
    return split_documents([
        Document(page_content=text, metadata={
            "source": f"https://test.invalid/{i}", "title": f"Document {i}", "type": "page",
        }) for i, text in enumerate(texts)
    ])


def test_tokenization_preserves_unicode_codes_numbers_and_negative_constraints():
    assert tokenize("SKU ＡＢ‑１２３, 4,90 €, 49, Città, non senza AB_124") == [
        "ab-123", "4,90", "49", "città", "non", "senza", "ab_124",
    ]
    assert code_tokens("ZX-104 A12 30 giorni TSHIRT-BIO") == {"zx-104", "a12", "tshirt-bio"}
    assert "zx-104" in tokenize(reformulate("Vorrei restituire ZX-104 entro 30 giorni, non 14"))
    assert {"30", "non", "14"} <= set(tokenize(reformulate("restituire 30 non 14")))


def test_bm25_matches_hand_calculation_and_deduplicates_query_and_documents():
    docs = chunks("alpha alpha beta", "beta gamma")
    index = BM25Index([*docs, docs[0]])
    identifier = docs[0].metadata["chunk_id"]
    length, average = index.lengths[identifier], index.average_length
    expected = math.log(2) * 2 * 2.5 / (2 + 1.5 * (0.25 + 0.75 * length / average))
    result = index.search("alpha alpha", 10)
    assert len(result) == 1
    assert result[0][1] == pytest.approx(expected)
    assert index.search("unknown", 4) == []
    assert BM25Index([]).search("alpha", 4) == []


def test_bm25_uses_sku_metadata_without_modifying_chunk_identity():
    docs = corpus()
    index = BM25Index(docs)
    hit = index.search("BOTTLE-THERMO", 4)[0][0]
    assert hit.metadata["sku"] == "BOTTLE-THERMO"
    assert "BOTTLE-THERMO" not in hit.page_content
    assert index.search("BOTTLE-THERMO-999", 4) == []
    assert BM25Index(list(reversed(docs))).search("caldo freddo", 10) == index.search(
        "caldo freddo", 10)


def test_record_id_and_metadata_integrity_are_required():
    store = VectorStore()
    records = store.get()
    assert len(documents_from_records(records)) == len(store.docs)
    records["ids"][0] = "different-id"
    assert len(documents_from_records(records)) == len(store.docs) - 1
    changed = deepcopy(store.docs[1])
    changed.page_content += "tampered"
    assert not BM25Index([changed]).documents


def test_rrf_weighted_union_unique_contributions_and_stable_ties():
    a, b, c = chunks("alpha", "beta", "gamma")
    config = RetrievalConfig(strategy="hybrid", rrf_constant=10, lexical_weight=2)
    result = rank_candidates([(a, .2), (a, .2), (b, .3)], [(b, 7), (c, 3)], config)
    assert [x.document for x in result] == [b, c, a]
    assert result[0].rrf_score == pytest.approx(1 / 12 + 2 / 11)
    assert result[0].semantic_rank == 2 and result[0].bm25_rank == 1
    assert result[1].cosine_distance is None
    ties = rank_candidates([(a, .2)], [(b, 1)], RetrievalConfig(strategy="hybrid"))
    assert [x.chunk_id for x in ties] == sorted(x.chunk_id for x in ties)
    assert rank_candidates([(a, float("nan")), (b, float("inf")), (c, -5)], [], config) == []


def test_rrf_score_never_passes_cosine_gate_and_unknown_code_blocks_semantic():
    doc = chunks("manuale ZX-104")[0]
    config = RetrievalConfig(strategy="hybrid")
    item = rank_candidates([(doc, .9)], [(doc, .5)], config)[0]
    assert item.rrf_score < config.max_distance
    assert evidence_gate(item, "manuale ZX-104", config) == "rejected"
    item.cosine_distance = .1
    assert evidence_gate(item, "manuale ZX-999", config) == "code_mismatch"
    assert evidence_gate(item, "manuale ZX-104", config) == "cosine"
    item.cosine_distance = None
    item.bm25_score = 10
    assert evidence_gate(item, "manuale ZX-104", config) == "lexical"
    assert evidence_gate(item, "garanzia meteoriti ZX-104", config) == "rejected"


@pytest.mark.parametrize("options", [
    {"strategy": "rrf"}, {"k": 0}, {"k": 5, "candidates": 4}, {"candidates": 0},
    {"rrf_constant": 0}, {"max_distance": 3}, {"bm25_b": 2}, {"bm25_k1": 0},
    {"semantic_weight": 0}, {"lexical_weight": -1}, {"retry_attempts": 2},
    {"lexical_min_coverage": 0}, {"lexical_min_score": float("nan")},
])
def test_configuration_rejects_invalid_or_unbounded_options(options):
    with pytest.raises(ValidationError):
        RetrievalConfig(**options)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{f"retrieval_{k}": v for k, v in options.items()})


async def test_hybrid_recovers_exact_sku_and_never_duplicates_context():
    store = VectorStore()
    semantic = await KnowledgeBase(store).search("BOTTLE-THERMO")
    hybrid = await KnowledgeBase(store, config=RetrievalConfig(strategy="hybrid")).search(
        "BOTTLE-THERMO")
    assert not semantic.found
    assert hybrid.found and len(hybrid.chunks) == 1
    assert hybrid.attempts[0].candidates[0].evidence == "lexical"
    assert len(hybrid.attempts) == 1
    assert not (await KnowledgeBase(store, config=RetrievalConfig(strategy="hybrid")).search(
        "manuale ZX-999")).found


async def test_retry_is_bounded_and_first_attempt_is_preserved():
    config = RetrievalConfig(strategy="hybrid", retry_attempts=1)
    result = await KnowledgeBase(VectorStore(), config=config).search("Vorrei restituire")
    assert len(result.attempts) == 2 and result.found
    assert not result.attempts[0].selected_ids
    assert result.attempts[1].selected_ids and result.attempts[1].reformulated
    assert result.attempts[0].query_digest != result.attempts[1].query_digest
    assert all(a.rewrite_calls == a.generation_calls == 0 for a in result.attempts)
    assert len((await KnowledgeBase(VectorStore(), config=config).search("ZX-999")).attempts) <= 2
    success = await KnowledgeBase(VectorStore(), config=config).search("BOTTLE-THERMO")
    assert len(success.attempts) == 1
    assert len((await KnowledgeBase(VectorStore(), config=config).search("xyz")).attempts) == 1
    with pytest.raises(ValidationError):
        await KnowledgeBase(VectorStore()).search("anything", k=0)


async def test_passage_assessor_can_reject_nonempty_passages_before_retry():
    calls = []

    def reject(query, docs):
        calls.append(query)
        assert docs
        return False

    kb = KnowledgeBase(VectorStore(), config=RetrievalConfig(strategy="hybrid", retry_attempts=1),
                       passage_assessor=reject)
    result = await kb.search("Quanto costa la spedizione?")
    assert not result.found and len(result.attempts) == 2 and len(calls) == 2
    assert all(a.adequacy == "assessor_rejected" for a in result.attempts)


async def test_retry_does_not_register_rejected_passages_for_citations():
    from langchain_core.messages import AIMessage

    store = VectorStore()
    identifier = store.docs[0].metadata["chunk_id"]
    kb = KnowledgeBase(store, config=RetrievalConfig(retry_attempts=1),
                       passage_assessor=lambda query, docs: False)
    result = await answer("spedizioni", toolset=build_toolset(None, knowledge_base=kb),
                          llm=FakeLLM(call(domanda="spedizioni"), AIMessage(
                              content=f"Gratis [{identifier}]")))
    assert result.reply == UNCITED_REPLY and result.sources == []


async def test_independent_citation_audit_accepts_lexical_not_fused_distance():
    store = RecordingStore(VectorStore())
    store.config = RetrievalConfig(strategy="hybrid")
    kb = RecordingKnowledgeBase(store, config=store.config)
    result = await kb.search("BOTTLE-THERMO")
    assert {d.metadata["chunk_id"] for d in admitted_documents(store)} == set(result.chunks)
    candidate = next(c for c in result.attempts[0].candidates if c.chunk_id in result.chunks)
    candidate.bm25_score = 0.01
    assert candidate.rrf_score < .6
    assert admitted_documents(store) == []


async def test_failure_classification_and_ranks():
    store = VectorStore()
    config = RetrievalConfig(strategy="hybrid")
    result = await KnowledgeBase(store, config=config).search("BOTTLE-THERMO")
    expected = set(result.chunks)
    args = dict(expects_source=True, expected_ids=expected, corpus_ids=expected,
                attempts=result.attempts, answer_correct=True, citation_correct=True)
    assert classify_failure(**args) == "none"
    assert classify_failure(**{**args, "corpus_ids": []}) == "corpus_miss"
    assert classify_failure(**{**args, "attempts": []}) == "retrieval_miss"
    assert classify_failure(**{**args, "citation_correct": False}) == "generation/citation_miss"
    assert classify_failure(**{**args, "answer_correct": False}) == "generation/citation_miss"
    attempt = result.attempts[0]
    assert describe_attempt(attempt, expected)["expected_context_rank"] == 1
    attempt.selected_ids = []
    assert classify_failure(**args) == "ranking_miss"
    for c in attempt.candidates:
        c.accepted = False
    assert classify_failure(**args) == "retrieval_miss"


async def test_actual_strategy_benchmark_exposes_recovery_and_regressions():
    report = await evaluate_retrieval(VectorStore(), corpus(), cases=CASES[:1], repeats=1)
    assert report["summary"]["semantic"]["first_hit_at_k"] == 0
    assert report["summary"]["hybrid"]["first_hit_at_k"] == 1
    assert report["rows"][0]["failure"] == "retrieval_miss"
    assert all(r["metrics"]["external_calls"] == 0 for r in report["rows"])
    assert report["comparison"]
