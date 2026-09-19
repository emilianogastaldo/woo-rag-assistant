"""Bounded live runner exercised exclusively with local vectors and network blocked."""
import pytest
from evals import run_embedding_smoke as smoke
from evals.retrieval_fixtures import LocalEmbeddings


async def test_installed_sdk_constructs_bounded_client_without_network(monkeypatch):
    from types import SimpleNamespace

    from openai.resources.embeddings import AsyncEmbeddings

    calls = []

    async def create(self, **kwargs):
        calls.append(kwargs)
        assert self._client.max_retries == 0
        assert str(self._client.base_url) == "https://api.openai.com/v1/"
        return SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[1, 0])],
            usage=SimpleNamespace(total_tokens=1),
        )

    monkeypatch.setattr(smoke.settings, "openai_api_key", "synthetic")
    monkeypatch.setattr(AsyncEmbeddings, "create", create)
    assert await smoke.fetch_vectors(["synthetic"]) == ([[1, 0]], 1)
    assert calls == [{"model": smoke.MODEL, "input": ["synthetic"], "encoding_format": "float"}]


def test_estimate_and_consent_do_not_construct_provider(monkeypatch, capsys):
    async def forbidden(*args, **kwargs):
        pytest.fail("provider must not be constructed")

    monkeypatch.setattr(smoke, "fetch_vectors", forbidden)
    assert smoke.main(["--estimate"]) == 0
    assert "embedding_requests_max" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        smoke.main(["--live"])
    with pytest.raises(ValueError):
        smoke.plan(0.000000001)
    with pytest.raises(ValueError):
        smoke.plan(1)


async def test_smoke_python_consent_and_one_batch_shared_across_strategies(monkeypatch):
    calls = []

    async def local(inputs):
        calls.append(inputs)
        return LocalEmbeddings().embed_documents(inputs), 800

    monkeypatch.setattr(smoke, "fetch_vectors", local)
    with pytest.raises(ValueError, match="allow-external"):
        await smoke.smoke()
    assert calls == []
    report = await smoke.smoke(allow_external=True)
    assert len(calls) == 1 and len(report["rows"]) == 36
    assert report["provider"]["embedding_requests"] == 1
    assert report["provider"]["embedding_tokens_measured"] == 800
    assert report["provider"]["cost_usd_estimated_from_measured_tokens"] == 0.000016
    assert len({r["id"] for r in report["rows"]}) == 6


async def test_budget_exceeded_before_any_provider_call(monkeypatch):
    monkeypatch.setattr(smoke, "MAX_INPUT_BYTES", 1)
    async def forbidden(inputs):
        pytest.fail("provider must not be called")

    monkeypatch.setattr(smoke, "fetch_vectors", forbidden)
    with pytest.raises(ValueError, match="budget exceeded"):
        await smoke.smoke(allow_external=True)


def test_unplanned_query_cannot_trigger_a_paid_retry():
    cache = smoke.CachedEmbeddings(["known"], [[1, 0]])
    with pytest.raises(KeyError):
        cache.embed_query("unexpected")
