"""Immutable Chroma generations and a crash-safe, single-host POSIX registry.

All administrators and readers MUST share this directory. Locks are nonblocking:
concurrent administration fails explicitly; cleanup never deletes a pinned reader.
No distributed/NFS lock semantics are assumed.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from langchain_core.documents import Document

from app.config import settings
from app.rag.chunks import verified_chunk_id


class VersionError(RuntimeError):
    pass


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def make_manifest(chunks, *, model, dimensions, chunk_size, chunk_overlap):
    records = sorted([
        {"id": d.metadata["chunk_id"], "text": d.page_content, "metadata": d.metadata}
        for d in chunks
    ], key=lambda r: r["id"])
    if not records or len({r["id"] for r in records}) != len(records):
        raise VersionError("Empty or duplicate corpus")
    for row in records:
        doc = Document(page_content=row["text"], metadata=row["metadata"])
        if verified_chunk_id(doc) != row["id"]:
            raise VersionError("Invalid chunk identity/metadata")
    return {"schema": 1, "model": model, "dimensions": dimensions,
            "chunk_size": chunk_size, "chunk_overlap": chunk_overlap, "records": records}


def check_vectors(vectors, count, dimensions):
    if len(vectors) != count:
        raise VersionError("Embedding count mismatch")
    for vector in vectors:
        if (len(vector) != dimensions or not all(math.isfinite(float(x)) for x in vector)
                or not any(float(x) != 0 for x in vector)):
            raise VersionError("Invalid embedding dimension/value")


def validate(collection, manifest, owner):
    """Read back ALL records and vectors, verify identity, and query the actual index."""
    expected = manifest["records"]
    metadata = collection.metadata or {}
    if any(metadata.get(k) != v for k, v in {
        "owner": owner, "manifest": digest(manifest), "hnsw:space": "cosine",
        "dimensions": manifest["dimensions"], "model": manifest["model"],
    }.items()):
        raise VersionError("Collection ownership/manifest mismatch")
    if collection.count() != len(expected):
        raise VersionError("Collection count mismatch")
    rows = collection.get(include=["documents", "metadatas", "embeddings"])
    actual = sorted([
        {"id": i, "text": t, "metadata": m}
        for i, t, m in zip(rows["ids"], rows["documents"], rows["metadatas"], strict=True)
    ], key=lambda r: r["id"])
    if actual != expected:
        raise VersionError("Stored chunks differ from manifest")
    vectors = rows["embeddings"]
    check_vectors(vectors, len(expected), manifest["dimensions"])
    smoke = collection.query(query_embeddings=[list(vectors[0])], n_results=1,
                             include=["distances"])
    if (not smoke["ids"][0] or smoke["ids"][0][0] not in rows["ids"]
            or not math.isfinite(smoke["distances"][0][0])
            or abs(smoke["distances"][0][0]) > 0.001):
        raise VersionError("Index smoke query failed")


class Registry:
    def __init__(self, root=None, namespace=None):
        self.namespace = namespace or settings.chroma_collection
        self.owner = digest(self.namespace)
        self.root = Path(root or settings.knowledge_state_dir) / self.owner

    def _init(self):
        self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock(self, name, *, shared=False):
        self._init()
        with (self.root / f"{name}.lock").open("a+") as handle:
            try:
                fcntl.flock(handle, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise VersionError("Knowledge operation already in progress; retry later") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def read_state(self):
        try:
            state = json.loads((self.root / "active.json").read_text())
        except FileNotFoundError:
            return {"active": None, "previous": None}
        if set(state) != {"active", "previous"}:
            raise VersionError("Invalid active registry")
        for name in state.values():
            if name is not None:
                self.check_name(name)
        return state

    def status(self):
        with self.lock("admin"):
            state = self.read_state()
            versions = []
            for path in sorted(self.root.glob("kb-*.json")):
                name = path.stem
                manifest = self.manifest(name)
                role = ("active" if name == state["active"] else
                        "previous" if name == state["previous"] else "candidate_or_obsolete")
                versions.append({"name": name, "role": role,
                                 "chunks": len(manifest["records"]),
                                 "dimensions": manifest["dimensions"]})
            return {**state, "versions": versions}

    def check_name(self, name):
        if not re.fullmatch(r"kb-" + self.owner[:16] + r"-[a-f0-9]{64}", name):
            raise VersionError("Target does not belong to this namespace")

    def manifest(self, name):
        self.check_name(name)
        data = json.loads((self.root / f"{name}.json").read_text())
        if name != self.name(data):
            raise VersionError("Manifest digest mismatch")
        return data

    def name(self, manifest):
        return f"kb-{self.owner[:16]}-{digest(manifest)}"

    def write(self, filename, value):
        self._init()
        fd, temporary = tempfile.mkstemp(dir=self.root, prefix=".pending-")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(value, handle, sort_keys=True, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.root / filename)
            directory = os.open(self.root, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @contextmanager
    def snapshot(self):
        # Lock is held through ALL lexical/vector reads, even across async awaits.
        with self.lock("readers", shared=True):
            name = self.read_state()["active"]
            if name:
                manifest = self.manifest(name)
                if (manifest["model"] != settings.embedding_model
                        or manifest["dimensions"] != settings.embedding_dimensions):
                    raise VersionError("Active embedding configuration differs from application")
            # Read-only compatibility until an explicitly authorized first ingestion.
            yield name or self.namespace

    def _promote(self, client, name):
        manifest = self.manifest(name)
        if (manifest["model"] != settings.embedding_model
                or manifest["dimensions"] != settings.embedding_dimensions):
            raise VersionError("Target embedding configuration differs from application")
        validate(client.get_collection(name), manifest, self.owner)
        state = self.read_state()
        if state["active"] != name:
            self.write("active.json", {"active": name, "previous": state["active"]})

    def promote(self, client, name):
        with self.lock("admin"):
            self._promote(client, name)

    def rollback(self, client, target):
        with self.lock("admin"):
            if self.read_state()["previous"] != target:
                raise VersionError("Rollback target must be the previous active version")
            self._promote(client, target)

    def cleanup(self, client, target):
        self.check_name(target)
        with self.lock("admin"), self.lock("readers"):
            if target in self.read_state().values():
                raise VersionError("Cannot delete active or rollback version")
            manifest = self.manifest(target)
            # Failed/partial writes can be removed, but only with verified ownership.
            from chromadb.errors import NotFoundError
            try:
                collection = client.get_collection(target)
            except NotFoundError:
                collection = None  # Recovery after delete succeeded but local unlink failed.
            if collection is not None:
                metadata = collection.metadata or {}
                if (metadata.get("owner") != self.owner
                        or metadata.get("manifest") != digest(manifest)):
                    raise VersionError("Refusing cleanup of an unowned collection")
                client.delete_collection(target)
            (self.root / f"{target}.json").unlink()

    def build(self, client, chunks, embeddings, *, promote=True):
        """Caller holds admin lock from BEFORE fetch until after promotion."""
        manifest = make_manifest(chunks, model=settings.embedding_model,
                                 dimensions=settings.embedding_dimensions,
                                 chunk_size=settings.chunk_size,
                                 chunk_overlap=settings.chunk_overlap)
        name = self.name(manifest)
        from chromadb.errors import NotFoundError
        try:
            collection = client.get_collection(name)
        except NotFoundError:
            collection = None
        if collection is None:
            vectors = embeddings.embed_documents([r["text"] for r in manifest["records"]])
            check_vectors(vectors, len(chunks), manifest["dimensions"])
            # Journal ownership before remote create: failed writes stay quarantined.
            self.write(f"{name}.json", manifest)
            collection = client.create_collection(name, metadata={
                "hnsw:space": "cosine", "owner": self.owner, "manifest": digest(manifest),
                "dimensions": manifest["dimensions"], "model": manifest["model"],
            }, embedding_function=None)
            rows = manifest["records"]
            for start in range(0, len(rows), 100):
                batch = rows[start:start + 100]
                collection.add(ids=[r["id"] for r in batch], documents=[r["text"] for r in batch],
                               metadatas=[r["metadata"] for r in batch],
                               embeddings=vectors[start:start + 100])
        else:
            # Never overwrite deterministic-name collisions or incomplete candidates.
            if self.manifest(name) != manifest:
                raise VersionError("Version collision")
        validate(collection, manifest, self.owner)
        if promote:
            self._promote(client, name)
        return name
