"""Wheel packaging and dependency readiness contracts, with network blocked."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from zipfile import ZipFile

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rag.versions import VersionError


def test_wheel_contains_and_imports_every_app_subpackage(tmp_path):
    source = Path(__file__).resolve().parents[1]
    build = tmp_path / "project"
    build.mkdir()
    shutil.copy(source / "pyproject.toml", build)
    shutil.copytree(source / "app", build / "app", ignore=shutil.ignore_patterns("__pycache__"))
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG"}}
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation"],
                   cwd=build, env=env, check=True, capture_output=True, timeout=60)
    wheel, = (build / "dist").glob("*.whl")
    with ZipFile(wheel) as archive:
        expected = {str(p.relative_to(build)) for p in (build / "app").rglob("*.py")}
        assert expected <= set(archive.namelist())
    target = tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
                    "--target", str(target), str(wheel)],
                   env=env, check=True, capture_output=True, timeout=60)
    script = '''import app, importlib, pkgutil, pathlib
root = pathlib.Path("installed").resolve()
modules = [app] + [importlib.import_module(m.name)
                  for m in pkgutil.walk_packages(app.__path__, "app.")]
assert len(modules) >= 20
assert all(pathlib.Path(m.__file__).is_relative_to(root) for m in modules)
'''
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
                   env={**env, "PYTHONPATH": str(target)},
                   check=True, capture_output=True, timeout=60)


@pytest.mark.parametrize("error", [VersionError("missing"), httpx.ConnectError("down"),
                                  TimeoutError(), ValueError("malformed")])
def test_readiness_fails_without_breaking_liveness(monkeypatch, error):
    monkeypatch.setattr("app.main.check_readiness", AsyncMock(side_effect=error))
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_readiness_recovers(monkeypatch):
    monkeypatch.setattr("app.main.check_readiness", AsyncMock(return_value=None))
    assert TestClient(app).get("/ready").json() == {"status": "ready"}


@pytest.mark.parametrize("fault", [None, "woo", "count", "dimension", "owner", "malformed"])
async def test_readiness_checks_actual_dependency_responses(tmp_path, monkeypatch, fault):
    from langchain_core.documents import Document

    from app.config import settings
    from app.rag.chunks import split_documents
    from app.rag.versions import Registry, digest, make_manifest
    from app.readiness import check_readiness

    monkeypatch.setattr(settings, "knowledge_state_dir", str(tmp_path))
    registry = Registry()
    manifest = make_manifest(split_documents([Document(
        page_content="Spedizione", metadata={"source": "https://test.invalid", "title": "Test",
                                            "type": "page"})]),
        model=settings.embedding_model, dimensions=settings.embedding_dimensions,
        chunk_size=800, chunk_overlap=120)
    name = registry.name(manifest)
    registry.write(f"{name}.json", manifest)
    registry.write("active.json", {"active": name, "previous": None})
    metadata = {"owner": registry.owner, "manifest": digest(manifest), "hnsw:space": "cosine",
                "model": settings.embedding_model, "dimensions": settings.embedding_dimensions}
    if fault == "dimension":
        metadata["dimensions"] = 1
    if fault == "owner":
        metadata["owner"] = "other"

    def handler(request):
        if request.url.path.endswith("/types/product"):
            return httpx.Response(200, json=[] if fault == "woo" else {"slug": "product"})
        if request.url.path.endswith("/count"):
            return httpx.Response(200, json=0 if fault == "count" else 1)
        return httpx.Response(200, json=[] if fault == "malformed" else
                              {"id": "test-collection", "metadata": metadata})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    if fault:
        with pytest.raises(VersionError):
            await check_readiness()
    else:
        await check_readiness()
