"""Dipendenze live: solo OpenAI, corpus e Woo sintetici. Import dopo opt-in."""

import math

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import settings
from evals.fixtures import documents


class LiveStore:
    """Ricerca esatta coseno sul corpus fisso; nessuna collection Chroma modificata."""

    def __init__(self, embeddings, docs, vectors):
        self.embeddings = embeddings
        self.docs = docs
        self.vectors = vectors
        self.embedding_calls = 0

    def get(self, **kwargs):
        return {
            "ids": [doc.metadata["chunk_id"] for doc in self.docs],
            "documents": [doc.page_content for doc in self.docs],
            "metadatas": [doc.metadata for doc in self.docs],
        }

    async def asimilarity_search_with_score(self, query, k=4):
        self.embedding_calls += 1
        query_vector = await self.embeddings.aembed_query(query)
        query_norm = math.sqrt(sum(v * v for v in query_vector))
        hits = []
        for doc, vector in zip(self.docs, self.vectors, strict=True):
            dot = sum(a * b for a, b in zip(query_vector, vector, strict=True))
            norm = query_norm * math.sqrt(sum(v * v for v in vector))
            distance = 1 - dot / norm if norm else 1.0
            hits.append((doc, distance))
        return sorted(hits, key=lambda item: item[1])[:k]


async def prepare_store():
    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key,
        max_retries=0,
        request_timeout=30,
        chunk_size=64,
        check_embedding_ctx_length=False,
    )
    docs = documents()
    vectors = await embeddings.aembed_documents([doc.page_content for doc in docs])
    return LiveStore(embeddings, docs, vectors)


def build_model(toolset):
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
        max_retries=0,
        timeout=30,
        max_tokens=512,
    ).bind_tools(toolset.tools, parallel_tool_calls=False)
