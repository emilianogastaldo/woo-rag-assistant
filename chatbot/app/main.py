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

import hashlib
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager, nullcontext

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent import FALLBACK_REPLY, answer
from app.auth.session import (
    DEMO_CUSTOMERS,
    SessionError,
    issue_token,
    resolve_session,
    verify_token,
)
from app.config import settings
from app.conversations import ConversationError, MemoryConversationStore, MemoryRateLimiter
from app.http_clients import provider_client_scope
from app.observability import correlation, log_event
from app.privacy import privacy_scope, redact
from app.resilience import AttemptBudget, RecoverableFailure, budget_scope
from app.tools.woo_client import WooClient, woo_client_scope


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings.validate_security()
    application.state.conversations = MemoryConversationStore()
    application.state.rate_limiter = MemoryRateLimiter()
    logging.getLogger("uvicorn.access").disabled = True
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


class ChatRequest(BaseModel):
    """Only new user text and the opaque server conversation handle are accepted."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=16000)
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{43}$")

    @field_validator("message")
    @classmethod
    def bound_message(cls, value):
        if len(value.encode()) > settings.message_max_bytes:
            raise ValueError("Messaggio troppo lungo")
        return value


class ChatSource(BaseModel):
    title: str
    url: str
    type: str
    chunk_ids: list[str] = Field(
        min_length=1,
        description="ID citati nella risposta e recuperati in questa richiesta",
    )


class ChatResponse(BaseModel):
    conversation_id: str
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


def _bearer(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sessione non valida")
    return token.strip()


# Also initialized here for ASGI clients that intentionally skip lifespan.
app.state.conversations = MemoryConversationStore()
app.state.rate_limiter = MemoryRateLimiter()


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # FastAPI's default error includes the rejected (possibly sensitive) input.
    return JSONResponse(status_code=422, content={"detail": "Richiesta non valida"})


@app.middleware("http")
async def request_correlation(request: Request, call_next):
    request_id = uuid.uuid4().hex
    with correlation(request_id, uuid.uuid4().hex):
        started = time.perf_counter()
        if request.url.path == "/chat":
            # Use socket peer only: forwarded headers are not trusted here.
            peer = request.client.host if request.client else "unknown"
            retry = request.app.state.rate_limiter.check(hashlib.sha256(peer.encode()).hexdigest())
            if retry:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Troppe richieste"},
                    headers={"Retry-After": str(retry)},
                )
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > settings.chat_body_max_bytes:
                    return JSONResponse(
                        status_code=413, content={"detail": "Richiesta troppo grande"}
                    )
            request._body = bytes(body)
        response = await call_next(request)
        log_event(
            event="request",
            outcome="ok" if response.status_code < 400 else "error",
            duration_ms=(time.perf_counter() - started) * 1000,
        )
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def demo_login(req: DemoLoginRequest) -> DemoLoginResponse:
    """Login mockato per la demo: emette un token firmato per un cliente del seed."""
    email = DEMO_CUSTOMERS.get(req.customer.strip().upper())
    if email is None:
        raise HTTPException(status_code=404, detail="Cliente demo non riconosciuto")
    return DemoLoginResponse(token=issue_token(email))


if settings.demo_enabled:
    app.post("/demo/login", response_model=DemoLoginResponse)(demo_login)


@app.get("/session/config")
async def session_config():
    return {"demo_enabled": settings.demo_enabled}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    request: Request,
    response: Response,
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
    conversation = None
    try:
        provider_client = getattr(request.app.state, "provider_http_client", None)
        provider_scope = (
            provider_client_scope(provider_client) if provider_client is not None else nullcontext()
        )
        with budget_scope(budget), woo_client_scope(woo), provider_scope:
            try:
                token = _bearer(authorization)
                session = await resolve_session(token, client=woo)
            except SessionError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc
            except RecoverableFailure:
                raise HTTPException(status_code=503, detail=FALLBACK_REPLY) from None
            guest_token = request.cookies.get("wrag_guest")
            if session is not None:
                identity = f"{token}:{session.customer_id}".encode()
                owner = "auth:" + hashlib.sha256(identity).hexdigest()
            else:
                try:
                    if not guest_token or not verify_token(guest_token).startswith("guest:"):
                        raise SessionError("ospite assente")
                except SessionError:
                    guest_token = issue_token("guest:" + uuid.uuid4().hex)
                owner = "anon:" + hashlib.sha256(guest_token.encode()).hexdigest()
            try:
                conversation = request.app.state.conversations.acquire(req.conversation_id, owner)
            except ConversationError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from None
            with privacy_scope(
                token or "",
                guest_token or "",
                session.email if session else "",
                str(session.customer_id) if session else "",
            ):
                message = redact(req.message)
                result = await answer(message, session=session, history=list(conversation.history))
                result.reply = redact(result.reply)
                sources = [
                    ChatSource(
                        **{k: redact(v) if isinstance(v, str) else v for k, v in source.items()}
                    )
                    for source in result.sources
                ]
                request.app.state.conversations.commit(conversation, message, result.reply)
            if session is None:
                response.set_cookie(
                    "wrag_guest",
                    guest_token,
                    httponly=True,
                    secure=settings.app_env == "production",
                    samesite="lax",
                    max_age=settings.session_ttl_seconds,
                    path="/chat",
                )
        return ChatResponse(
            conversation_id=conversation.id,
            reply=result.reply,
            sources=sources,
            authenticated=session is not None,
            tools_used=result.tools_used,
        )
    finally:
        if conversation is not None:
            request.app.state.conversations.release(conversation)
        if owns_client:
            await woo.aclose()


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    expose_headers=["Retry-After", "X-Request-ID"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


_widget_dir = os.getenv("WIDGET_DIR", "/widget")
if os.path.isdir(_widget_dir):
    app.mount("/widget", StaticFiles(directory=_widget_dir, html=True), name="widget")
