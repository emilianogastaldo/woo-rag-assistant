"""Opt-in six-case smoke: one bounded embedding request, no paid generation/judge."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from pathlib import Path

from app.config import settings
from app.rag.retrieval import query_digest, reformulate
from evals.metrics import digest
from evals.network import offline_network
from evals.retrieval_fixtures import CASES, VectorStore, corpus
from evals.run_retrieval_eval import evaluate_retrieval

MODEL = "text-embedding-3-small"
PRICE_PER_MILLION = 0.02
PRICE_AS_OF = "2026-09-19"
PRICE_SOURCE = "https://developers.openai.com/api/docs/models/text-embedding-3-small"
MAX_INPUT_BYTES = 12_000  # Conservative upper bound on byte-BPE tokens, no tokenizer download.
SMOKE_IDS = {"sku-only", "manual-code", "paraphrase", "unknown-code", "absent-policy", "mixed"}


def plan(max_cost_usd=0.001):
    if not math.isfinite(max_cost_usd) or not 0 < max_cost_usd <= 0.001:
        raise ValueError("budget must be in (0, 0.001] USD")
    docs = corpus()
    cases = [c for c in CASES if c["id"] in SMOKE_IDS]
    if len(cases) != 6:
        raise ValueError("smoke requires the six reviewed cases")
    queries = [query for c in cases for query in (c["query"], reformulate(c["query"]))]
    inputs = list(dict.fromkeys([d.page_content for d in docs] + [q for q in queries if q]))
    sizes = [len(text.encode("utf-8")) for text in inputs]
    token_upper_bound = sum(sizes)
    upper_cost = token_upper_bound * PRICE_PER_MILLION / 1_000_000
    if not sizes or max(sizes) > 8_000 or token_upper_bound > MAX_INPUT_BYTES:
        raise ValueError("embedding input budget exceeded")
    if upper_cost > max_cost_usd:
        raise ValueError("estimated upper cost exceeds approved budget")
    return docs, cases, inputs, {
        "model": MODEL, "cases": sorted(SMOKE_IDS), "repeats": 1,
        "documents": len(docs), "embedding_inputs": len(inputs),
        "embedding_requests_max": 1, "generation_requests_max": 0,
        "rewrite_requests_max": 0, "sdk_retries": 0, "judge_requests_max": 0,
        "output_tokens_max": 0, "request_timeout_seconds": 30, "run_timeout_seconds": 60,
        "input_tokens_upper_bound": token_upper_bound, "approved_max_cost_usd": max_cost_usd,
        "estimated_upper_cost_usd": upper_cost, "price_per_million": PRICE_PER_MILLION,
        "price_as_of": PRICE_AS_OF, "price_source": PRICE_SOURCE,
        "data": "versioned synthetic corpus + six synthetic questions and local rewrites",
        "services": "OpenAI embeddings only; no WooCommerce, Chroma or demo access",
    }


async def fetch_vectors(inputs):
    # Construct provider only after Python/CLI consent and input/cost checks.
    from openai import AsyncOpenAI, DefaultAsyncHttpxClient

    async with AsyncOpenAI(
        api_key=settings.openai_api_key, base_url="https://api.openai.com/v1",
        max_retries=0, timeout=30, http_client=DefaultAsyncHttpxClient(trust_env=False),
    ) as client:
        response = await asyncio.wait_for(client.embeddings.create(
            model=MODEL, input=inputs, encoding_format="float",
        ), timeout=30)
    items = sorted(response.data, key=lambda item: item.index)
    if [item.index for item in items] != list(range(len(inputs))):
        raise ValueError("incomplete embedding response")
    return [item.embedding for item in items], response.usage.total_tokens


class CachedEmbeddings:
    def __init__(self, inputs, vectors):
        self.cache = {}
        for text, vector in zip(inputs, vectors, strict=True):
            norm = math.sqrt(sum(v * v for v in vector))
            if not norm or not math.isfinite(norm):
                raise ValueError("invalid embedding vector")
            self.cache[text] = [v / norm for v in vector]

    def embed_documents(self, texts):
        return [self.cache[text] for text in texts]

    def embed_query(self, query):
        # Missing input raises; it cannot trigger additional network calls.
        return self.cache[query]


class RecordedScoresStore(VectorStore):
    """Replay complete measured cosine rankings; BM25/gates run again locally.

    This is a regression replay, not another real-embedding/ANN measurement.
    Partial candidate lists are rejected rather than fabricating missing scores.
    """

    def __init__(self, docs, report):
        self.docs = docs
        documents = {d.metadata["chunk_id"]: d for d in docs}
        self.rankings = {}
        for row in report["rows"]:
            for attempt in row["attempts"]:
                hits = sorted([c for c in attempt["candidates"] if c["semantic_rank"] is not None],
                              key=lambda c: c["semantic_rank"])
                if {c["chunk_id"] for c in hits} != documents.keys():
                    continue
                self.rankings[attempt["query_digest"]] = [
                    (documents[c["chunk_id"]], c["cosine_distance"]) for c in hits
                ]

    async def asimilarity_search_with_score(self, query, k=4):
        return self.rankings[query_digest(query)][:k]


async def replay(report, commit=None):
    docs, cases, _, _ = plan()
    if (report.get("mode") != "live-embedding-smoke" or report.get("schema_version") != 1
            or report.get("dataset_digest") != digest(cases)
            or report.get("corpus_digest") != digest([(d.page_content, d.metadata) for d in docs])):
        raise ValueError("incompatible smoke recording")
    with offline_network():
        result = await evaluate_retrieval(
            RecordedScoresStore(docs, report), docs, cases=cases, repeats=1,
            commit=commit, mode="offline-recorded-embedding-scores",
        )
    result["replayed_from"] = {"report_digest": digest(report), "commit": report["commit"]}
    result["scope"] = "Offline replay of measured cosine scores; no new provider/vector/ANN run."
    result["provider"] = {"embedding_requests": 0, "generation_calls": 0, "cost_usd": 0}
    old_rows = {(r["variant"], r["id"]): r for r in report["rows"]}
    result["changes_from_recording"] = [{
        "variant": row["variant"], "id": row["id"],
        "before_failure": old_rows[(row["variant"], row["id"])]["failure"],
        "after_failure": row["failure"],
        "before_metrics": old_rows[(row["variant"], row["id"])]["metrics"],
        "after_metrics": row["metrics"],
    } for row in result["rows"]]
    return result


async def smoke(*, allow_external=False, max_cost_usd=0.001, commit=None):
    if not allow_external:
        raise ValueError("explicit --allow-external required")
    docs, cases, inputs, limits = plan(max_cost_usd)
    started = time.perf_counter()
    vectors, tokens = await fetch_vectors(inputs)
    embedding_ms = (time.perf_counter() - started) * 1000
    # All strategies use these exact same vectors; no provider access after the batch.
    with offline_network():
        store = VectorStore(docs, CachedEmbeddings(inputs, vectors))
        report = await evaluate_retrieval(
            store, docs, cases=cases, repeats=1, commit=commit, mode="live-embedding-smoke",
        )
    report["scope"] = (
        "Six-case real-embedding retrieval smoke; local generation/Woo, in-memory cosine. "
        "Not a repeated benchmark, production routing/generation test or Chroma E2E test."
    )
    report["provider"] = {
        "limits": limits, "embedding_requests": 1, "embedding_tokens_measured": tokens,
        "embedding_latency_ms": embedding_ms,
        "cost_usd_estimated_from_measured_tokens": tokens * PRICE_PER_MILLION / 1_000_000,
        "cost_is_invoice": False, "generation_calls": 0, "rewrite_calls": 0, "judge_calls": 0,
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--estimate", action="store_true")
    parser.add_argument("--replay", type=Path, help="offline replay of complete measured rankings")
    parser.add_argument("--max-cost-usd", type=float, default=0.001)
    parser.add_argument("--commit")
    parser.add_argument("--output", type=Path, default=Path("/results/embedding-smoke.json"))
    args = parser.parse_args(argv)
    if args.replay and (args.live or args.allow_external or args.estimate):
        parser.error("--replay cannot be combined with live/estimate flags")
    if args.replay and args.replay.resolve() == args.output.resolve():
        parser.error("replay output must not overwrite its source")
    if not args.replay and not args.estimate and not (args.live and args.allow_external):
        parser.error("requires --live --allow-external")
    try:
        if args.estimate:
            print(json.dumps(plan(args.max_cost_usd)[3], indent=2))
            return 0
        if args.replay:
            report = asyncio.run(replay(json.loads(args.replay.read_text()), args.commit))
        else:
            report = asyncio.run(asyncio.wait_for(smoke(
                allow_external=args.allow_external, max_cost_usd=args.max_cost_usd,
                commit=args.commit,
            ), timeout=60))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    except Exception:
        print("Smoke failed; no automatic retry. Provider/configuration details suppressed.")
        return 2
    print(json.dumps(report["provider"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
