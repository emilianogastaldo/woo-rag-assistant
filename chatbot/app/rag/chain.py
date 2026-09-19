"""Catena RAG: retrieval sulla knowledge base statica con citazione delle fonti.

Il retrieval è separato dalla generazione: qui si recuperano i chunk pertinenti e
si restituisce un contesto già formattato più l'elenco strutturato delle fonti.
La generazione la fa l'agente (`app/agent.py`), che espone questa ricerca come tool.

Regola "mai inventare": i chunk oltre `retrieval_max_distance` sono scartati. Se non
resta nulla il contesto è vuoto e l'agente deve dichiarare di non saperlo, senza
tentare una risposta.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document

from app.config import RetrievalConfig, settings
from app.rag.lexical import BM25Index, documents_from_records
from app.rag.retrieval import (
    RetrievalAttempt,
    evidence_gate,
    query_digest,
    rank_candidates,
    reformulate,
)
from app.rag.store import get_vector_store

NO_RESULTS = (
    "NESSUN_RISULTATO_PERTINENTE. La knowledge base del negozio non contiene "
    "informazioni su questa domanda: dichiara di non saperlo e invita a contattare "
    "l'assistenza. Non rispondere con conoscenza tua."
)


@dataclass(frozen=True)
class Source:
    """Fonte citabile, ricostruita dai metadati del chunk (non dall'LLM)."""

    title: str
    url: str
    type: str

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "type": self.type}


@dataclass
class RetrievalResult:
    context: str
    chunks: dict[str, Source] = field(default_factory=dict)
    attempts: list[RetrievalAttempt] = field(default_factory=list)

    @property
    def sources(self) -> list[Source]:
        """Fonti recuperate, ancora NON attribuite alla risposta."""
        return list(dict.fromkeys(self.chunks.values()))

    @property
    def found(self) -> bool:
        return bool(self.chunks)


class KnowledgeBase:
    """Accesso in lettura alla collection ChromaDB popolata dall'ingestion."""

    def __init__(
        self, store: Any | None = None, *, config: RetrievalConfig | None = None,
        passage_assessor: Callable[[str, list[Document]], bool] | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._passage_assessor = passage_assessor

    @property
    def store(self) -> Any:
        if self._store is None:
            self._store = get_vector_store()
        return self._store

    async def search(self, query: str, k: int | None = None) -> RetrievalResult:
        config = self._config or settings.retrieval
        if k is not None:
            config = RetrievalConfig(**{**config.model_dump(), "k": k})
        index = None
        snapshot_ms = 0.0
        if config.strategy == "hybrid":
            started = time.perf_counter()
            # Read the current collection every search: no stale lexical sidecar after
            # reingestion/delete/restart, including same-count corpus replacements.
            records = await asyncio.to_thread(self.store.get, include=["documents", "metadatas"])
            index = BM25Index(documents_from_records(records), k1=config.bm25_k1, b=config.bm25_b)
            snapshot_ms = (time.perf_counter() - started) * 1000
        attempts = []
        active_query = query
        for number in range(config.retry_attempts + 1):
            attempt = await self._attempt(active_query, config, index)
            attempt.reformulated = number > 0
            attempt.timings_ms["snapshot_bm25_build"] = snapshot_ms if number == 0 else 0.0
            attempts.append(attempt)
            if attempt.selected_ids or number == config.retry_attempts:
                break
            started = time.perf_counter()
            rewritten = reformulate(query)
            attempt.timings_ms["reformulation"] = (time.perf_counter() - started) * 1000
            if not rewritten or rewritten == active_query:
                break
            active_query = rewritten

        selected = set(attempts[-1].selected_ids)
        blocks: list[str] = []
        chunks: dict[str, Source] = {}
        for item in attempts[-1].candidates:
            if item.chunk_id not in selected:
                continue
            doc, identifier = item.document, item.chunk_id
            meta = doc.metadata or {}
            title = str(meta.get("title", "")) or "Documento del negozio"
            source = Source(
                title=title,
                url=str(meta.get("source", "")),
                type=str(meta.get("type", "")),
            )
            chunks[identifier] = source
            blocks.append(f"[{identifier}] {doc.page_content}")

        return RetrievalResult(
            context="\n\n---\n\n".join(blocks) or NO_RESULTS, chunks=chunks, attempts=attempts,
        )

    async def _attempt(self, query, config, index) -> RetrievalAttempt:
        timings = {}
        started = time.perf_counter()
        # Semantic-only keeps the pre-issue-4 query size and threshold behavior.
        hits = await self.store.asimilarity_search_with_score(
            query, k=config.k if config.strategy == "semantic" else config.candidates,
        )
        timings["semantic"] = (time.perf_counter() - started) * 1000
        lexical = []
        if index is not None:
            # Intersection with the verified snapshot prevents a different generation
            # of Chroma records from entering the fused candidate pool.
            hits = [(doc, score) for doc, score in hits
                    if doc.metadata.get("chunk_id") in index.documents]
            started = time.perf_counter()
            lexical = index.search(query, config.candidates)
            timings["bm25"] = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        candidates = rank_candidates(hits, lexical, config)
        timings["rrf"] = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        for item in candidates:
            item.evidence = evidence_gate(item, query, config)
            item.accepted = item.evidence in {"cosine", "lexical"}
        selected = [item for item in candidates if item.accepted][:config.k]
        timings["evidence_gate"] = (time.perf_counter() - started) * 1000
        adequacy = "evidence_gate"
        if selected and self._passage_assessor is not None:
            started = time.perf_counter()
            adequate = self._passage_assessor(query, [c.document for c in selected])
            timings["passage_assessment"] = (time.perf_counter() - started) * 1000
            adequacy = "assessor_accepted" if adequate else "assessor_rejected"
            if not adequate:
                selected = []
        return RetrievalAttempt(
            query_digest=query_digest(query), strategy=config.strategy, candidates=candidates,
            selected_ids=[c.chunk_id for c in selected], timings_ms=timings, adequacy=adequacy,
        )
