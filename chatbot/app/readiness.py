"""Dependency readiness without provider calls or collection creation."""
from __future__ import annotations

import asyncio
from urllib.parse import quote

import httpx

from app.config import settings
from app.rag.versions import Registry, VersionError, digest


async def check_readiness():
    registry = Registry()
    async with asyncio.timeout(5), httpx.AsyncClient(timeout=2, trust_env=False) as client:
        with registry.snapshot() as name:
            root = settings.wc_base_url.split("/wp-json/")[0]
            # Product REST type proves WP database + Woo plugin are ready, no credentials.
            wp = await client.get(f"{root}/wp-json/wp/v2/types/product")
            wp.raise_for_status()
            if not isinstance(wp.json(), dict) or wp.json().get("slug") != "product":
                raise VersionError("WooCommerce not ready")
            base = (f"http://{settings.chroma_host}:{settings.chroma_port}/api/v2/tenants/"
                    "default_tenant/databases/default_database/collections")
            response = await client.get(f"{base}/{quote(name, safe='')}")
            response.raise_for_status()
            collection = response.json()
            if not isinstance(collection, dict) or not isinstance(collection.get("id"), str):
                raise VersionError("Invalid collection response")
            identifier = quote(collection["id"], safe="")
            count = await client.get(f"{base}/{identifier}/count")
            count.raise_for_status()
            if type(count.json()) is not int or count.json() <= 0:
                raise VersionError("Knowledge is empty or invalid")
            if name == registry.namespace:
                return  # Compatibility mode: no manifest existed before versioned ingestion.
            else:
                manifest = registry.manifest(name)
                metadata = collection.get("metadata") or {}
                if (not isinstance(metadata, dict)
                        or metadata.get("manifest") != digest(manifest)
                        or metadata.get("owner") != registry.owner
                        or metadata.get("dimensions") != manifest["dimensions"]
                        or metadata.get("model") != manifest["model"]
                        or metadata.get("hnsw:space") != "cosine"
                        or count.json() != len(manifest["records"])):
                    raise VersionError("Active knowledge is incomplete")
