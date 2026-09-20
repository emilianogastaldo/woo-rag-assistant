"""Backend FastAPI: orchestratore chat (RAG + tool calling).

Flusso di una richiesta a `/chat`:
  1. il token di sessione arriva nell'header `Authorization: Bearer ...`;
  2. il backend lo verifica e risolve il customer ID server-side;
  3. in base alla sessione costruisce il toolset (i tool ordini esistono solo per
     un utente autenticato);
  4. l'agente decide fra RAG, tool o entrambi e produce risposta e fonti.

Il customer ID non entra mai nel payload della richiesta né nel prompt.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager, nullcontext
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field

from app.agent import FALLBACK_REPLY, answer
from app.auth.session import DEMO_CUSTOMERS, SessionError, issue_token, resolve_session
from app.config import settings
from app.http_clients import provider_client_scope
from app.observability import correlation, log_event
from app.resilience import AttemptBudget, RecoverableFailure, budget_scope
from app.tools.woo_client import WooClient, woo_client_scope


@asynccontextmanager
async def lifespan(application: FastAPI):
    operations = logging.getLogger("woo_rag.operations")
    if not operations.handlers:
        operations.addHandler(logging.StreamHandler())
    operations.setLevel(logging.INFO)
    # HTTP library request logs contain OAuth query parameters.
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    application.state.woo_client = WooClient()
    application.state.provider_http_client = httpx.AsyncClient(
        timeout=settings.provider_timeout_seconds,
        trust_env=False,
    )
    try:
        yield
    finally:
        await application.state.woo_client.aclose()
        await application.state.provider_http_client.aclose()

app = FastAPI(
    title="woo-rag-assistant",
    description="Assistente clienti WooCommerce basato su RAG + tool calling",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """Payload in ingresso dal widget.

    NB: il customer ID NON transita mai qui. È derivato server-side dal token di
    sessione presentato nell'header Authorization (vedi CLAUDE.md).
    """

    message: str = Field(min_length=1, max_length=4000)
    history: list[Message] = Field(default_factory=list, max_length=20)


class ChatSource(BaseModel):
    title: str
    url: str
    type: str
    chunk_ids: list[str] = Field(
        min_length=1, description="ID citati nella risposta e recuperati in questa richiesta",
    )


class ChatResponse(BaseModel):
    reply: str = Field(description="Testo con citazioni [chunk-v1-<sha256>] validate")
    sources: list[ChatSource] = Field(
        default_factory=list,
        description="Sole fonti citate valide, deduplicate per URL e tipo; altrimenti lista vuota",
    )
    authenticated: bool = False
    tools_used: list[str] = []


class DemoLoginRequest(BaseModel):
    customer: str = "A"


class DemoLoginResponse(BaseModel):
    token: str
    email: str


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _safe_id(value: str | None) -> str:
    return value if value and _CORRELATION_ID.fullmatch(value) else uuid.uuid4().hex


@app.middleware("http")
async def request_correlation(request: Request, call_next):
    request_id = _safe_id(request.headers.get("X-Request-ID"))
    conversation_id = _safe_id(request.headers.get("X-Conversation-ID"))
    with correlation(request_id, conversation_id):
        started = time.perf_counter()
        response = await call_next(request)
        log_event(event="request", outcome="ok" if response.status_code < 400 else "error",
                  duration_ms=(time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    return response


def _to_messages(history: list[Message]) -> list[BaseMessage]:
    converted: list[BaseMessage] = []
    for item in history[-10:]:
        if item.role == "user":
            converted.append(HumanMessage(content=item.content))
        elif item.role == "assistant":
            converted.append(AIMessage(content=item.content))
    return converted


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/demo/login", response_model=DemoLoginResponse)
async def demo_login(req: DemoLoginRequest) -> DemoLoginResponse:
    """Login mockato per la demo: emette un token firmato per un cliente del seed."""
    email = DEMO_CUSTOMERS.get(req.customer.strip().upper())
    if email is None:
        raise HTTPException(status_code=404, detail="Cliente demo non riconosciuto")
    return DemoLoginResponse(token=issue_token(email), email=email)


@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> ChatResponse:
    woo = getattr(request.app.state, "woo_client", None)
    owns_client = woo is None
    woo = woo or WooClient()
    budget = AttemptBudget(
        max_attempts=settings.agent_max_attempts,
        max_retries=settings.agent_retry_budget,
        deadline_seconds=settings.request_deadline_seconds,
    )
    try:
        provider_client = getattr(request.app.state, "provider_http_client", None)
        provider_scope = (
            provider_client_scope(provider_client) if provider_client is not None else nullcontext()
        )
        with budget_scope(budget), woo_client_scope(woo), provider_scope:
            try:
                session = await resolve_session(_bearer(authorization), client=woo)
            except SessionError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc
            except RecoverableFailure:
                raise HTTPException(status_code=503, detail=FALLBACK_REPLY) from None
            result = await answer(
                req.message,
                session=session,
                history=_to_messages(req.history),
            )
        return ChatResponse(
            reply=result.reply,
            sources=[ChatSource(**source) for source in result.sources],
            authenticated=session is not None,
            tools_used=result.tools_used,
        )
    finally:
        if owns_client:
            await woo.aclose()


_widget_dir = os.getenv("WIDGET_DIR", "/widget")
if os.path.isdir(_widget_dir):
    app.mount("/widget", StaticFiles(directory=_widget_dir, html=True), name="widget")
