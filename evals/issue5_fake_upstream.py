"""Deterministic OpenAI-compatible and Woo fault server for issue #5."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter, defaultdict

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

app = FastAPI()
calls: Counter[str] = Counter()
ports: defaultdict[str, set[int]] = defaultdict(set)


def record(name: str, request: Request) -> int:
    calls[name] += 1
    if request.client:
        ports[name].add(request.client.port)
    return calls[name]


def embedding(text: str) -> list[float]:
    if "meteoriti" in text.lower():
        return [-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/admin/reset")
async def reset():
    calls.clear()
    ports.clear()
    return {"status": "ok"}


@app.get("/admin/counters")
async def counters():
    return {"calls": dict(calls), "client_ports": {k: len(v) for k, v in ports.items()}}


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    record("embeddings", request)
    body = await request.json()
    values = body.get("input", [])
    values = [values] if isinstance(values, str) else values
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": embedding(str(value))}
            for index, value in enumerate(values)
        ],
        "model": body.get("model", "synthetic-embedding"),
        "usage": {"prompt_tokens": len(values), "total_tokens": len(values)},
    }


def completion(content=None, tool_call=None):
    message = {"role": "assistant", "content": content}
    finish = "stop"
    if tool_call:
        name, arguments = tool_call
        message["content"] = None
        message["tool_calls"] = [{
            "id": "call-synthetic",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }]
        finish = "tool_calls"
    return {
        "id": "chatcmpl-synthetic",
        "object": "chat.completion",
        "created": 1,
        "model": "synthetic-chat",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    user = next(
        (str(message.get("content", "")) for message in reversed(messages)
         if message.get("role") == "user"),
        "",
    )
    key = "model_down" if "MODEL-DOWN" in user else "model_retry" if "MODEL-500" in user else "chat"
    number = record(key, request)
    if "MODEL-MALFORMED" in user:
        return {"choices": None}
    if key == "model_down" or (key == "model_retry" and number == 1):
        return JSONResponse({"error": {"message": "synthetic"}}, status_code=503)
    if key == "model_retry":
        return completion("Posso aiutarti con il negozio.")
    if messages and messages[-1].get("role") == "tool":
        content = str(messages[-1].get("content", ""))
        match = re.search(r"\[(chunk-v1-[0-9a-f]{64})\]", content)
        if match:
            return completion(f"La spedizione standard e documentata. [{match.group(1)}]")
        if "NESSUN_RISULTATO_PERTINENTE" in content:
            return completion("Non lo so: contatta l'assistenza.")
        if "temporaneamente" in content or "dati non leggibili" in content:
            return completion("Il servizio e temporaneamente non disponibile.")
        return completion(content)
    if user.startswith("STOCK "):
        return completion(tool_call=(
            "verifica_disponibilita_prodotto", {"prodotto": user.removeprefix("STOCK ")}
        ))
    if user.startswith("ORDER "):
        return completion(tool_call=("stato_ordine", {"numero_ordine": int(user[6:])}))
    return completion(tool_call=("cerca_informazioni_negozio", {"domanda": user}))


@app.get("/wp-json/wc/v3/products")
async def products(request: Request, sku: str = "", search: str = ""):
    code = sku or search
    name = f"woo_{code.lower().replace('-', '_') or 'empty'}"
    number = record(name, request)
    if code == "TIMEOUT":
        await asyncio.sleep(0.5)
    if code == "RATE-LIMIT" and number == 1:
        return JSONResponse({"error": "synthetic"}, status_code=429,
                            headers={"Retry-After": "0.1"})
    if code == "LONG-WAIT":
        return JSONResponse({"error": "synthetic"}, status_code=429,
                            headers={"Retry-After": "10"})
    if code == "CLIENT-ERROR":
        return JSONResponse({"error": "synthetic"}, status_code=400)
    if code == "SERVER-ERROR":
        return JSONResponse({"error": "synthetic"}, status_code=503)
    if code == "MALFORMED":
        return Response(content="{", media_type="application/json")
    digest = hashlib.sha256(code.encode()).hexdigest()[:8]
    return [{
        "id": int(digest, 16), "name": f"Synthetic {code}", "sku": code,
        "stock_status": "instock", "stock_quantity": 3, "price": "9.90",
        "permalink": "https://shop.invalid/product",
    }]


@app.get("/wp-json/wc/v3/customers")
async def customers(request: Request):
    record("customers", request)
    return [{"id": 101}]


@app.get("/wp-json/wc/v3/orders")
async def orders(request: Request, customer: int, include: int):
    record("orders", request)
    assert customer == 101
    return [{"id": include, "customer_id": 101 if include == 21 else 102,
             "status": "processing", "line_items": [], "total": "9.90"}]
