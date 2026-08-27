"""Agente router: decide se rispondere con RAG, con i tool o con entrambi.

Il routing non è una catena di if: i tool sono esposti al modello e lui sceglie.
Ciò che *non* è lasciato al modello è l'autorizzazione — i tool ordini vengono
registrati solo se la sessione è autenticata (registrazione condizionale), quindi
per un utente anonimo semplicemente non esistono. Il customer ID è chiuso dentro
`OrderService` e non compare mai né nel prompt né nella firma dei tool.

Le fonti citate non le produce l'LLM: sono raccolte dai metadati dei chunk
restituiti dal retrieval, così una citazione inventata è strutturalmente impossibile.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.auth.session import Session
from app.config import settings
from app.rag.chain import KnowledgeBase, Source
from app.tools.catalog import CatalogService
from app.tools.orders import OrderService

BASE_PROMPT = """Sei l'assistente clienti di un negozio online WooCommerce.
Rispondi in italiano, in modo cortese, conciso e concreto. Oggi è il {today}.

Regole vincolanti:
- Usa SEMPRE gli strumenti per recuperare informazioni. Non rispondere mai a
  memoria su prodotti, spedizioni, resi, disponibilità o ordini.
- Se uno strumento non trova nulla di pertinente, dichiara di non saperlo e
  invita a contattare l'assistenza. Non inventare mai policy, prezzi, tempi o dati.
- Rispondi solo su argomenti relativi al negozio (catalogo, acquisti, spedizioni,
  resi, pagamenti, ordini). Se la domanda è fuori tema, declina con garbo e
  riporta la conversazione sul negozio.
- Puoi solo consultare informazioni: non puoi annullare ordini, modificare
  indirizzi o emettere rimborsi. Per queste richieste indirizza all'assistenza.
- Se una domanda richiede sia i dati di un ordine sia una policy del negozio,
  usa entrambi gli strumenti prima di rispondere.
"""

AUTHENTICATED_PROMPT = """
Il cliente è autenticato: hai gli strumenti per consultare i suoi ordini. Puoi
consultare esclusivamente gli ordini del suo account; se un numero d'ordine non
viene trovato, di' semplicemente che non risulta, senza altre supposizioni.
"""

ANONYMOUS_PROMPT = """
Il cliente NON è autenticato: non hai alcuno strumento per gli ordini. Se chiede
dello stato di un ordine, spiega con garbo che per motivi di sicurezza servono le
credenziali e invitalo ad accedere al proprio account. Sulle informazioni generali
del negozio puoi rispondere normalmente.
"""

FALLBACK_REPLY = (
    "Non riesco a completare la richiesta in questo momento. "
    "Ti consiglio di contattare l'assistenza del negozio."
)


class RicercaInformazioni(BaseModel):
    domanda: str = Field(
        description="Domanda o argomento da cercare nella knowledge base del negozio"
    )


class DisponibilitaProdotto(BaseModel):
    prodotto: str = Field(description="Nome o SKU del prodotto da verificare")


class StatoOrdine(BaseModel):
    numero_ordine: int = Field(description="Numero dell'ordine indicato dal cliente")


class ElencoOrdini(BaseModel):
    """Nessun argomento: il cliente è già determinato dalla sessione."""


@dataclass
class Toolset:
    """Tool esposti al modello più le fonti che il retrieval accumula usandoli.

    Tenere insieme le due cose evita che un chiamante costruisca i tool e poi
    perda le citazioni: le fonti appartengono al toolset che le ha prodotte.
    """

    tools: list[StructuredTool] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)


@dataclass
class AgentResult:
    reply: str
    sources: list[dict[str, str]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)


def build_toolset(
    session: Session | None,
    knowledge_base: KnowledgeBase | None = None,
    catalog: CatalogService | None = None,
    order_service: OrderService | None = None,
) -> Toolset:
    """Costruisce il toolset per la conversazione.

    I tool ordini compaiono solo con una sessione valida: per l'utente anonimo
    non sono "vietati dal prompt", non vengono proprio registrati.
    """
    kb = knowledge_base or KnowledgeBase()
    shop = catalog or CatalogService()
    toolset = Toolset()

    async def cerca_informazioni(domanda: str) -> str:
        result = await kb.search(domanda)
        toolset.sources.extend(result.sources)
        return result.context

    async def verifica_disponibilita(prodotto: str) -> str:
        return await shop.check_availability(prodotto)

    tools = [
        StructuredTool.from_function(
            coroutine=cerca_informazioni,
            name="cerca_informazioni_negozio",
            description=(
                "Cerca nella knowledge base del negozio: descrizioni prodotti, policy di "
                "spedizione, condizioni di reso e rimborso, FAQ. Da usare per ogni domanda "
                "su come funziona il negozio o su cosa vende."
            ),
            args_schema=RicercaInformazioni,
        ),
        StructuredTool.from_function(
            coroutine=verifica_disponibilita,
            name="verifica_disponibilita_prodotto",
            description=(
                "Verifica disponibilità a magazzino e prezzo attuale di un prodotto, per "
                "nome o SKU. Da usare per domande su scorte, esaurito, prezzo aggiornato."
            ),
            args_schema=DisponibilitaProdotto,
        ),
    ]

    if session is None:
        toolset.tools = tools
        return toolset

    orders = order_service or OrderService(customer_id=session.customer_id)

    async def stato_ordine(numero_ordine: int) -> str:
        return await orders.get_order(numero_ordine)

    async def elenco_ordini() -> str:
        return await orders.list_orders()

    tools.append(
        StructuredTool.from_function(
            coroutine=stato_ordine,
            name="stato_ordine",
            description=(
                "Recupera stato, date e articoli di un ordine del cliente collegato alla "
                "sessione, dato il numero d'ordine."
            ),
            args_schema=StatoOrdine,
        )
    )
    tools.append(
        StructuredTool.from_function(
            coroutine=elenco_ordini,
            name="elenco_ordini",
            description=(
                "Elenca gli ordini recenti del cliente collegato alla sessione. Utile "
                "quando il cliente non ricorda il numero d'ordine."
            ),
            args_schema=ElencoOrdini,
        )
    )
    toolset.tools = tools
    return toolset


def system_prompt(session: Session | None) -> str:
    base = BASE_PROMPT.format(today=date.today().strftime("%d/%m/%Y"))
    return base + (AUTHENTICATED_PROMPT if session else ANONYMOUS_PROMPT)


def _build_llm(tools: list[StructuredTool]) -> Any:
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )
    return llm.bind_tools(tools)


async def answer(
    message: str,
    session: Session | None = None,
    history: list[BaseMessage] | None = None,
    toolset: Toolset | None = None,
    llm: Any | None = None,
) -> AgentResult:
    """Esegue un giro completo di conversazione e restituisce risposta e fonti."""
    active = toolset if toolset is not None else build_toolset(session)
    by_name = {tool.name: tool for tool in active.tools}
    model = llm if llm is not None else _build_llm(active.tools)

    messages: list[BaseMessage] = [SystemMessage(content=system_prompt(session))]
    messages.extend(history or [])
    messages.append(HumanMessage(content=message))

    used: list[str] = []
    for _ in range(settings.agent_max_steps):
        ai_message: AIMessage = await model.ainvoke(messages)
        messages.append(ai_message)

        tool_calls = getattr(ai_message, "tool_calls", None)
        if not tool_calls:
            return AgentResult(
                reply=_as_text(ai_message.content) or FALLBACK_REPLY,
                sources=_dedupe(active.sources),
                tools_used=used,
            )

        for call in tool_calls:
            tool = by_name.get(call["name"])
            if tool is None:
                output = "Strumento non disponibile per questa conversazione."
            else:
                used.append(call["name"])
                output = await tool.ainvoke(call["args"])
            messages.append(ToolMessage(content=str(output), tool_call_id=call["id"]))

    return AgentResult(reply=FALLBACK_REPLY, sources=_dedupe(active.sources), tools_used=used)


def _dedupe(sources: list[Source]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for source in sources:
        key = (source.title, source.url)
        if key not in seen:
            seen.add(key)
            unique.append(source.as_dict())
    return unique
