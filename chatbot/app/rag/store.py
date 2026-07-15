"""Factory condivisa per il vector store ChromaDB.

Usata sia dalla pipeline di ingestion (scrittura) sia dalla catena RAG (lettura),
così embedding, host e nome della collection restano un'unica fonte di verità.
"""
from __future__ import annotations

import chromadb
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from app.config import settings


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)


def get_chroma_client() -> chromadb.api.ClientAPI:
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


def get_vector_store(client: chromadb.api.ClientAPI | None = None) -> Chroma:
    return Chroma(
        client=client or get_chroma_client(),
        collection_name=settings.chroma_collection,
        embedding_function=get_embeddings(),
    )
