"""Client asincrono per la REST API di WooCommerce con firma OAuth 1.0a one-legged.

Su HTTP puro WooCommerce richiede OAuth 1.0a (la Basic Auth vale solo su HTTPS).
Quirk noto: la base string della firma è ricostruita da WooCommerce a partire dal
proprio `home_url`, NON dall'host a cui il client si connette. In ambiente Docker ci
si connette a `http://wordpress` ma si deve firmare con l'URL pubblico
(es. `http://localhost:8080`). Vedi docs/architecture.md — DEC-001.

Riusato sia dalla pipeline di ingestion sia dai tool ordini (scoped sul cliente).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings


class WooClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        sign_url: str | None = None,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base = (base_url or settings.wc_base_url).rstrip("/")
        self._sign_base = (sign_url or settings.wc_signing_base).rstrip("/")
        self._ck = consumer_key or settings.wc_consumer_key
        self._cs = consumer_secret or settings.wc_consumer_secret
        self._timeout = timeout

    @staticmethod
    def _percent(value: Any) -> str:
        # RFC 3986: quote lascia inalterati A-Za-z0-9-._~, coerente con OAuth 1.0a.
        return quote(str(value), safe="")

    def _signature(self, method: str, sign_url: str, params: dict[str, str]) -> str:
        encoded = {self._percent(k): self._percent(v) for k, v in params.items()}
        normalized = "&".join(f"{k}={encoded[k]}" for k in sorted(encoded))
        base_string = "&".join(
            [method.upper(), self._percent(sign_url), self._percent(normalized)]
        )
        digest = hmac.new((self._cs + "&").encode(), base_string.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def _signed_params(self, method: str, path: str, params: dict | None) -> dict[str, str]:
        merged: dict[str, str] = {k: str(v) for k, v in (params or {}).items()}
        merged.update(
            {
                "oauth_consumer_key": self._ck,
                "oauth_nonce": secrets.token_hex(16),
                "oauth_signature_method": "HMAC-SHA256",
                "oauth_timestamp": str(int(time.time())),
            }
        )
        sign_url = f"{self._sign_base}/{path.lstrip('/')}"
        merged["oauth_signature"] = self._signature(method, sign_url, merged)
        return merged

    async def get(self, path: str, params: dict | None = None) -> httpx.Response:
        url = f"{self._base}/{path.lstrip('/')}"
        signed = self._signed_params("GET", path, params)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, params=signed)
            response.raise_for_status()
            return response

    async def get_json(self, path: str, params: dict | None = None) -> Any:
        return (await self.get(path, params)).json()

    async def get_all(self, path: str, params: dict | None = None, per_page: int = 100) -> list[dict]:
        """Recupera tutte le pagine di una risorsa paginata WooCommerce."""
        results: list[dict] = []
        page = 1
        while True:
            response = await self.get(path, {**(params or {}), "per_page": per_page, "page": page})
            batch = response.json()
            results.extend(batch)
            total_pages = int(response.headers.get("X-WP-TotalPages", "1") or "1")
            if not batch or page >= total_pages:
                break
            page += 1
        return results
