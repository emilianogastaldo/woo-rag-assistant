"""Failure and concurrency contracts; no network and no persistent Chroma data."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import Mock

import pytest
from chromadb.errors import NotFoundError
from langchain_core.documents import Document

from app import ingest
from app.config import RetrievalConfig, settings
from app.rag.chain import KnowledgeBase
from app.rag.chunks import split_documents
from app.rag.reader import KnowledgeReader
from app.rag.versions import Registry, VersionError, make_manifest, validate


def chunks(text="Spedizione versione A"):
    return split_documents([Document(page_content=text, metadata={
        "source": "https://synthetic.invalid/spedizioni", "title": "Spedizioni", "type": "page",
    })])


class Collection:
    def __init__(self, metadata):
        self.metadata = metadata
        self.rows = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
        self.fail_write = False

    def add(self, **rows):
        if self.fail_write:
            raise RuntimeError("write failure")
        self.rows = deepcopy(rows)

    def count(self):
        return len(self.rows["ids"])

    def get(self, **kwargs):
        return deepcopy(self.rows)

    def query(self, **kwargs):
        return {"ids": [self.rows["ids"][:1]], "distances": [[0.0]]}


class Client:
    def __init__(self):
        self.collections = {}
        self.fail_write = False

    def get_collection(self, name):
        if name not in self.collections:
            raise NotFoundError(name)
        return self.collections[name]

    def create_collection(self, name, metadata, **kwargs):
        assert name not in self.collections
        collection = Collection(metadata)
        collection.fail_write = self.fail_write
        self.collections[name] = collection
        return collection

    def delete_collection(self, name):
        del self.collections[name]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "knowledge_state_dir", str(tmp_path))
    monkeypatch.setattr(settings, "embedding_dimensions", 3)
    return Registry(), Client(), Mock(embed_documents=lambda texts: [[1., 0., 0.] for _ in texts])


def build(setup, text="Spedizione versione A", **kwargs):
    registry, client, embeddings = setup
    with registry.lock("admin"):
        return registry.build(client, chunks(text), embeddings, **kwargs)


def test_determinism_idempotence_and_no_empty_switch(setup):
    registry, client, _ = setup
    a = build(setup)
    assert build(setup) == a
    assert len(client.collections) == 1
    b = build(setup, "Spedizione versione B", promote=False)
    assert registry.read_state()["active"] == a
    validate(client.get_collection(b), registry.manifest(b), registry.owner)
    registry.promote(client, b)
    assert registry.read_state() == {"active": b, "previous": a}
    assert {v["role"] for v in registry.status()["versions"]} == {"active", "previous"}
    registry.rollback(client, a)
    assert registry.read_state() == {"active": a, "previous": b}
    with pytest.raises(VersionError):
        registry.rollback(client, a)


@pytest.mark.parametrize("failure", ["fetch", "empty", "embedding", "dimension", "write"])
def test_ingestion_failures_preserve_active(setup, monkeypatch, failure):
    registry, client, embeddings = setup
    a = build(setup)

    async def gather():
        if failure == "fetch":
            raise RuntimeError("fetch failure")
        return [] if failure == "empty" else [Document(
            page_content="version B", metadata=chunks()[0].metadata)]

    monkeypatch.setattr(ingest, "gather_documents", gather)
    if failure == "embedding":
        embeddings.embed_documents = Mock(side_effect=RuntimeError("embedding failure"))
    if failure == "dimension":
        embeddings.embed_documents = lambda texts: [[1.] for _ in texts]
    client.fail_write = failure == "write"
    with pytest.raises((RuntimeError, VersionError)):
        ingest.ingest(registry=registry, client=client, embeddings=embeddings)
    assert registry.read_state()["active"] == a
    assert client.get_collection(a).count() > 0
    if failure == "write":
        orphan = next(n for n in client.collections if n != a)
        registry.cleanup(client, orphan)
        assert set(client.collections) == {a}


@pytest.mark.parametrize("failure",
                         ["count", "metadata", "id", "text", "dimension", "nan", "smoke"])
def test_validation_rejects_bad_candidate_without_promotion(setup, failure):
    registry, client, _ = setup
    a = build(setup)
    b = build(setup, "Spedizione versione B", promote=False)
    collection = client.get_collection(b)
    if failure == "count":
        collection.count = lambda: 999
    elif failure == "metadata":
        collection.rows["metadatas"][0]["source"] = "bad"
    elif failure == "id":
        collection.rows["ids"][0] = "bad"
    elif failure == "text":
        collection.rows["documents"][0] = "bad"
    elif failure == "dimension":
        collection.rows["embeddings"][0] = [1.]
    elif failure == "nan":
        collection.rows["embeddings"][0][0] = float("nan")
    else:
        collection.query = lambda **kwargs: {"ids": [["bad"]], "distances": [[0.]]}
    with pytest.raises(VersionError):
        registry.promote(client, b)
    assert registry.read_state()["active"] == a


def test_cleanup_protects_active_previous_foreign_and_pinned(setup):
    registry, client, _ = setup
    a = build(setup)
    b = build(setup, "version B")
    c = build(setup, "version C", promote=False)
    for target in (a, b, "woo_knowledge", "../active.json"):
        with pytest.raises(VersionError):
            registry.cleanup(client, target)
    with registry.snapshot():
        with pytest.raises(VersionError):
            registry.cleanup(client, c)
    client.get_collection(c).metadata["owner"] = "foreign"
    with pytest.raises(VersionError):
        registry.cleanup(client, c)
    client.get_collection(c).metadata["owner"] = registry.owner
    registry.cleanup(client, c)
    assert set(client.collections) == {a, b}


def test_concurrent_admin_and_collision_fail_closed(setup):
    registry, client, _ = setup
    with registry.lock("admin"):
        with pytest.raises(VersionError):
            build(setup)
    a = build(setup)
    client.get_collection(a).metadata["manifest"] = "collision"
    with pytest.raises(VersionError):
        build(setup)
    assert client.get_collection(a).count() == 1


def test_manifest_order_and_configuration(setup):
    docs = chunks() + chunks("Spedizione B")
    config = dict(model="test", dimensions=3, chunk_size=800, chunk_overlap=120)
    a = make_manifest(docs, **config)
    assert a == make_manifest(list(reversed(docs)), **config)
    assert a != make_manifest(docs, **{**config, "model": "different"})
    with pytest.raises(VersionError):
        make_manifest(docs + docs, **config)


async def test_search_pins_generation_across_promotion_and_concurrent_search(setup):
    registry, client, _ = setup
    a = build(setup)
    b = build(setup, "Spedizione versione B", promote=False)
    entered, release = asyncio.Event(), asyncio.Event()

    class Reader(KnowledgeReader):
        async def aget(self):
            name = self._snapshot.get()
            if name == a:
                entered.set()
                await release.wait()
            return client.get_collection(name).get()

        async def asimilarity_search_with_score(self, query, k=4):
            row = client.get_collection(self._snapshot.get()).rows
            return [(Document(page_content=row["documents"][0], metadata=row["metadatas"][0]), 0.)]

    kb = KnowledgeBase(Reader(), config=RetrievalConfig(strategy="hybrid"))
    pending = asyncio.create_task(kb.search("Spedizione"))
    await entered.wait()
    registry.promote(client, b)
    second = await kb.search("Spedizione")
    release.set()
    first = await pending
    assert "versione A" in first.context and "versione B" in second.context
    assert set(first.chunks).isdisjoint(second.chunks)


def test_failed_atomic_replace_retains_pointer(setup, monkeypatch):
    import app.rag.versions as versions
    registry, client, _ = setup
    a = build(setup)
    b = build(setup, "Spedizione versione B", promote=False)
    monkeypatch.setattr(versions.os, "replace", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError):
        registry.promote(client, b)
    assert registry.read_state()["active"] == a


def test_cleanup_obsolete_valid_version_and_missing_remote_recovery(setup):
    registry, client, _ = setup
    a = build(setup)
    b = build(setup, "Spedizione versione B")
    c = build(setup, "Spedizione versione C")
    registry.cleanup(client, a)
    assert set(client.collections) == {b, c}
    orphan = build(setup, "Spedizione versione D", promote=False)
    client.delete_collection(orphan)
    registry.cleanup(client, orphan)
    assert not (registry.root / f"{orphan}.json").exists()
