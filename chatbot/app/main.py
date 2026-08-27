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

import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field

from app.agent import answer
from app.auth.session import DEMO_CUSTOMERS, SessionError, issue_token, resolve_session
from app.config import settings

app = FastAPI(
    title="woo-rag-assistant",
    description="Assistente clienti WooCommerce basato su RAG + tool calling",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    """Payload in ingresso dal widget.

    NB: il customer ID NON transita mai qui. È derivato server-side dal token di
    sessione presentato nell'header Authorization (vedi CLAUDE.md).
    """

    message: str = Field(min_length=1)
    history: list[Message] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    sources: list[dict[str, str]] = []
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
async def chat(req: ChatRequest, authorization: str | None = Header(default=None)) -> ChatResponse:
    try:
        session = await resolve_session(_bearer(authorization))
    except SessionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    result = await answer(req.message, session=session, history=_to_messages(req.history))
    return ChatResponse(
        reply=result.reply,
        sources=result.sources,
        authenticated=session is not None,
        tools_used=result.tools_used,
    )


_widget_dir = os.getenv("WIDGET_DIR", "/widget")
if os.path.isdir(_widget_dir):
    app.mount("/widget", StaticFiles(directory=_widget_dir, html=True), name="widget")
