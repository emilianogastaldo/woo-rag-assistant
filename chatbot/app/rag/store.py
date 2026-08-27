"""Factory condivisa per il vector store ChromaDB.

Usata dalla pipeline di ingestion (scrittura), dalla catena RAG (lettura) e dallo
script di eval, così embedding, host, spazio metrico e nome della collection
restano un'unica fonte di verità.
"""
from __future__ import annotations

import chromadb
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from app.config import settings

# Distanza coseno invece della L2 di default: il punteggio resta in [0, 2] ed è
# interpretabile (0 = identico), quindi la soglia di pertinenza del RAG è
# confrontabile tra collection diverse. Vedi docs DEC-005.
COLLECTION_METADATA = {"hnsw:space": "cosine"}


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)


def get_chroma_client() -> chromadb.api.ClientAPI:
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


def get_vector_store(
    client: chromadb.api.ClientAPI | None = None,
    collection_name: str | None = None,
) -> Chroma:
    return Chroma(
        client=client or get_chroma_client(),
        collection_name=collection_name or settings.chroma_collection,
        embedding_function=get_embeddings(),
        collection_metadata=COLLECTION_METADATA,
    )
