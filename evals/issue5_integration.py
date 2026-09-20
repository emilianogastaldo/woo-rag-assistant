"""HTTP-level checks against the isolated issue #5 Compose project."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import chromadb
import httpx
from langchain_core.documents import Document

from app.agent import FALLBACK_REPLY, UNCITED_REPLY
from app.rag.chunks import split_documents

API = "http://api:8000"
UPSTREAM = "http://upstream:9000"
RESULTS = Path("/results")


def wait_for(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=1, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError("isolated service did not become ready")


def seed(replace=False) -> str:
    client = chromadb.HttpClient(host="chroma", port=8000)
    collection = client.get_or_create_collection(
        os.environ["CHROMA_COLLECTION"], metadata={"hnsw:space": "cosine"}
    )
    document = split_documents([Document(
        page_content=("La spedizione standard impiega cinque giorni lavorativi." if replace
                      else "La spedizione standard impiega tre giorni lavorativi."),
        metadata={"source": "https://shop.invalid/spedizioni", "title": "Spedizioni",
                  "type": "page"},
    )])[0]
    if replace:
        previous = collection.get()["ids"]
        if previous:
            collection.delete(ids=previous)
    collection.upsert(
        ids=[document.metadata["chunk_id"]],
        documents=[document.page_content],
        metadatas=[document.metadata],
        embeddings=[[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
    )
    return document.metadata["chunk_id"]


def post(message: str, token=None) -> tuple[dict, float, str]:
    started = time.monotonic()
    response = httpx.post(
        f"{API}/chat", json={"message": message}, timeout=3, trust_env=False,
        headers={"X-Request-ID": "issue5-request",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    elapsed = time.monotonic() - started
    if response.status_code != 200:
        raise AssertionError(f"API status {response.status_code}: {response.text[:300]}")
    assert "Traceback" not in response.text and "synthetic-secret" not in response.text
    return response.json(), elapsed, response.headers["X-Request-ID"]


def counters() -> dict:
    return httpx.get(f"{UPSTREAM}/admin/counters", timeout=2, trust_env=False).json()


def reset() -> None:
    response = httpx.post(f"{UPSTREAM}/admin/reset", timeout=2, trust_env=False)
    assert response.status_code == 200


def healthy() -> dict:
    wait_for(f"{UPSTREAM}/health")
    wait_for(f"{API}/health")
    seed()
    reset()
    shipping, _, request_id = post("Come funziona la spedizione?")
    assert shipping["sources"] and shipping["tools_used"] == ["cerca_informazioni_negozio"]
    assert len(request_id) == 32 and request_id != "issue5-request"
    missing, _, _ = post("Avete una garanzia contro i meteoriti?")
    assert missing["reply"] == UNCITED_REPLY and missing["sources"] == []

    normal, _, _ = post("STOCK NORMAL")
    assert "disponibile" in normal["reply"]
    post("STOCK NORMAL")
    normal_counts = counters()
    assert normal_counts["calls"]["woo_normal"] == 2
    assert normal_counts["client_ports"]["woo_normal"] == 1

    reset()
    rate, rate_elapsed, _ = post("STOCK RATE-LIMIT")
    assert "disponibile" in rate["reply"]
    assert rate_elapsed >= .1
    assert counters()["calls"]["woo_rate_limit"] == 2

    reset()
    client_error, _, _ = post("STOCK CLIENT-ERROR")
    assert client_error["sources"] == []
    assert counters()["calls"]["woo_client_error"] == 1

    reset()
    server_error, _, _ = post("STOCK SERVER-ERROR")
    assert server_error["sources"] == []
    assert counters()["calls"]["woo_server_error"] == 2

    reset()
    timeout, elapsed, _ = post("STOCK TIMEOUT")
    assert timeout["sources"] == [] and 0.25 <= elapsed < 1.5
    assert counters()["calls"]["woo_timeout"] == 2

    reset()
    malformed, _, _ = post("STOCK MALFORMED")
    assert malformed["sources"] == []
    assert counters()["calls"]["woo_malformed"] == 1

    reset()
    recovered, _, _ = post("MODEL-500")
    assert "negozio" in recovered["reply"]
    assert counters()["calls"]["model_retry"] == 2

    reset()
    down, _, _ = post("MODEL-DOWN")
    assert down["reply"] == FALLBACK_REPLY and down["sources"] == []
    assert counters()["calls"]["model_down"] == 2

    reset()
    malformed_model, _, _ = post("MODEL-MALFORMED")
    assert malformed_model["reply"] == FALLBACK_REPLY and not malformed_model["sources"]
    assert counters()["calls"]["chat"] == 1

    reset()
    exhausted, deadline_elapsed, _ = post("STOCK LONG-WAIT")
    assert exhausted["reply"] == FALLBACK_REPLY
    assert 1.4 < deadline_elapsed < 2
    assert counters()["calls"]["woo_long_wait"] == 1

    reset()
    anonymous, _, _ = post("ORDER 22")
    assert "orders" not in counters()["calls"] and anonymous["tools_used"] == []
    token = httpx.post(f"{API}/demo/login", json={"customer": "A"},
                       trust_env=False).json()["token"]
    owned, _, _ = post("ORDER 21", token)
    foreign, _, _ = post("ORDER 22", token)
    assert "#21" in owned["reply"] and owned["authenticated"]
    assert "Nessun ordine" in foreign["reply"] and "#22" not in foreign["reply"]
    return {"phase": "healthy", "status": "PASS", "timeout_seconds": round(elapsed, 3),
            "deadline_seconds": round(deadline_elapsed, 3),
            "retry_after_seconds": round(rate_elapsed, 3), "external_provider_calls": 0}


def chroma_down() -> dict:
    reset()
    body, elapsed, _ = post("Come funziona la spedizione?")
    assert body["reply"] == FALLBACK_REPLY
    assert body["sources"] == []
    return {"phase": "chroma-down", "status": "PASS", "elapsed_seconds": round(elapsed, 3)}


def recovered() -> dict:
    wait_for("http://chroma:8000/api/v2/heartbeat")
    new_id = seed(replace=True)
    body, _, _ = post("Come funziona la spedizione?")
    assert body["sources"]
    assert body["sources"][0]["chunk_ids"] == [new_id]
    return {"phase": "recovered", "status": "PASS"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("healthy", "chroma-down", "recovered"), required=True)
    args = parser.parse_args()
    result = globals()[args.phase.replace("-", "_")]()
    path = RESULTS / f"{args.phase}.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
