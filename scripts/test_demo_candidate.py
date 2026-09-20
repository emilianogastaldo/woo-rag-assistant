"""Budget checks use only synthetic text and HTTP MockTransport, never a provider."""
from contextlib import nullcontext
from unittest.mock import AsyncMock, Mock

import demo_candidate as runner
import httpx
import pytest
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from evals.network import offline_network


@pytest.fixture(autouse=True)
def no_external_network():
    with offline_network():
        yield


def request(**overrides):
    body = {"input": ["synthetic text"], "model": "text-embedding-3-small", "dimensions": 1536}
    body.update(overrides)
    return httpx.Request("POST", "https://api.openai.com/v1/embeddings", json=body)


def test_gate_allows_only_one_matching_request():
    gate = runner.OneEmbeddingRequest(["synthetic text"])
    gate(request())
    with pytest.raises(runner.CandidateBudgetError):
        gate(request())
    assert gate.attempts == 1


@pytest.mark.parametrize("overrides", [
    {"input": ["unexpected data"]}, {"model": "other"}, {"dimensions": 8},
])
def test_gate_blocks_changed_payload_before_dispatch(overrides):
    gate = runner.OneEmbeddingRequest(["synthetic text"])
    with pytest.raises(runner.CandidateBudgetError):
        gate(request(**overrides))
    assert gate.attempts == 0


@pytest.mark.parametrize("url", [
    "http://api.openai.com/v1/embeddings", "https://example.invalid/v1/embeddings",
    "https://api.openai.com/v1/embeddings?extra=1", "https://api.openai.com/v1/chat/completions",
])
def test_gate_blocks_other_endpoints(url):
    gate = runner.OneEmbeddingRequest(["synthetic text"])
    with pytest.raises(runner.CandidateBudgetError):
        gate(httpx.Request("POST", url, content=request().content))
    assert gate.attempts == 0


def test_sdk_429_is_not_retried_and_hook_precedes_network():
    calls = []

    def respond(req):
        calls.append(req)
        return httpx.Response(429, json={"error": {"message": "synthetic"}})

    gate = runner.OneEmbeddingRequest(["synthetic text"])
    with httpx.Client(transport=httpx.MockTransport(respond),
                      event_hooks={"request": [gate]}) as client:
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small", dimensions=1536, api_key="synthetic",
            check_embedding_ctx_length=False, max_retries=0, http_client=client,
        )
        from openai import RateLimitError
        with pytest.raises(RateLimitError):
            embeddings.embed_documents(["synthetic text"])
        with pytest.raises(runner.CandidateBudgetError, match="budget exhausted"):
            embeddings.embed_documents(["synthetic text"])
    assert len(calls) == gate.attempts == 1


def test_denied_consent_never_initializes_registry(monkeypatch):
    registry = Mock()
    monkeypatch.setattr(runner, "Registry", registry)
    with pytest.raises(runner.CandidateBudgetError):
        runner.build_candidate(allow_provider=False, expected_digest="0" * 64)
    registry.assert_not_called()


def synthetic_manifest():
    chunks = runner.split_documents([Document(page_content="synthetic text", metadata={
        "source": "https://example.invalid/policy", "title": "Synthetic", "type": "page",
    })])
    manifest = runner.make_manifest(chunks, model="text-embedding-3-small", dimensions=1536,
                                    chunk_size=800, chunk_overlap=120)
    return chunks, manifest


def test_changed_corpus_and_token_budget_fail_closed(monkeypatch):
    _, manifest = synthetic_manifest()
    encoder = Mock()
    encoder.encode.return_value = [1] * 2001
    monkeypatch.setattr(runner.tiktoken, "encoding_for_model", Mock(return_value=encoder))
    with pytest.raises(runner.CandidateBudgetError, match="differs"):
        runner.check_manifest(manifest, "0" * 64, 2000, 12)
    encoder.encode.assert_not_called()
    with pytest.raises(runner.CandidateBudgetError, match="Token"):
        runner.check_manifest(manifest, runner.digest(manifest), 2000, 12)


def test_build_is_candidate_only_and_requires_unchanged_pointer(monkeypatch):
    chunks, manifest = synthetic_manifest()
    registry = Mock()
    registry.lock.return_value = nullcontext()
    registry.read_state.return_value = {"active": None, "previous": None}
    registry.build.return_value = "synthetic-candidate"
    monkeypatch.setattr(runner, "Registry", Mock(return_value=registry))
    monkeypatch.setattr(runner, "gather_documents", AsyncMock(return_value=chunks))
    monkeypatch.setattr(runner, "split_documents", Mock(return_value=chunks))
    monkeypatch.setattr(runner, "check_manifest", Mock(return_value=(["synthetic text"], 2)))
    monkeypatch.setattr(runner, "get_chroma_client", Mock(return_value=object()))
    monkeypatch.setattr(runner, "OpenAIEmbeddings", Mock())
    result = runner.build_candidate(allow_provider=True, expected_digest=runner.digest(manifest))
    assert registry.build.call_args.kwargs["promote"] is False
    registry.promote.assert_not_called()
    assert result["active_unchanged"] and result["embedding_attempts"] == 0
    registry.read_state.side_effect = [{"active": None, "previous": None},
                                       {"active": "changed", "previous": None}]
    with pytest.raises(runner.CandidateBudgetError, match="Active state"):
        runner.build_candidate(allow_provider=True, expected_digest=runner.digest(manifest))
