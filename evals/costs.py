"""Preventivo conservativo e costo da usage; nessuna richiesta al provider."""

from app.config import settings
from evals.fixtures import documents

# USD / milione token, tariffe standard verificate 2026-11-03, senza sconti cache.
# https://developers.openai.com/api/docs/models/gpt-4.1-mini
# https://developers.openai.com/api/docs/models/text-embedding-3-small
PRICES = {"gpt-4.1-mini": (0.40, 1.60), "text-embedding-3-small": 0.02}
EMBEDDING_INPUT_MAX_BYTES = 8191
SETUP_TIMEOUT_SECONDS = 30


def token_cost(input_tokens, output_tokens, embedding_tokens):
    generation = PRICES.get(settings.openai_model)
    embedding = PRICES.get(settings.embedding_model)
    if not isinstance(generation, tuple) or not isinstance(embedding, float):
        return None
    return round((input_tokens * generation[0] + output_tokens * generation[1]
                  + embedding_tokens * embedding) / 1_000_000, 8)


def cost_estimate(turns, generation_requests, embedding_requests):
    # Byte-level tokenizers cannot emit more input tokens than UTF-8 bytes.
    corpus_bytes = sum(len(doc.page_content.encode()) for doc in documents())
    embedding_max = corpus_bytes + (embedding_requests - 1) * EMBEDDING_INPUT_MAX_BYTES
    input_max = turns * settings.model_token_budget
    output_max = generation_requests * settings.model_max_output_tokens
    return {
        "generation_input_tokens_max": input_max,
        "embedding_input_tokens_max": embedding_max,
        "estimated_usd_max": token_cost(input_max, output_max, embedding_max),
        "provider_work_seconds_max": (
            SETUP_TIMEOUT_SECONDS + turns * settings.request_deadline_seconds
        ),
        "pricing_date": "2026-11-03",
        "billing_cap": False,
    }


def measured_cost(rows, store, generation_requests_without_usage):
    embeddings = getattr(store, "embeddings", None)
    embedding_tokens = getattr(embeddings, "input_tokens", 0)
    missing = getattr(embeddings, "requests_without_usage", 0)
    missing += generation_requests_without_usage
    input_tokens = sum(row["metrics"]["input_tokens"] for row in rows)
    output_tokens = sum(row["metrics"]["output_tokens"] for row in rows)
    return {
        "currency": "USD",
        "generation_input_tokens": input_tokens,
        "generation_output_tokens": output_tokens,
        "embedding_input_tokens": embedding_tokens,
        "requests_without_usage": missing,
        "usage_complete": embeddings is not None and missing == 0,
        "estimated_usd_observed": token_cost(input_tokens, output_tokens, embedding_tokens),
        "billing_cap": False,
    }
