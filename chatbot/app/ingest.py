"""Pipeline di ingestion offline: WooCommerce/WP -> ChromaDB.

Esecuzione: `docker compose run --rm ingest`

Flusso:
  1. Legge prodotti (WC REST, OAuth) e pagine informative (WP REST, pubbliche).
  2. Estrae testo pulito dall'HTML (BeautifulSoup).
  3. Chunking (RecursiveCharacterTextSplitter) con metadati per la citazione fonti.
  4. Embedding -> candidata immutabile, validation -> promozione atomica.

Solo conoscenza *statica*: descrizioni prodotti e pagine di policy/FAQ. Lo stato
dinamico (stock, ordini) è servito dai tool, non dal RAG.
"""
from __future__ import annotations

import argparse
import asyncio

import httpx
from bs4 import BeautifulSoup
from langchain_core.documents import Document

from app.config import settings
from app.rag.chunks import split_documents
from app.rag.store import get_chroma_client, get_embeddings
from app.rag.versions import Registry, VersionError
from app.tools.woo_client import WooClient


def html_to_text(html: str | None) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(separator="\n").strip()


async def fetch_product_docs() -> list[Document]:
    if not settings.knowledge_include_products:
        return []
    async with WooClient() as woo:
        products = await woo.get_all(
            "products", {"status": "publish"}, max_pages=settings.knowledge_max_pages
        )
    docs: list[Document] = []
    for p in products:
        if (p.get("status", "publish") != "publish"
                or p.get("catalog_visibility", "visible") not in {"visible", "catalog"}):
            continue
        body = "\n\n".join(
            filter(
                None,
                [html_to_text(p.get("short_description")), html_to_text(p.get("description"))],
            )
        )
        if not body:
            continue
        docs.append(
            Document(
                page_content=f"{p['name']}\n\n{body}",
                metadata={
                    "source": p.get("permalink", ""),
                    "title": p["name"],
                    "type": "product",
                    "sku": p.get("sku", ""),
                },
            )
        )
    return docs


async def fetch_page_docs() -> list[Document]:
    slugs = set(settings.knowledge_page_slug_list)
    if not slugs:
        return []
    root = settings.wc_base_url.split("/wp-json/")[0]
    url = f"{root}/wp-json/wp/v2/pages"
    pages: list[dict] = []
    seen: set[int] = set()
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        for page in range(1, settings.knowledge_max_pages + 1):
            response = await client.get(url, params={
                "per_page": 100, "page": page, "status": "publish", "slug": ",".join(sorted(slugs)),
            })
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list):
                raise VersionError("Invalid WordPress page response")
            for row in batch:
                if (not isinstance(row, dict) or type(row.get("id")) is not int
                        or row["id"] in seen):
                    raise VersionError("Invalid or repeated WordPress page")
                seen.add(row["id"])
            pages.extend(batch)
            total = response.headers.get("X-WP-TotalPages")
            if total is not None:
                if not total.isdigit() or int(total) > settings.knowledge_max_pages:
                    raise VersionError("Knowledge pages exceed configured limit")
                if page >= int(total):
                    break
            elif len(batch) < 100:
                break
        else:
            raise VersionError("Knowledge pages exceed configured limit")

    docs: list[Document] = []
    for pg in pages:
        if (pg.get("slug") not in slugs or pg.get("status") != "publish"
                or pg.get("content", {}).get("protected")):
            continue
        title = html_to_text(pg["title"]["rendered"])
        text = html_to_text(pg["content"]["rendered"])
        if not text:
            continue
        docs.append(Document(
            page_content=f"{title}\n\n{text}",
            metadata={"source": pg.get("link", ""), "title": title, "type": "page"},
        ))
    return docs


async def gather_documents() -> list[Document]:
    products, pages = await asyncio.gather(fetch_product_docs(), fetch_page_docs())
    print(f"[ingest] {len(products)} prodotti, {len(pages)} pagine")
    return products + pages


def ingest(*, registry=None, client=None, embeddings=None, promote=True):
    registry = registry or Registry()
    with registry.lock("admin"):
        docs = asyncio.run(gather_documents())
        if not docs:
            raise VersionError("Empty source corpus; active version preserved")
        return registry.build(client or get_chroma_client(), split_documents(docs),
                              embeddings or get_embeddings(), promote=promote)


def main() -> None:
    parser = argparse.ArgumentParser(description="Versioned ingestion and explicit recovery")
    parser.add_argument("action", nargs="?", default="build",
                        choices=["build", "promote", "rollback", "cleanup", "status", "preview"])
    parser.add_argument("--target", help="Exact collection name; no wildcard or automatic pruning")
    parser.add_argument("--candidate-only", action="store_true")
    args = parser.parse_args()
    registry = Registry()
    if args.action == "preview":
        docs = asyncio.run(gather_documents())
        print({"documents": len(docs), "chunks": len(split_documents(docs)),
               "sources": [doc.metadata["source"] for doc in docs]})
    elif args.action == "status":
        print(registry.status())
    elif args.action == "build":
        print(ingest(registry=registry, promote=not args.candidate_only))
    else:
        if not args.target:
            parser.error("--target is required")
        getattr(registry, args.action)(get_chroma_client(), args.target)
        print(f"{args.action}: completed")


if __name__ == "__main__":
    main()
