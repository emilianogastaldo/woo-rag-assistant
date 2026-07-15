"""Pipeline di ingestion offline: WooCommerce/WP -> ChromaDB.

Esecuzione: `docker compose run --rm ingest`

Flusso:
  1. Legge prodotti (WC REST, OAuth) e pagine informative (WP REST, pubbliche).
  2. Estrae testo pulito dall'HTML (BeautifulSoup).
  3. Chunking (RecursiveCharacterTextSplitter) con metadati per la citazione fonti.
  4. Embedding OpenAI -> scrittura idempotente nella collection ChromaDB.

Solo conoscenza *statica*: descrizioni prodotti e pagine di policy/FAQ. Lo stato
dinamico (stock, ordini) è servito dai tool, non dal RAG.
"""
from __future__ import annotations

import asyncio

import httpx
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.rag.store import get_chroma_client, get_vector_store
from app.tools.woo_client import WooClient

# Pagine WP da includere come knowledge base: esclude quelle di sistema di
# WooCommerce (cart, checkout, shop, my-account) e la Sample Page di WordPress.
KNOWLEDGE_PAGE_SLUGS = ("spedizioni", "resi-e-rimborsi", "domande-frequenti")


def html_to_text(html: str | None) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(separator="\n").strip()


async def fetch_product_docs() -> list[Document]:
    woo = WooClient()
    products = await woo.get_all("products", {"status": "publish"})
    docs: list[Document] = []
    for p in products:
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
    # Le pagine WP sono pubbliche: nessuna firma OAuth necessaria.
    root = settings.wc_base_url.split("/wp-json/")[0]
    url = f"{root}/wp-json/wp/v2/pages"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params={"per_page": 100, "status": "publish"})
        response.raise_for_status()
        pages = response.json()

    docs: list[Document] = []
    for pg in pages:
        if pg.get("slug") not in KNOWLEDGE_PAGE_SLUGS:
            continue
        title = html_to_text(pg["title"]["rendered"])
        text = html_to_text(pg["content"]["rendered"])
        docs.append(
            Document(
                page_content=f"{title}\n\n{text}",
                metadata={"source": pg.get("link", ""), "title": title, "type": "page"},
            )
        )
    return docs


async def gather_documents() -> list[Document]:
    products, pages = await asyncio.gather(fetch_product_docs(), fetch_page_docs())
    print(f"[ingest] {len(products)} prodotti, {len(pages)} pagine")
    return products + pages


def main() -> None:
    print("[ingest] Raccolta documenti da WooCommerce/WP...")
    docs = asyncio.run(gather_documents())
    if not docs:
        print("[ingest] Nessun documento trovato: interrompo.")
        return

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    chunks = splitter.split_documents(docs)
    print(f"[ingest] {len(chunks)} chunk dopo lo splitting")

    # Reset idempotente: azzera la collection prima di reindicizzare.
    client = get_chroma_client()
    try:
        client.delete_collection(settings.chroma_collection)
        print(f"[ingest] collection '{settings.chroma_collection}' azzerata")
    except Exception:
        pass

    store = get_vector_store(client=client)
    store.add_documents(chunks)
    print(f"[ingest] Indicizzati {len(chunks)} chunk in '{settings.chroma_collection}'. Fatto.")


if __name__ == "__main__":
    main()
