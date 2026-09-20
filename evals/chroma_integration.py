"""Real isolated Chroma + local adapters. Never imported by the offline suite."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import RetrievalConfig, settings
from app.rag.chain import KnowledgeBase
from app.rag.chunks import split_documents
from app.rag.lexical import BM25Index, documents_from_records
from app.rag.store import COLLECTION_METADATA
from evals.network import local_service_network
from evals.retrieval_fixtures import LocalEmbeddings, corpus
from evals.run_retrieval_eval import evaluate_retrieval


async def run(commit):
    # No configured real endpoints/collection are accepted by this harness.
    assert settings.chroma_host == "chroma" and settings.chroma_port == 8000
    assert settings.chroma_collection.startswith("issue4-")
    assert not settings.openai_api_key
    client = None
    for _ in range(40):
        try:
            client = chromadb.HttpClient(
                host="chroma", port=8000, settings=ChromaSettings(anonymized_telemetry=False),
            )
            client.heartbeat()
            break
        except Exception:
            await asyncio.sleep(0.5)
    assert client is not None
    assert client.list_collections() == [], "test volume must be new and empty"
    embeddings = LocalEmbeddings()
    store = Chroma(
        client=client, collection_name=settings.chroma_collection,
        embedding_function=embeddings, collection_metadata=COLLECTION_METADATA,
    )
    docs = corpus()
    ids = [d.metadata["chunk_id"] for d in docs]
    store.add_documents(docs, ids=ids)
    store.add_documents(list(reversed(docs)), ids=list(reversed(ids)))
    records = store.get(include=["documents", "metadatas"])
    assert len(records["ids"]) == len(ids) and set(records["ids"]) == set(ids)
    index = BM25Index(documents_from_records(records))
    assert set(index.documents) == set(ids)
    report = await evaluate_retrieval(
        store, docs, repeats=3, commit=commit, mode="docker-chroma-local-adapters",
    )
    assert all(row["metrics"]["citation_validity"] == 1 for row in report["rows"])
    for case_id in ("unknown-code", "unknown-sku", "absent"):
        assert all(not row["attempts"][-1]["selected_ids"] for row in report["rows"]
                   if row["id"] == case_id and row["variant"].startswith("hybrid"))

    # Same KnowledgeBase across corpus replacement: no stale lexical cache; only
    # this run's dedicated collection is modified. Real delete/upsert/read path.
    kb = KnowledgeBase(store, config=RetrievalConfig(strategy="hybrid"))
    assert (await kb.search("BOTTLE-THERMO")).found
    old_id = next(d.metadata["chunk_id"] for d in docs if d.metadata.get("sku") == "BOTTLE-THERMO")
    store.delete(ids=[old_id])
    assert not (await kb.search("BOTTLE-THERMO")).found
    replacement = split_documents([Document(
        page_content="Accessori per il modello vecchio.",
        metadata={"title": "Accessorio", "source": "https://synthetic.invalid/replacement",
                  "type": "product", "sku": "ACCESSORY-NEW"},
    )])[0]
    store.add_documents([replacement], ids=[replacement.metadata["chunk_id"]])
    assert len(store.get()["ids"]) == len(ids)
    assert not (await kb.search("BOTTLE-THERMO")).found
    assert (await kb.search("ACCESSORY-NEW")).found
    # Legacy and tampered record IDs never enter the lexical index.
    store.add_documents([Document(page_content="LEGACY-999", metadata={"title": "Legacy"})],
                        ids=["legacy-record"])
    records = store.get(include=["documents", "metadatas"])
    assert "legacy-record" not in BM25Index(documents_from_records(records)).documents
    assert not (await kb.search("LEGACY-999")).found
    report["integration"] = {
        "status": "PASS", "stable_ids": True, "idempotent_upsert": True,
        "same_count_replacement": True, "legacy_rejection": True,
        "collection": settings.chroma_collection, "chroma_version": client.get_version(),
        "local_document_embedding_calls": embeddings.document_calls,
        "local_query_embedding_calls": embeddings.query_calls,
        "external_calls": 0, "provider_cost_usd": 0,
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit")
    args = parser.parse_args()
    started = time.perf_counter()
    with local_service_network("chroma", 8000):
        report = asyncio.run(run(args.commit))
    report["elapsed_ms"] = (time.perf_counter() - started) * 1000
    Path("/results/integration.json").write_text(json.dumps(report, indent=2) + "\n")
    print("PASS: isolated Chroma roundtrip, BM25/RRF, citations, replacement and abstention")


if __name__ == "__main__":
    main()
