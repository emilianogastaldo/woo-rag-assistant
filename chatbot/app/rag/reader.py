"""Cancellable read-only Chroma REST adapter; ingestion keeps its own SDK store."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import quote

import httpx
from langchain_core.documents import Document

from app.config import settings
from app.http_clients import current_provider_client
from app.rag.store import get_embeddings
from app.rag.versions import Registry, VersionError
from app.resilience import FailureKind, RecoverableFailure, parse_retry_after, retry_call


class KnowledgeReader:
    def __init__(self):
        self._snapshot = ContextVar("knowledge_snapshot", default=None)

    @contextmanager
    def snapshot(self):
        try:
            with Registry().snapshot() as name:
                token = self._snapshot.set(name)
                try:
                    yield
                finally:
                    self._snapshot.reset(token)
        except (VersionError, OSError, ValueError) as exc:
            raise RecoverableFailure(FailureKind.CHROMA_UNAVAILABLE) from exc

    async def _request(self, method, path, payload=None):
        client = current_provider_client()
        if client is None:
            async with httpx.AsyncClient(trust_env=False) as owned:
                return await self._send(owned, method, path, payload)
        return await self._send(client, method, path, payload)

    async def _send(self, client, method, path, payload):
        async def send():
            url = (f"http://{settings.chroma_host}:{settings.chroma_port}/api/v2/tenants/"
                   f"default_tenant/databases/default_database/collections/{path}")
            try:
                response = await client.request(method, url, json=payload)
            except httpx.TimeoutException as exc:
                raise RecoverableFailure(FailureKind.TIMEOUT, retryable=True) from exc
            except httpx.TransportError as exc:
                raise RecoverableFailure(FailureKind.CHROMA_UNAVAILABLE, retryable=True) from exc
            if response.status_code >= 400:
                raise RecoverableFailure(
                    FailureKind.CHROMA_UNAVAILABLE,
                    retryable=response.status_code == 429 or response.status_code >= 500,
                    retry_after=parse_retry_after(response.headers.get("Retry-After")),
                )
            try:
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("invalid response")
                return result
            except ValueError as exc:
                raise RecoverableFailure(FailureKind.MALFORMED_RESPONSE) from exc

        return await retry_call("chroma_http", send, max_retries=settings.provider_retry_attempts,
                                timeout_seconds=settings.provider_timeout_seconds, idempotent=True)

    async def _collection(self):
        # The search pins one immutable generation across BM25, vectors and retries.
        name = self._snapshot.get()
        if name is None:
            with self.snapshot():
                return await self._collection()
        result = await self._request("GET", quote(name, safe=""))
        identifier = result.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise RecoverableFailure(FailureKind.MALFORMED_RESPONSE)
        return quote(identifier, safe="")

    async def aget(self):
        identifier = await self._collection()
        return await self._request("POST", f"{identifier}/get",
                                   {"include": ["documents", "metadatas"]})

    async def asimilarity_search_with_score(self, query, k=4):
        # Each physical operation retries only itself, never the entire pipeline.
        from app.resilience import provider_call

        vector = await provider_call("embedding", lambda: get_embeddings().aembed_query(query))
        identifier = await self._collection()
        result = await self._request("POST", f"{identifier}/query", {
            "query_embeddings": [vector], "n_results": k,
            "include": ["documents", "metadatas", "distances"],
        })
        try:
            docs, metadata, scores = (result[key][0] for key in
                                      ("documents", "metadatas", "distances"))
            if not (isinstance(docs, list) and isinstance(metadata, list)
                    and isinstance(scores, list) and len(docs) == len(metadata) == len(scores)):
                raise ValueError("invalid rows")
            return [(Document(page_content=doc, metadata=meta), float(score))
                    for doc, meta, score in zip(docs, metadata, scores, strict=True)]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RecoverableFailure(FailureKind.MALFORMED_RESPONSE) from exc
