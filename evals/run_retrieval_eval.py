"""Mechanical retrieval ablations, independent of FakeStore/scripted golden plans."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from statistics import mean

from app import agent
from app.agent import AgentTrace, answer, build_toolset
from app.auth.session import Session
from app.config import RetrievalConfig
from app.tools.orders import OrderService
from evals.diagnostics import classify_failure, describe_attempt
from evals.fixtures import FakeWoo
from evals.metrics import (
    RecordingKnowledgeBase,
    RecordingStore,
    admitted_documents,
    digest,
    source_key,
)
from evals.network import offline_network
from evals.retrieval_fixtures import CASES, LocalModel, VectorStore, corpus

HERE = Path(__file__).resolve().parent


def variants():
    base = RetrievalConfig()
    hybrid = {**base.model_dump(), "strategy": "hybrid"}
    return {
        "semantic": (None, base),
        "hybrid": ("semantic", RetrievalConfig(**hybrid)),
        "hybrid-candidates-4": ("hybrid", RetrievalConfig(**{**hybrid, "candidates": 4})),
        "hybrid-rrf-20": ("hybrid", RetrievalConfig(**{**hybrid, "rrf_constant": 20})),
        "hybrid-lexical-2": ("hybrid", RetrievalConfig(**{**hybrid, "lexical_weight": 2.0})),
        "hybrid-retry": ("hybrid", RetrievalConfig(**{**hybrid, "retry_attempts": 1})),
    }


async def evaluate_retrieval(
    store, docs, *, cases=None, repeats=3, commit=None, mode="offline-local",
):
    if repeats < 1:
        raise ValueError("positive repeats required")
    cases = CASES if cases is None else cases
    rows = []
    for name, (_parent, config) in variants().items():
        for case in cases:
            for repeat in range(1, repeats + 1):
                recorder = RecordingStore(store)
                recorder.config, recorder.corpus = config, docs
                kb = RecordingKnowledgeBase(recorder, config=config)
                woo, trace = FakeWoo(), AgentTrace()
                session = Session(email="test@example.invalid", customer_id=101) if case.get(
                    "order") else None
                tools = build_toolset(
                    session, knowledge_base=kb,
                    order_service=OrderService(customer_id=101, client=woo),
                )
                started = time.perf_counter()
                result = await answer(
                    case["query"], session=session, toolset=tools,
                    llm=LocalModel(case["query"], case.get("order")), trace=trace,
                )
                elapsed = (time.perf_counter() - started) * 1000
                expected = {d.metadata["chunk_id"] for d in docs
                            if source_key(d.metadata) == case["source"]}
                attempts = [a for search in recorder.searches for a in search.attempts]
                first_ids, final_ids = attempts[0].selected_ids, attempts[-1].selected_ids
                cited = {i for source in result.sources for i in source["chunk_ids"]}
                audited = {d.metadata["chunk_id"]: d for d in admitted_documents(recorder)}
                text_ids = set(re.findall(r"\[(chunk-[^\[\]\s]*)\]", result.reply))
                citation_ok = text_ids == cited and cited <= audited.keys() and all(
                    (s["title"], s["url"], s["type"]) == (
                        audited[key].metadata["title"], audited[key].metadata["source"],
                        audited[key].metadata["type"],
                    ) for s in result.sources for key in s["chunk_ids"]
                )
                answer_ok = bool(cited & expected) if case["source"] else not cited
                first_rank = next(
                    (i for i, key in enumerate(first_ids, 1) if key in expected), None,
                )
                final_rank = next(
                    (i for i, key in enumerate(final_ids, 1) if key in expected), None,
                )
                metrics = {
                    "first_hit_at_k": float(first_rank is not None) if expected else None,
                    "first_mrr": (1 / first_rank if first_rank else 0) if expected else None,
                    "final_hit_at_k": float(final_rank is not None) if expected else None,
                    "final_mrr": (1 / final_rank if final_rank else 0) if expected else None,
                    "abstention_correct": float(not final_ids) if not case["source"] else None,
                    "citation_validity": float(citation_ok),
                    "citation_precision": (len(cited & expected) / len(cited) if cited
                                           else 0.0 if case["source"] else None),
                    "mechanical_answer": float(answer_ok and citation_ok),
                    "retrieval_calls": len(attempts), "llm_calls": trace.llm_calls,
                    "woo_calls": woo.calls, "latency_ms": elapsed,
                    "second_stage_ms": sum(
                        ms for a in attempts for stage, ms in a.timings_ms.items()
                        if stage != "semantic"
                    ),
                    "retry_ms": sum(sum(a.timings_ms.values()) for a in attempts[1:]),
                    "external_calls": 0, "provider_input_tokens": 0,
                    "provider_output_tokens": 0, "local_stages_cost_usd": 0,
                }
                rows.append({
                    "id": case["id"], "variant": name, "repeat": repeat,
                    "group": case["group"], "route": "mixed" if session else "rag",
                    "expected_chunk_ids": sorted(expected), "metrics": metrics,
                    "failure": classify_failure(
                        expects_source=bool(case["source"]), expected_ids=expected,
                        corpus_ids=[d.metadata["chunk_id"] for d in docs], attempts=attempts,
                        answer_correct=answer_ok, citation_correct=citation_ok,
                    ),
                    "attempts": [describe_attempt(a, expected) for a in attempts],
                })
    summaries, changes = {}, []
    quality = ("first_hit_at_k", "first_mrr", "final_hit_at_k", "final_mrr",
               "abstention_correct", "citation_validity", "citation_precision", "mechanical_answer")
    for name, (parent, _) in variants().items():
        values = [row for row in rows if row["variant"] == name]
        summaries[name] = summarize(values)
        if parent:
            for reference in dict.fromkeys(("semantic", parent)):
                for case in cases:
                    current = summarize([r for r in values if r["id"] == case["id"]])
                    previous = summarize([r for r in rows if r["variant"] == reference
                                          and r["id"] == case["id"]])
                    delta = {key: current[key] - previous[key] for key in current
                             if current[key] is not None and previous[key] is not None}
                    changes.append({
                        "id": case["id"], "variant": name, "reference": reference, "delta": delta,
                        "regressions": [key for key in quality if delta.get(key, 0) < -1e-9],
                        "cost_increases": [key for key in ("retrieval_calls", "external_calls")
                                           if delta.get(key, 0) > 0],
                        "latency_increase": current["latency_ms"] > max(
                            previous["latency_ms"] * 1.2, previous["latency_ms"] + 10),
                    })
    return {
        "schema_version": 1, "benchmark": "retrieval-ablation", "mode": mode, "commit": commit,
        "dataset_digest": digest(cases),
        "corpus_digest": digest([(d.page_content, d.metadata) for d in docs]),
        "fixture_digest": digest((HERE / "retrieval_fixtures.py").read_text()),
        "implementation_digest": digest([
            *[p.read_text() for p in sorted(HERE.glob("*.py"))],
            *[p.read_text() for p in sorted(Path(agent.__file__).parent.rglob("*.py"))],
        ]),
        "repeats": repeats,
        "configurations": {k: c.model_dump() for k, (_, c) in variants().items()},
        "rows": rows, "summary": summaries, "comparison": changes,
        "scope": "Mechanical correctness only: local embeddings/model, no semantic quality claim.",
    }


def summarize(rows):
    return {key: mean(values) if (values := [r["metrics"][key] for r in rows
                                          if r["metrics"][key] is not None]) else None
            for key in rows[0]["metrics"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "results" / "retrieval.json")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--commit")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    with offline_network():
        report = asyncio.run(evaluate_retrieval(
            VectorStore(), corpus(), repeats=args.repeats, commit=args.commit,
        ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for name, metrics in report["summary"].items():
        print(f"{name}: first_hit={metrics['first_hit_at_k']:.3f} "
              f"final_hit={metrics['final_hit_at_k']:.3f} "
              f"abstention={metrics['abstention_correct']:.3f}")
    return 0  # Exploratory ablations report failures/regressions without hiding them.


if __name__ == "__main__":
    raise SystemExit(main())
