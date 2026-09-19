"""Identità dei chunk condivisa da ingestion, retrieval ed evaluation."""
from __future__ import annotations

import hashlib
import json

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings


def chunk_id(document: Document) -> str:
    """SHA-256 v1 di metadati della fonte, offset e testo esatti (UTF-8)."""
    meta = document.metadata
    identity = [
        "v1", meta.get("source", ""), meta.get("title", ""), meta.get("type", ""),
        meta.get("start_index"), document.page_content,
    ]
    payload = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return "chunk-v1-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verified_chunk_id(document: Document) -> str | None:
    """Scarta indici legacy o metadati/contenuti incoerenti: serve reingestion."""
    meta = document.metadata
    offset = meta.get("start_index")
    if (
        not all(isinstance(meta.get(key), str) and meta[key] for key in ("source", "title", "type"))
        or type(offset) is not int
        or offset < 0
        or not document.page_content.strip()
    ):
        return None
    expected = chunk_id(document)
    return expected if meta.get("chunk_id") == expected else None


def split_documents(
    documents: list[Document], *, chunk_size: int | None = None, chunk_overlap: int | None = None,
) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size if chunk_size is None else chunk_size,
        chunk_overlap=settings.chunk_overlap if chunk_overlap is None else chunk_overlap,
        add_start_index=True,
    )
    unique: dict[str, Document] = {}
    for document in splitter.split_documents(documents):
        identifier = chunk_id(document)
        document.metadata["chunk_id"] = identifier
        document.id = identifier
        unique.setdefault(identifier, document)
    return list(unique.values())
