"""CLI: offline di default; --live --allow-external abilita solo dati sintetici."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

# Disabilita callback/telemetria anche se l'ambiente di sviluppo li abilita.
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGCHAIN_TRACING"] = "false"
os.environ["ANONYMIZED_TELEMETRY"] = "false"

from app import agent  # noqa: E402
from app.agent import AgentResult, AgentTrace, answer, build_toolset  # noqa: E402
from app.auth.session import Session  # noqa: E402
from app.config import settings  # noqa: E402
from app.tools.catalog import CatalogService  # noqa: E402
from app.tools.orders import OrderService  # noqa: E402
from evals.fixtures import (  # noqa: E402
    AS_OF,
    FakeStore,
    FakeWoo,
    FrozenDate,
    ScriptedLLM,
    documents,
)
from evals.metrics import (  # noqa: E402
    SCHEMA_VERSION,
    RecordingKnowledgeBase,
    RecordingStore,
    aggregate,
    compare,
    digest,
    load_cases,
    score,
)
from evals.network import offline_network  # noqa: E402

HERE = Path(__file__).resolve().parent


def estimate(case_count, repeats, max_steps):
    turns = case_count * repeats
    return {
        "cases": case_count,
        "repeats": repeats,
        "turns": turns,
        "generation_requests_max": turns * max_steps,
        "embedding_requests_max": 1 + turns * max_steps * (1 + settings.retrieval_retry_attempts),
        "generation_output_tokens_max": turns * max_steps * 512,
        "corpus_embedding_requests": 1,
        "retries": 0,
        "retrieval_retries_max": turns * max_steps * settings.retrieval_retry_attempts,
        "note": "Cost depends on input/output and embedding tokens and provider prices. No judge.",
    }


async def evaluate(cases, repeats=1, live=False, allow_external=False, commit=None):
    # La guardia esiste anche nell'API Python, non solo nel parser CLI.
    if live and not allow_external:
        raise ValueError("live evaluation requires explicit --allow-external")
    if repeats < 1 or not cases:
        raise ValueError("positive repeats and non-empty cases required")
    rows = []
    started = time.perf_counter()
    with nullcontext() if live else offline_network(), patch("app.agent.date", FrozenDate):
        if live:
            from evals.live import build_model, prepare_store

            store = await prepare_store()
        else:
            store = FakeStore()
        setup_ms = (time.perf_counter() - started) * 1000
        for case in cases:
            for repeat in range(1, repeats + 1):
                trace = AgentTrace()
                retrieval = RecordingStore(store)
                retrieval.corpus = documents()
                woo = FakeWoo()
                session = (
                    Session(email="synthetic@example.invalid", customer_id=101)
                    if case.authenticated
                    else None
                )
                toolset = build_toolset(
                    session,
                    knowledge_base=RecordingKnowledgeBase(store=retrieval),
                    catalog=CatalogService(client=woo),
                    order_service=OrderService(customer_id=101, client=woo),
                )
                model = build_model(toolset) if live else ScriptedLLM(case.id)
                error = False
                started = time.perf_counter()
                try:
                    result = await answer(
                        case.question,
                        session=session,
                        toolset=toolset,
                        llm=model,
                        trace=trace,
                    )
                except Exception:
                    # Un caso fallito resta nel denominatore; niente stack/URL/secret nel report.
                    error = True
                    result = AgentResult(reply="")
                row = score(
                    case,
                    result,
                    retrieval,
                    trace,
                    woo.calls,
                    (time.perf_counter() - started) * 1000,
                    error,
                )
                row["repeat"] = repeat
                rows.append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "commit": commit,
        "mode": "live-synthetic" if live else "offline-scripted",
        "dataset_digest": digest([c.model_dump() for c in cases]),
        "fixture_digest": digest((HERE / "fixtures.py").read_text()),
        "implementation_digest": digest(
            [
                *[path.read_text() for path in sorted(HERE.glob("*.py"))],
                *[path.read_text() for path in sorted(Path(agent.__file__).parent.rglob("*.py"))],
            ]
        ),
        "repeats": repeats,
        "config": {
            **{f"retrieval_{key}": value for key, value in settings.retrieval.model_dump().items()},
            "retrieval_k": settings.retrieval_k,
            "retrieval_max_distance": settings.retrieval_max_distance,
            "agent_max_steps": settings.agent_max_steps,
            "as_of": AS_OF,
            "model_digest": digest(settings.openai_model) if live else None,
            "embedding_model_digest": digest(settings.embedding_model) if live else None,
        },
        "setup_ms": round(setup_ms, 3),
        "embedding_calls": (1 + store.embedding_calls) if live else 0,
        "estimate": estimate(len(cases), repeats, settings.agent_max_steps) if live else None,
        "rows": rows,
        "summary": aggregate(rows),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="consent to send the synthetic corpus/questions to OpenAI",
    )
    parser.add_argument("--estimate", action="store_true", help="no network or model construction")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--golden", type=Path, default=HERE / "golden.jsonl")
    parser.add_argument("--output", type=Path, default=HERE / "results" / "latest.json")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument(
        "--commit", help="Git commit of the evaluated tree (implementation hash also saved)",
    )
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.live and not args.allow_external and not args.estimate:
        parser.error("live evaluation requires --live --allow-external")
    try:
        cases = load_cases(args.golden)
        if args.estimate:
            print(
                json.dumps(estimate(len(cases), args.repeats, settings.agent_max_steps), indent=2)
            )
            return 0
        baseline = json.loads(args.baseline.read_text()) if args.baseline else None
        if baseline is not None:
            # Rifiuta input incompatibili PRIMA di spendere chiamate live.
            expected = {
                "schema_version": SCHEMA_VERSION,
                "dataset_digest": digest([c.model_dump() for c in cases]),
                "fixture_digest": digest((HERE / "fixtures.py").read_text()),
                "mode": "live-synthetic" if args.live else "offline-scripted",
                "repeats": args.repeats,
                "rows": [
                    {"id": c.id, "repeat": r} for c in cases for r in range(1, args.repeats + 1)
                ],
            }
            for key in ("schema_version", "dataset_digest", "fixture_digest", "mode", "repeats"):
                if baseline.get(key) != expected[key]:
                    raise ValueError("incompatible baseline")
            keys = [(r["id"], r["repeat"]) for r in baseline["rows"]]
            if sorted(keys) != sorted((r["id"], r["repeat"]) for r in expected["rows"]):
                raise ValueError("incompatible baseline cases")
        report = asyncio.run(evaluate(
            cases, args.repeats, args.live, args.allow_external, args.commit,
        ))
        if baseline:
            report["comparison"] = compare(baseline, report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    except Exception:
        # Le eccezioni dei provider possono contenere credenziali o dati del prompt.
        print(
            "Evaluation failed: check configuration/dataset/baseline locally; details suppressed."
        )
        return 2
    failed = sorted({r["id"] for r in report["rows"] if not r["passed"]})
    regressed = [r for r in report.get("comparison", []) if r["regressions"]]
    print(f"{report['mode']}: {len(report['rows'])} runs; failed={failed}")
    for row in regressed:
        print(f"REGRESSION {row['id']}: {', '.join(row['regressions'])}")
    return 1 if failed or regressed else 0


if __name__ == "__main__":
    raise SystemExit(main())
