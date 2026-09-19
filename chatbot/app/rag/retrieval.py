"""Rank fusion, evidence gates and bounded local query reformulation."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from langchain_core.documents import Document

from app.config import RetrievalConfig
from app.rag.chunks import verified_chunk_id
from app.rag.lexical import code_tokens, searchable_text, tokenize


@dataclass
class Candidate:
    chunk_id: str
    document: Document = field(repr=False)
    semantic_rank: int | None = None
    cosine_distance: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rank: int = 0
    accepted: bool = False
    evidence: str = "rejected"

    def as_dict(self) -> dict:
        return {key: value for key, value in vars(self).items() if key != "document"}


@dataclass
class RetrievalAttempt:
    query_digest: str
    strategy: str
    candidates: list[Candidate]
    selected_ids: list[str]
    reformulated: bool = False
    timings_ms: dict[str, float] = field(default_factory=dict)
    semantic_calls: int = 1
    rewrite_calls: int = 0
    generation_calls: int = 0
    local_stages_cost_usd: float = 0.0  # embeddings accounted separately by the provider adapter
    adequacy: str = "evidence_gate"

    def as_dict(self) -> dict:
        return {
            **{key: value for key, value in vars(self).items() if key != "candidates"},
            "candidates": [c.as_dict() for c in self.candidates],
        }


def query_digest(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()


def rank_candidates(semantic, lexical, config: RetrievalConfig) -> list[Candidate]:
    """Weighted RRF on 1-based ranks, with one contribution per ID per list."""
    candidates: dict[str, Candidate] = {}
    for channel, hits in (("semantic", semantic), ("bm25", lexical)):
        seen = set()
        rank = 0
        for doc, score in hits:
            identifier = verified_chunk_id(doc)
            if identifier is None or identifier in seen or not math.isfinite(score):
                continue
            if channel == "semantic" and not -1e-6 <= score <= 2.000001:
                continue
            if channel == "bm25" and score <= 0:
                continue
            seen.add(identifier)
            rank += 1
            item = candidates.setdefault(identifier, Candidate(identifier, doc))
            if channel == "semantic":
                item.semantic_rank, item.cosine_distance = rank, max(0.0, min(2.0, score))
            else:
                item.bm25_rank, item.bm25_score = rank, score
    result = list(candidates.values())
    if config.strategy == "hybrid":
        for item in result:
            item.rrf_score = sum(
                weight / (config.rrf_constant + rank)
                for weight, rank in (
                    (config.semantic_weight, item.semantic_rank),
                    (config.lexical_weight, item.bm25_rank),
                ) if rank is not None
            )
        result.sort(key=lambda c: (-c.rrf_score, c.chunk_id))
    else:
        result.sort(key=lambda c: c.semantic_rank)
    for rank, item in enumerate(result, 1):
        item.rank = rank
    return result


def evidence_gate(item: Candidate, query: str, config: RetrievalConfig) -> str:
    semantic = (item.cosine_distance is not None
                and item.cosine_distance <= config.max_distance)
    if config.strategy == "semantic":
        return "cosine" if semantic else "rejected"
    terms = set(tokenize(searchable_text(item.document)))
    # Near-match/unknown SKU must not be rescued by a semantically similar product.
    if not code_tokens(query) <= terms:
        return "code_mismatch"
    if semantic:
        return "cosine"
    query_terms = set(tokenize(query))
    coverage = len(query_terms & terms) / len(query_terms) if query_terms else 0
    if (item.bm25_score is not None and item.bm25_score >= config.lexical_min_score
            and coverage >= config.lexical_min_coverage):
        return "lexical"
    return "rejected"


def reformulate(query: str) -> str:
    """One conservative, local rewrite. Preserve all codes, numbers and negatives.

    No corpus text or LLM prompt is used. A rewrite is attempted only after an empty
    evidence gate (or an explicitly supplied passage assessor), never as error retry.
    """
    synonyms = {"restituire": "reso", "restituzione": "reso", "rimandare": "reso",
                "spedire": "spedizione", "recapito": "consegna"}
    return " ".join(dict.fromkeys(synonyms.get(term, term) for term in tokenize(query)))
