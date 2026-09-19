"""Catena RAG: retrieval sulla knowledge base statica con citazione delle fonti.

Il retrieval è separato dalla generazione: qui si recuperano i chunk pertinenti e
si restituisce un contesto già formattato più l'elenco strutturato delle fonti.
La generazione la fa l'agente (`app/agent.py`), che espone questa ricerca come tool.

Regola "mai inventare": i chunk oltre `retrieval_max_distance` sono scartati. Se non
resta nulla il contesto è vuoto e l'agente deve dichiarare di non saperlo, senza
tentare una risposta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.rag.chunks import verified_chunk_id
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

    @property
    def sources(self) -> list[Source]:
        """Fonti recuperate, ancora NON attribuite alla risposta."""
        return list(dict.fromkeys(self.chunks.values()))

    @property
    def found(self) -> bool:
        return bool(self.chunks)


class KnowledgeBase:
    """Accesso in lettura alla collection ChromaDB popolata dall'ingestion."""

    def __init__(self, store: Any | None = None) -> None:
        self._store = store

    @property
    def store(self) -> Any:
        if self._store is None:
            self._store = get_vector_store()
        return self._store

    async def search(self, query: str, k: int | None = None) -> RetrievalResult:
        hits = await self.store.asimilarity_search_with_score(query, k=k or settings.retrieval_k)
        relevant = [(doc, score) for doc, score in hits if score <= settings.retrieval_max_distance]
        if not relevant:
            return RetrievalResult(context=NO_RESULTS)

        blocks: list[str] = []
        chunks: dict[str, Source] = {}
        for doc, _score in relevant:
            identifier = verified_chunk_id(doc)
            if identifier is None or identifier in chunks:
                continue
            meta = doc.metadata or {}
            title = str(meta.get("title", "")) or "Documento del negozio"
            source = Source(
                title=title,
                url=str(meta.get("source", "")),
                type=str(meta.get("type", "")),
            )
            chunks[identifier] = source
            blocks.append(f"[{identifier}] {doc.page_content}")

        return RetrievalResult(context="\n\n---\n\n".join(blocks) or NO_RESULTS, chunks=chunks)
