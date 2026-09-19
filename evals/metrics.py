"""Metriche senza LLM judge: regole dichiarative, report privi di payload grezzi."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings
from app.rag.chain import KnowledgeBase
from app.rag.chunks import verified_chunk_id
from app.rag.lexical import code_tokens, searchable_text, tokenize
from app.rag.retrieval import query_digest
from evals.diagnostics import classify_failure, describe_attempt
from evals.fixtures import RAG, TOOLS

SCHEMA_VERSION = 2
QUALITY = (
    "routing_accuracy",
    "tool_accuracy",
    "answer_correct",
    "abstention_correct",
    "hit_at_k",
    "mrr",
    "citation_precision",
    "citation_recall",
    "citation_validity",
)
COUNTERS = (
    "llm_calls",
    "tool_calls",
    "unavailable_tool_calls",
    "retrieval_calls",
    "woo_calls",
    "input_tokens",
    "output_tokens",
    "latency_ms",
)


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$", max_length=64)
    question: str = Field(min_length=1)
    ground_truth: str
    expected_type: Literal[
        "page", "product", "mixed", "order", "out_of_domain", "catalog", "absent"
    ]
    expected_source: str | None
    expected_route: Literal["rag", "data", "mixed", "none"]
    expected_tools: list[str]
    authenticated: bool
    expected_outcome: Literal["answer", "abstain", "decline", "login", "not_found"]
    answer_all: list[str] = Field(min_length=1)
    answer_none: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self):
        if not set(self.expected_tools) <= TOOLS:
            raise ValueError("unknown expected tool")
        if route(self.expected_tools) != self.expected_route:
            raise ValueError("route and expected tools disagree")
        for pattern in self.answer_all + self.answer_none:
            re.compile(pattern)
        return self


def load_cases(path: Path) -> list[Case]:
    cases = [
        Case.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()
    ]
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("empty dataset or duplicate case ids")
    return cases


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def source_key(metadata):
    return metadata.get("sku") or metadata.get("title", "")


def route(tools):
    rag = RAG in tools
    data = bool(set(tools) & (TOOLS - {RAG}))
    return "mixed" if rag and data else "rag" if rag else "data" if data else "none"


class RecordingStore:
    """Osserva il retrieval effettivo, senza eseguire query aggiuntive per l'eval."""

    def __init__(self, store):
        self.store = store
        self.results = []
        self.searches = []
        self.config = settings.retrieval
        self.corpus = []
        self.query_terms = {}

    def get(self, **kwargs):
        return self.store.get(**kwargs)

    async def asimilarity_search_with_score(self, query, k=4):
        self.query_terms[query_digest(query)] = (set(tokenize(query)), code_tokens(query))
        hits = await self.store.asimilarity_search_with_score(query, k=k)
        self.results.append(hits)
        return hits


class RecordingKnowledgeBase(KnowledgeBase):
    async def search(self, query, k=None):
        result = await super().search(query, k=k)
        self.store.searches.append(result)
        return result


def admitted_documents(retrieval):
    """Independent citation audit: RRF is never interpreted as cosine distance."""
    if not retrieval.searches:  # Legacy tests/adapters, semantic-only schema-2 audit.
        return [doc for hits in retrieval.results for doc, distance in hits
                if distance <= settings.retrieval_max_distance]
    documents = []
    config = retrieval.config
    for result in retrieval.searches:
        if not result.attempts:
            continue
        final = result.attempts[-1]
        for item in final.candidates:
            if item.chunk_id not in final.selected_ids or not item.accepted:
                continue
            # Evidence label is audited against the original typed score. The lexical
            # gate was evaluated with the query, whose plaintext is deliberately absent
            # from reports; the recorder keeps only its token set in memory.
            if item.evidence == "cosine":
                valid = (item.cosine_distance is not None
                         and item.cosine_distance <= config.max_distance)
            elif item.evidence == "lexical":
                query_terms, codes = retrieval.query_terms[final.query_digest]
                terms = set(tokenize(searchable_text(item.document)))
                valid = (config.strategy == "hybrid" and item.bm25_score is not None
                         and item.bm25_score >= config.lexical_min_score and bool(query_terms)
                         and codes <= terms
                         and len(query_terms & terms) / len(query_terms)
                         >= config.lexical_min_coverage)
            else:
                valid = False
            if final.reformulated:
                query_terms, codes = retrieval.query_terms[final.query_digest]
                terms = set(tokenize(searchable_text(item.document)))
                valid = valid and bool(query_terms) and codes <= terms and (
                    len(query_terms & terms) / len(query_terms) >= config.lexical_min_coverage
                )
            if valid:
                documents.append(item.document)
    return documents


def score(case, result, retrieval, trace, woo_calls, latency_ms, error=False):
    # Valuta il primo retrieval della domanda; non premia tentativi ripetuti.
    hits = retrieval.results[0] if retrieval.results else []
    attempts = [a for search in retrieval.searches for a in search.attempts]
    if attempts and retrieval.config.strategy == "hybrid":
        hits = [(c.document, c.rrf_score) for c in attempts[0].candidates[:retrieval.config.k]]
    rank = next(
        (
            i
            for i, (doc, _) in enumerate(hits, 1)
            if source_key(doc.metadata) == case.expected_source
        ),
        None,
    )
    admitted = admitted_documents(retrieval)
    identities = {
        (doc.metadata.get("title"), doc.metadata.get("source")): source_key(doc.metadata)
        for doc in [*[doc for hits in retrieval.results for doc, _ in hits], *admitted]
    }
    citations = {(s.get("title"), s.get("url")) for s in result.sources}
    # Audit indipendente dal validatore dell'agente: ID nel testo, sotto soglia,
    # metadati coerenti e appartenenza alla stessa esecuzione.
    retrieved_ids = {
        identifier: (doc.metadata["title"], doc.metadata["source"], doc.metadata["type"])
        for doc in admitted
        if (identifier := verified_chunk_id(doc)) is not None
    }
    text_ids = set(re.findall(r"\[(chunk-[^\[\]\s]*)\]", result.reply))
    attributed_ids = {identifier for s in result.sources for identifier in s.get("chunk_ids", [])}
    verified_sources = {
        (s.get("title"), s.get("url"))
        for s in result.sources
        if s.get("chunk_ids")
        and all(
            identifier in text_ids
            and retrieved_ids.get(identifier) == (s.get("title"), s.get("url"), s.get("type"))
            for identifier in s["chunk_ids"]
        )
    }
    correct_citations = sum(
        citation in verified_sources and identities.get(citation) == case.expected_source
        for citation in citations
        if case.expected_source is not None
    )
    precision = (
        correct_citations / len(citations) if citations else 0.0 if case.expected_source else None
    )
    answer_correct = (
        not error
        and all(re.search(p, result.reply, re.IGNORECASE | re.DOTALL) for p in case.answer_all)
        and not any(re.search(p, result.reply, re.IGNORECASE | re.DOTALL) for p in case.answer_none)
    )
    values = {
        "routing_accuracy": float(not error and route(result.tools_used) == case.expected_route),
        "tool_accuracy": float(not error and set(result.tools_used) == set(case.expected_tools)),
        "answer_correct": float(answer_correct),
        "abstention_correct": float(answer_correct) if case.expected_outcome != "answer" else None,
        "hit_at_k": float(rank is not None) if case.expected_source else None,
        "mrr": (1.0 / rank if rank else 0.0) if case.expected_source else None,
        "citation_precision": precision,
        "citation_recall": float(correct_citations > 0) if case.expected_source else None,
        "citation_validity": float(
            not error and text_ids == attributed_ids and citations == verified_sources
            and (bool(text_ids) if case.expected_source else not text_ids)
        ),
        "llm_calls": trace.llm_calls,
        "tool_calls": trace.tool_calls,
        "unavailable_tool_calls": trace.unavailable_tool_calls,
        "retrieval_calls": len(retrieval.results),
        "woo_calls": woo_calls,
        "input_tokens": trace.input_tokens,
        "output_tokens": trace.output_tokens,
        "latency_ms": round(latency_ms, 3),
    }
    expected_ids = [doc.metadata["chunk_id"] for doc in retrieval.corpus
                    if source_key(doc.metadata) == case.expected_source]
    return {
        "id": case.id,
        "route": route(result.tools_used),
        # Lista chiusa: mai serializzare nomi arbitrari prodotti dal modello.
        "tools": sorted(set(result.tools_used) & TOOLS),
        "error": "execution_error" if error else None,
        "passed": not error
        and all(values[k] == 1 for k in QUALITY if k != "mrr" and values[k] is not None),
        "metrics": values,
        "diagnostics": {
            "failure": classify_failure(
                expects_source=bool(case.expected_source), expected_ids=expected_ids,
                corpus_ids=[doc.metadata["chunk_id"] for doc in retrieval.corpus],
                attempts=attempts, answer_correct=bool(answer_correct),
                citation_correct=values["citation_validity"] == 1
                and (values["citation_recall"] in (None, 1)),
            ),
            "expected_chunk_ids": expected_ids,
            "attempts": [describe_attempt(a, expected_ids) for a in attempts],
        },
    }


def aggregate(rows):
    summary = {}
    for key in (*QUALITY, *COUNTERS):
        values = [r["metrics"][key] for r in rows if r["metrics"][key] is not None]
        summary[key] = {"mean": mean(values) if values else None, "n": len(values)}
    summary["pass_rate"] = {"mean": mean(float(r["passed"]) for r in rows), "n": len(rows)}
    return summary


def compare(before, after):
    """Confronta le medie delle ripetizioni per ID, rifiutando dataset incompatibili."""
    for key in ("schema_version", "dataset_digest", "fixture_digest", "mode", "repeats"):
        if before.get(key) != after.get(key):
            raise ValueError(f"incompatible baseline: {key}")
    old_rows = before["rows"]
    new_rows = after["rows"]
    old_keys = [(r["id"], r["repeat"]) for r in old_rows]
    new_keys = [(r["id"], r["repeat"]) for r in new_rows]
    if (
        set(old_keys) != set(new_keys)
        or len(set(old_keys)) != len(old_keys)
        or len(set(new_keys)) != len(new_keys)
    ):
        raise ValueError("incompatible baseline: case repetitions")
    changes = []
    for case_id in sorted({r["id"] for r in new_rows}):
        previous = aggregate([r for r in old_rows if r["id"] == case_id])
        current = aggregate([r for r in new_rows if r["id"] == case_id])
        deltas, regressions = {}, []
        for key in (*QUALITY, *COUNTERS, "pass_rate"):
            old, new = previous[key]["mean"], current[key]["mean"]
            deltas[key] = None if old is None or new is None else round(new - old, 6)
            if old is not None and new is not None:
                if key in (*QUALITY, "pass_rate") and new < old:
                    regressions.append(key)
                elif key == "latency_ms" and new > max(old * 1.2, old + 10):
                    regressions.append(key)
                elif key in COUNTERS and key != "latency_ms" and new > old:
                    regressions.append(key)
        changes.append(
            {
                "id": case_id,
                "before": previous,
                "after": current,
                "delta": deltas,
                "regressions": regressions,
            }
        )
    return changes
