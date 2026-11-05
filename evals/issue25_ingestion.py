"""Assert the final seed corpus on real WP/Chroma, using local synthetic providers.

Run only through run_issue19_import.py --demo-final in disposable volumes.
"""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlsplit

import httpx

from app.agent import answer
from app.ingest import KNOWLEDGE_PAGE_SLUGS, gather_documents, ingest
from app.rag.chunks import split_documents
from app.rag.store import get_chroma_client
from app.rag.versions import Registry, validate


def main():
    # Bounded startup polling; no external address or credential is used.
    for attempt in range(60):
        try:
            httpx.get("http://upstream:9000/health", timeout=2).raise_for_status()
            get_chroma_client().heartbeat()
            break
        except Exception:
            if attempt == 59:
                raise
            time.sleep(1)
    docs = asyncio.run(gather_documents())
    pages = [doc for doc in docs if doc.metadata["type"] == "page"]
    products = [doc for doc in docs if doc.metadata["type"] == "product"]
    assert len(pages) == 3 and len(products) == 6
    assert {urlsplit(doc.metadata["source"]).path.strip("/") for doc in pages} == set(
        KNOWLEDGE_PAGE_SLUGS
    )
    assert {doc.metadata["sku"] for doc in products} == {
        "TSHIRT-BIO",
        "HOODIE-CLASSIC",
        "CAP-SPORT",
        "SHOES-RUN-X",
        "BACKPACK-URBAN",
        "BOTTLE-THERMO",
    }
    for doc in docs:
        assert doc.metadata["title"] and doc.metadata["source"].startswith("http://wordpress/")
        assert "<h2>" not in doc.page_content and "**" not in doc.page_content
    shipping = next(doc for doc in pages if "/spedizioni/" in doc.metadata["source"])
    assert all(text in shipping.page_content for text in ("4,90", "49", "2-4"))
    registry, client = Registry(), get_chroma_client()
    version = ingest(registry=registry, client=client)
    manifest = registry.manifest(version)
    validate(client.get_collection(version), manifest, registry.owner)
    assert {row["id"] for row in manifest["records"]} == {
        chunk.metadata["chunk_id"] for chunk in split_documents(docs)
    }
    assert {row["metadata"]["source"] for row in manifest["records"]} == {
        doc.metadata["source"] for doc in docs
    }
    assert ingest(registry=registry, client=client) == version
    assert len(client.list_collections()) == 1
    result = asyncio.run(answer("RAG", None))
    assert result.sources and result.tools_used == ["cerca_informazioni_negozio"]
    assert all(
        source["url"] in {doc.metadata["source"] for doc in docs} for source in result.sources
    )
    counters = httpx.get("http://upstream:9000/admin/counters").json()
    assert counters["embeddings"] > 0 and counters["chat"] == 2
    print(
        "__ISSUE25__"
        + json.dumps(
            {
                "status": "PASS",
                "pages": 3,
                "products": 6,
                "chunks": len(manifest["records"]),
                "version": version,
                "sources": sorted({doc.metadata["source"] for doc in docs}),
                "idempotent_ingestion": True,
                "synthetic_provider_calls": counters,
                "external_provider_calls": 0,
                "answer_quality_measured": False,
            }
        )
    )


if __name__ == "__main__":
    main()
