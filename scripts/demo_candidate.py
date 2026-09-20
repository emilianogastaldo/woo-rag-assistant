"""Explicit, bounded candidate build for the controlled demo migration.

No promotion or cleanup. Use only after separate corpus/provider authorization.
The application CLI remains unchanged; this runner calls its versioned registry.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
from contextlib import contextmanager

import httpx
import tiktoken
from langchain_openai import OpenAIEmbeddings

from app.config import settings
from app.ingest import gather_documents
from app.rag.chunks import split_documents
from app.rag.store import get_chroma_client
from app.rag.versions import Registry, digest, make_manifest


class CandidateBudgetError(RuntimeError):
    """Fail closed without including corpus, credentials or provider payloads."""


def check_manifest(manifest, expected_digest, max_tokens, max_chunks):
    if not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
        raise CandidateBudgetError("Invalid authorized manifest digest")
    if digest(manifest) != expected_digest:
        raise CandidateBudgetError("Corpus or configuration differs from authorization")
    texts = [r["text"] for r in manifest["records"]]
    if not 1 <= len(texts) <= max_chunks <= 1000:
        raise CandidateBudgetError("Chunk budget exceeded")
    encoding = tiktoken.encoding_for_model(manifest["model"])
    tokens = sum(len(encoding.encode(text, disallowed_special=())) for text in texts)
    if not 1 <= tokens <= max_tokens <= 2000:
        raise CandidateBudgetError("Token budget exceeded")
    return texts, tokens


class OneEmbeddingRequest:
    """HTTP request hook: exactly the authorized texts, at most one dispatch."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.attempts = 0

    def __call__(self, request):
        if request.method != "POST" or str(request.url) != "https://api.openai.com/v1/embeddings":
            raise CandidateBudgetError("Provider endpoint not authorized")
        body = json.loads(request.content)
        if (body.get("input") != self.texts
                or body.get("model") != "text-embedding-3-small"
                or body.get("dimensions") != 1536):
            raise CandidateBudgetError("Embedding payload differs from authorization")
        if self.attempts:
            raise CandidateBudgetError("One-request budget exhausted")
        self.attempts += 1


@contextmanager
def deadline(seconds):
    def expired(_signal, _frame):
        raise CandidateBudgetError("Candidate build deadline exceeded")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def build_candidate(*, allow_provider, expected_digest, max_tokens=2000, max_chunks=12):
    if not allow_provider:
        raise CandidateBudgetError("Explicit provider authorization is required")
    if (settings.embedding_model != "text-embedding-3-small"
            or settings.embedding_dimensions != 1536
            or settings.openai_base_url
            or settings.chroma_collection != "woo_knowledge"
            or settings.chunk_size != 800 or settings.chunk_overlap != 120
            or settings.retrieval_strategy != "semantic"
            or settings.retrieval_retry_attempts != 0):
        raise CandidateBudgetError("Configuration differs from migration plan")
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGCHAIN_TRACING"] = "false"
    registry = Registry()
    with registry.lock("admin"):
        before = registry.read_state()
        chunks = split_documents(asyncio.run(gather_documents()))
        manifest = make_manifest(
            chunks, model=settings.embedding_model, dimensions=settings.embedding_dimensions,
            chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap,
        )
        texts, tokens = check_manifest(manifest, expected_digest, max_tokens, max_chunks)
        gate = OneEmbeddingRequest(texts)
        with httpx.Client(
            timeout=15, trust_env=False, follow_redirects=False,
            event_hooks={"request": [gate]},
        ) as http_client:
            embeddings = OpenAIEmbeddings(
                model=settings.embedding_model, dimensions=settings.embedding_dimensions,
                api_key=settings.openai_api_key, request_timeout=15, max_retries=0,
                check_embedding_ctx_length=False, chunk_size=1000, http_client=http_client,
            )
            name = registry.build(get_chroma_client(), chunks, embeddings, promote=False)
        if registry.read_state() != before:
            raise CandidateBudgetError("Active state unexpectedly changed; stop")
        return {"candidate": name, "active_unchanged": True, "chunks": len(texts),
                "estimated_tokens": tokens, "embedding_attempts": gate.attempts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-provider", action="store_true")
    parser.add_argument("--expected-manifest", required=True)
    args = parser.parse_args()
    if not args.allow_provider:
        parser.error("--allow-provider requires separate, explicit corpus/provider consent")
    try:
        with deadline(120):
            result = build_candidate(allow_provider=args.allow_provider,
                                     expected_digest=args.expected_manifest)
    except Exception as exc:
        # Do not echo raw HTTP errors, URLs, text, tokens, or secrets.
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"status": "PASS", **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
