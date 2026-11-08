from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app import ingest
from app.config import Settings, settings
from app.rag.versions import VersionError
from app.tools.woo_client import WooClient


def page(identifier, slug, **overrides):
    return {"id": identifier, "slug": slug, "status": "publish",
            "title": {"rendered": slug}, "content": {"rendered": "Public policy"},
            "link": f"https://store.test/{slug}", **overrides}


def pages_http(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(ingest.httpx, "AsyncClient", lambda **kw: client_type(
        transport=httpx.MockTransport(handler), **kw
    ))


def test_selection_config():
    config = Settings(_env_file=None, knowledge_page_slugs="about, shipping,about")
    assert config.knowledge_page_slug_list == ["about", "shipping"]
    assert Settings(_env_file=None, knowledge_page_slugs="").knowledge_page_slug_list == []
    for values in [{"knowledge_page_slugs": "../secret"},
                   {"knowledge_page_slugs": "", "knowledge_include_products": False},
                   {"knowledge_max_pages": 0}]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **values)


async def test_selected_pages_paginate_and_exclude_private_or_protected(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_page_slugs", "about,payments,private,protected")
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        rows = [page(1, "about"), page(2, "private", status="private")] if len(seen) == 1 else [
            page(3, "payments"),
            page(4, "protected", content={"rendered": "secret", "protected": True}),
            page(5, "unselected"),
        ]
        return httpx.Response(200, json=rows, headers={"X-WP-TotalPages": "2"})

    pages_http(monkeypatch, handler)
    docs = await ingest.fetch_page_docs()
    assert [d.metadata["title"] for d in docs] == ["about", "payments"]
    assert [p["page"] for p in seen] == ["1", "2"]
    assert all(p["status"] == "publish" for p in seen)


async def test_empty_page_selection_does_not_fetch(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_page_slugs", "")
    pages_http(monkeypatch, lambda req: pytest.fail("Unexpected fetch"))
    assert await ingest.fetch_page_docs() == []


@pytest.mark.parametrize("case", ["limit", "duplicate", "invalid"])
async def test_incomplete_page_fetch_fails_instead_of_truncating(monkeypatch, case):
    monkeypatch.setattr(settings, "knowledge_max_pages", 2)
    pages_http(monkeypatch, lambda req: httpx.Response(
        200, json={} if case == "invalid" else [page(1, "spedizioni")],
        headers={"X-WP-TotalPages": "3" if case == "limit" else "2"},
    ))
    with pytest.raises(VersionError):
        await ingest.fetch_page_docs()


async def test_product_corpus_filters_visibility_and_excludes_live_fields(monkeypatch):
    woo = AsyncMock()
    woo.get_all.return_value = [
        {"name": "Public", "description": "Description", "price": "99.99", "stock_quantity": 999},
        {"name": "Hidden", "description": "Secret", "catalog_visibility": "hidden"},
        {"name": "Private", "description": "Secret", "status": "private"},
    ]
    woo.__aenter__.return_value = woo
    monkeypatch.setattr(ingest, "WooClient", lambda: woo)
    docs = await ingest.fetch_product_docs()
    assert len(docs) == 1 and docs[0].page_content == "Public\n\nDescription"
    assert woo.get_all.call_args.kwargs["max_pages"] == settings.knowledge_max_pages
    monkeypatch.setattr(settings, "knowledge_include_products", False)
    assert await ingest.fetch_product_docs() == []
    assert woo.get_all.await_count == 1


async def test_woo_snapshot_page_limit_and_repeated_page(monkeypatch):
    woo = WooClient()
    woo.get = AsyncMock(return_value=httpx.Response(
        200, json=[{"id": 1}], headers={"X-WP-TotalPages": "2"}
    ))
    try:
        with pytest.raises(ValueError, match="limit"):
            await woo.get_all("products", max_pages=1)
        from app.resilience import RecoverableFailure
        with pytest.raises(RecoverableFailure):
            await woo.get_all("products", max_pages=2)
    finally:
        await woo.aclose()


def test_preview_never_builds_embeddings_or_registry(monkeypatch, capsys):
    from langchain_core.documents import Document

    monkeypatch.setattr(ingest, "gather_documents", AsyncMock(return_value=[Document(
        page_content="Policy",
        metadata={"source": "https://store.test/about", "title": "About", "type": "page"}
    )]))
    monkeypatch.setattr(ingest, "get_embeddings", lambda: pytest.fail("Provider called"))
    monkeypatch.setattr(ingest, "ingest", lambda **kwargs: pytest.fail("Build called"))
    monkeypatch.setattr("sys.argv", ["ingest", "preview"])
    ingest.main()
    assert "https://store.test/about" in capsys.readouterr().out
