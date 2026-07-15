"""Backend FastAPI: orchestratore chat (RAG + tool calling).

v1: stub minimale. Espone l'endpoint /chat e un healthcheck.
La logica di routing (RAG / tool / misto), la registrazione condizionale
dei tool e la validazione di sessione verranno aggiunte nei blocchi successivi.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import settings

app = FastAPI(
    title="woo-rag-assistant",
    description="Assistente clienti WooCommerce basato su RAG + tool calling",
    version="0.1.0",
)


class ChatRequest(BaseModel):
    """Payload in ingresso dal widget.

    NB: il customer ID NON transita mai qui. È derivato server-side dal
    token di sessione (vedi regole di sicurezza in CLAUDE.md).
    """

    message: str
    session_token: str | None = None


class ChatResponse(BaseModel):
    reply: str
    sources: list[str] = []


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Stub dell'endpoint di chat.

    TODO:
      - validare `session_token` e risolvere il customer ID server-side
      - registrare condizionalmente i tool ordini (solo se autenticato)
      - instradare tra catena RAG e tool calling
    """
    _ = settings  # config disponibile per gli step successivi
    return ChatResponse(
        reply=(
            "Ciao! Sono l'assistente del negozio, ma sono ancora in fase di "
            "configurazione. Presto potrò aiutarti con prodotti, spedizioni e ordini."
        ),
        sources=[],
    )
