"""Real HTTP/Chroma/Woo checks. Runs only inside the audited internal network."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import pkgutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import httpx
import openai
from langchain_core.documents import Document

import app
from app.ingest import gather_documents
from app.rag.chunks import split_documents
from app.rag.store import get_chroma_client, get_embeddings
from app.rag.versions import Registry, VersionError, validate


def wait_ready(expected, *, base="http://api:8000", timeout=75):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            health = httpx.get(base + "/health", timeout=7)
            ready = httpx.get(base + "/ready", timeout=7)
            if health.status_code == 200 and ready.status_code == expected:
                return
        except httpx.HTTPError:
            pass  # Bounded startup polling only, never an administrative operation.
        time.sleep(0.3)
    raise AssertionError(f"readiness did not become {expected}")


def query(allowed, *, base="http://api:8000"):
    started = time.perf_counter()
    with httpx.Client(timeout=15) as client:
        response = client.post(base + "/chat", json={"message": "RAG"})
    response.raise_for_status()
    data = response.json()
    ids = {identifier for source in data["sources"] for identifier in source["chunk_ids"]}
    assert ids and any(ids <= generation for generation in allowed), "empty or mixed citations"
    assert all(f"[{identifier}]" in data["reply"] for identifier in ids)
    return (time.perf_counter() - started) * 1000


def expect_failure(call):
    try:
        call()
    except (VersionError, RuntimeError, openai.APIError):
        return
    raise AssertionError("operation unexpectedly succeeded")


def scenarios():
    registry, client, embeddings = Registry(), get_chroma_client(), get_embeddings()
    a = registry.read_state()["active"]
    assert a
    manifest_a = registry.manifest(a)
    validate(client.get_collection(a), manifest_a, registry.owner)
    ids_a = {r["id"] for r in manifest_a["records"]}
    docs = asyncio.run(gather_documents())
    assert {d.metadata["type"] for d in docs} == {"page", "product"}
    # Same source URLs, changed text: both lexical and vector IDs must switch together.
    docs_b = [Document(page_content=d.page_content.replace("versione A", "versione B"),
                       metadata=d.metadata) for d in docs]
    b_chunks = split_documents(docs_b)
    ids_b = {d.metadata["chunk_id"] for d in b_chunks}
    assert ids_a.isdisjoint(ids_b)
    wait_ready(200)
    wait_ready(200, base="http://dev:8000")
    timings = [query([ids_a]), query([ids_a], base="http://dev:8000")]
    # Real HTTP fetch and provider failures remain isolated to this ingestion process.
    failed_fetch = subprocess.run(
        ["python", "-m", "app.ingest"], capture_output=True, timeout=20,
        env={**os.environ, "WC_BASE_URL": "http://wordpress/wp-json/missing"})
    assert failed_fetch.returncode != 0 and registry.read_state()["active"] == a
    timings.append(query([ids_a]))
    with patch("app.config.settings.openai_base_url", "http://upstream:9000/missing"):
        with registry.lock("admin"):
            expect_failure(partial(registry.build, client, b_chunks, get_embeddings()))
    assert registry.read_state()["active"] == a
    timings.append(query([ids_a]))
    done = threading.Event()
    entered = threading.Event()
    release = threading.Event()
    observed = []

    def continuous_queries():
        while not done.is_set():
            observed.append(query([ids_a, ids_b]))

    class SlowEmbeddings:
        def embed_documents(self, texts):
            entered.set()
            assert release.wait(20)
            return embeddings.embed_documents(texts)

    def build_b():
        with registry.lock("admin"):
            return registry.build(client, b_chunks, SlowEmbeddings(), promote=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        poller = pool.submit(continuous_queries)
        try:
            pending = pool.submit(build_b)
            assert entered.wait(20)
            timings.append(query([ids_a]))
            # Separate interpreter: proves file locking across independent ingestion processes.
            collision = subprocess.run(["python", "-m", "app.ingest"], capture_output=True,
                                       timeout=20, text=True)
            assert collision.returncode != 0 and "already in progress" in collision.stderr
            release.set()
            b = pending.result(timeout=30)
            timings.append(query([ids_a]))
            registry.promote(client, b)
            timings.append(query([ids_b]))
            timings.append(query([ids_b], base="http://dev:8000"))
            registry.rollback(client, a)
            timings.append(query([ids_a]))
            # Bad manifest, ID, metadata and dimensions must prevent promotion on real Chroma.
            failed_targets = []
            for field in ("text", "metadata", "dimension", "write"):
                bad_chunks = split_documents([Document(
                    page_content="Spedizione guasto " + field, metadata=docs[0].metadata)])
                if field == "write":
                    from chromadb.api.models.Collection import Collection
                    original_add = Collection.add

                    def write_then_fail(self, original_add=original_add, **rows):
                        original_add(self, **rows)
                        raise RuntimeError("synthetic write failure after server commit")

                    before = {p.stem for p in registry.root.glob("kb-*.json")}
                    with patch.object(Collection, "add", write_then_fail), registry.lock("admin"):
                        expect_failure(partial(registry.build, client, bad_chunks, embeddings))
                    after = {p.stem for p in registry.root.glob("kb-*.json")}
                    target, = after - before
                else:
                    with registry.lock("admin"):
                        target = registry.build(client, bad_chunks, embeddings, promote=False)
                    collection = client.get_collection(target)
                    row = collection.get(include=["embeddings"])
                    if field == "text":
                        collection.update(ids=row["ids"], documents=["corrupted"],
                                          embeddings=row["embeddings"])
                    elif field == "metadata":
                        collection.update(ids=row["ids"], metadatas=[{"title": "corrupted"}])
                    else:
                        # The real server refuses wrong-dimensional writes before promotion.
                        try:
                            collection.update(ids=row["ids"], embeddings=[[1., 0.]])
                        except Exception as exc:
                            assert "dimension" in str(exc).lower()
                        else:
                            raise AssertionError("Chroma accepted wrong dimensions")
                        # Validation also rejects a mismatched manifest dimension.
                        invalid = {**registry.manifest(target), "dimensions": 2}
                        expect_failure(partial(validate, collection, invalid, registry.owner))
                    if field != "dimension":
                        expect_failure(partial(registry.promote, client, target))
                failed_targets.append(target)
                assert registry.read_state()["active"] == a
                timings.append(query([ids_a]))
            done.set()
            poller.result(timeout=20)
            for protected in (a, b):
                expect_failure(partial(registry.cleanup, client, protected))
            for target in failed_targets:
                with registry.snapshot():
                    expect_failure(partial(registry.cleanup, client, target))
                registry.cleanup(client, target)
            assert {c.name for c in client.list_collections()} == {a, b}
        finally:
            release.set()
            done.set()
            poller.result(timeout=20)
    assert len(observed) >= 3
    # Verify idempotent retry does not create a third generation.
    rerun = subprocess.run(["python", "-m", "app.ingest"], capture_output=True, timeout=30)
    assert rerun.returncode == 0
    assert registry.read_state()["active"] == a
    modules = [m.name for m in pkgutil.walk_packages(app.__path__, "app.")]
    for name in modules:
        module = importlib.import_module(name)
        assert "site-packages/app/" in module.__file__
    wheel, = Path("/wheels").glob("*.whl")
    with ZipFile(wheel) as archive:
        assert {"app/auth/session.py", "app/rag/versions.py", "app/tools/orders.py"} <= set(
            archive.namelist())
    assert not Path("/app/app").exists()
    counters = httpx.get("http://upstream:9000/admin/counters").json()
    report = {"status": "PASS", "schema_version": 1, "dataset": "issue7-synthetic-v1",
              "cases": ["standalone_wheel_imports", "real_woo_fetch", "manifest_validation",
                        "continuous_queries", "candidate_isolation", "concurrent_ingestion",
                        "promotion", "rollback", "validation_failure", "partial_write_failure",
                        "dimension_rejection", "cleanup_protection", "idempotence", "dev_http",
                        "http_fetch_failure", "http_embedding_failure"],
              "queries": len(observed) + len(timings), "latency_ms": timings + observed,
              "versions": [a, b], "provider_calls": counters, "external_calls": 0,
              "cost_measured_usd": 0}
    Path("/results/scenarios.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "latency_ms"}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["not-ready", "ready", "scenarios"], required=True)
    args = parser.parse_args()
    if args.phase == "scenarios":
        scenarios()
    else:
        wait_ready(200 if args.phase == "ready" else 503)
        print(f"{args.phase}: PASS")


if __name__ == "__main__":
    main()
