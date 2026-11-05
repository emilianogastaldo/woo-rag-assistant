"""Dipendenze live: solo OpenAI, corpus e Woo sintetici. Import dopo opt-in."""

import math

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from app.config import settings
from evals.costs import EMBEDDING_INPUT_MAX_BYTES, SETUP_TIMEOUT_SECONDS
from evals.fixtures import documents


class MeasuredEmbeddings:
    """Conserva usage numerico, mai input o risposte grezze nei report."""

    def __init__(self):
        self.input_tokens = 0
        self.requests_without_usage = 0
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key, max_retries=0,
            timeout=SETUP_TIMEOUT_SECONDS,
            base_url="https://api.openai.com/v1",
        )

    async def aclose(self):
        await self.client.close()

    async def aembed_documents(self, texts):
        if any(len(text.encode()) > EMBEDDING_INPUT_MAX_BYTES for text in texts):
            raise ValueError("synthetic embedding input exceeds the preflight limit")
        self.requests_without_usage += 1
        result = await self.client.embeddings.create(
            model=settings.embedding_model, input=texts, encoding_format="float",
        )
        tokens = getattr(getattr(result, "usage", None), "total_tokens", None)
        if isinstance(tokens, int) and tokens >= 0:
            self.input_tokens += tokens
            self.requests_without_usage -= 1
        return [item.embedding for item in sorted(result.data, key=lambda item: item.index)]

    async def aembed_query(self, text):
        return (await self.aembed_documents([text]))[0]


class MeasuredModel:
    def __init__(self, model):
        self.model = model
        self.requests_without_usage = 0

    async def ainvoke(self, messages):
        self.requests_without_usage += 1
        result = await self.model.ainvoke(messages)
        usage = result.usage_metadata or {}
        if all(isinstance(usage.get(key), int) and usage[key] >= 0
               for key in ("input_tokens", "output_tokens")):
            self.requests_without_usage -= 1
        return result


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
    embeddings = MeasuredEmbeddings()
    docs = documents()
    try:
        vectors = await embeddings.aembed_documents([doc.page_content for doc in docs])
    except BaseException:
        await embeddings.aclose()
        raise
    return LiveStore(embeddings, docs, vectors)


def build_model(toolset):
    return MeasuredModel(ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url="https://api.openai.com/v1",
        temperature=0,
        max_retries=0,
        timeout=settings.provider_timeout_seconds,
        max_tokens=settings.model_max_output_tokens,
    ).bind_tools(toolset.tools, parallel_tool_calls=False))
