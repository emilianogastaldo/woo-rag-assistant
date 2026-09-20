"""Failure attribution from corpus membership, candidates and admitted context."""
from __future__ import annotations


def classify_failure(*, expects_source, expected_ids, corpus_ids, attempts,
                     answer_correct, citation_correct):
    if not expects_source:
        return "none" if answer_correct and citation_correct else "generation/citation_miss"
    if not expected_ids or not set(expected_ids) & set(corpus_ids):
        return "corpus_miss"
    if not attempts:
        return "retrieval_miss"
    final = attempts[-1]
    expected = set(expected_ids)
    if expected & set(final.selected_ids):
        return "none" if answer_correct and citation_correct else "generation/citation_miss"
    eligible = {c.chunk_id for c in final.candidates if c.accepted}
    if expected & eligible and final.adequacy != "assessor_rejected":
        return "ranking_miss"
    return "retrieval_miss"


def describe_attempt(attempt, expected_ids):
    expected = set(expected_ids)
    matches = [c for c in attempt.candidates if c.chunk_id in expected]
    return {
        **attempt.as_dict(),
        "expected_candidate_rank": min((c.rank for c in matches), default=None),
        "expected_semantic_rank": min(
            (c.semantic_rank for c in matches if c.semantic_rank is not None), default=None,
        ),
        "expected_bm25_rank": min(
            (c.bm25_rank for c in matches if c.bm25_rank is not None), default=None,
        ),
        "expected_context_rank": next(
            (i for i, identifier in enumerate(attempt.selected_ids, 1) if identifier in expected),
            None,
        ),
    }
