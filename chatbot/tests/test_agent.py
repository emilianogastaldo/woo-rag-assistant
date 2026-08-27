"""Agente: registrazione condizionale dei tool e loop di tool calling.

Copre gli scenari obbligatori 1 e 2 di CLAUDE.md: l'anonimo ha il RAG ma non i
tool ordini, e una richiesta sugli ordini degrada in un invito ad accedere.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent import answer, build_toolset, system_prompt
from app.auth.session import Session
from app.rag.chain import RetrievalResult, Source

SESSION = Session(email="mario.rossi@example.com", customer_id=12)

ANON_TOOLS = {"cerca_informazioni_negozio", "verifica_disponibilita_prodotto"}
ORDER_TOOLS = {"stato_ordine", "elenco_ordini"}


class FakeKnowledgeBase:
    def __init__(self, result: RetrievalResult) -> None:
        self.result = result
        self.queries: list[str] = []

    async def search(self, query: str, k: int | None = None) -> RetrievalResult:
        self.queries.append(query)
        return self.result


class FakeCatalog:
    async def check_availability(self, product: str, limit: int = 3) -> str:
        return f"Prodotto: {product}\nDisponibilità: disponibile"


class FakeOrderService:
    def __init__(self) -> None:
        self.asked: list[int] = []

    async def get_order(self, order_number: int) -> str:
        self.asked.append(order_number)
        return "Ordine #22\nStato: completato (consegnato)"

    async def list_orders(self, limit: int = 5) -> str:
        return "Ordine #22"


class FakeLLM:
    """Sostituisce il modello: restituisce risposte predefinite in sequenza."""

    def __init__(self, *responses: AIMessage) -> None:
        self.responses = list(responses)
        self.seen: list[list] = []

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        return self.responses.pop(0)


def anon_toolset(**kwargs):
    return build_toolset(
        None,
        knowledge_base=kwargs.pop("knowledge_base", FakeKnowledgeBase(RetrievalResult(""))),
        catalog=FakeCatalog(),
        **kwargs,
    )


def auth_toolset(**kwargs):
    return build_toolset(
        SESSION,
        knowledge_base=kwargs.pop("knowledge_base", FakeKnowledgeBase(RetrievalResult(""))),
        catalog=FakeCatalog(),
        order_service=kwargs.pop("order_service", FakeOrderService()),
        **kwargs,
    )


def tool_names(toolset) -> set[str]:
    return {tool.name for tool in toolset.tools}


def test_utente_anonimo_non_ha_i_tool_ordini():
    toolset = anon_toolset()
    assert tool_names(toolset) == ANON_TOOLS
    assert not ORDER_TOOLS & tool_names(toolset)


def test_utente_autenticato_ha_anche_i_tool_ordini():
    assert ANON_TOOLS | ORDER_TOOLS == tool_names(auth_toolset())


def test_la_firma_del_tool_ordini_non_espone_il_customer_id():
    """Il modello può chiedere solo il numero d'ordine: il cliente lo mette il codice."""
    toolset = auth_toolset()
    schema = next(t for t in toolset.tools if t.name == "stato_ordine").args_schema
    assert set(schema.model_fields) == {"numero_ordine"}


def test_il_prompt_non_contiene_il_customer_id():
    prompt = system_prompt(SESSION)
    assert "12" not in prompt
    assert SESSION.email not in prompt


def test_il_prompt_anonimo_invita_ad_accedere():
    assert "accedere" in system_prompt(None).lower()


async def test_risposta_rag_raccoglie_le_fonti_dai_metadati():
    kb = FakeKnowledgeBase(
        RetrievalResult(
            context="La spedizione standard costa 4,90 €.",
            sources=[Source(title="Spedizioni", url="http://x/spedizioni", type="page")],
        )
    )
    toolset = anon_toolset(knowledge_base=kb)
    llm = FakeLLM(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "cerca_informazioni_negozio",
                    "args": {"domanda": "costo spedizione"},
                    "id": "call-1",
                }
            ],
        ),
        AIMessage(content="La spedizione standard costa 4,90 €."),
    )
    result = await answer("quanto costa la spedizione?", session=None, toolset=toolset, llm=llm)
    assert "4,90" in result.reply
    assert result.sources == [{"title": "Spedizioni", "url": "http://x/spedizioni", "type": "page"}]
    assert result.tools_used == ["cerca_informazioni_negozio"]
    assert kb.queries == ["costo spedizione"]


async def test_tool_ordini_invocato_dal_modello_quando_autenticato():
    orders = FakeOrderService()
    toolset = auth_toolset(order_service=orders)
    llm = FakeLLM(
        AIMessage(
            content="",
            tool_calls=[{"name": "stato_ordine", "args": {"numero_ordine": 22}, "id": "c1"}],
        ),
        AIMessage(content="Il tuo ordine #22 è stato consegnato."),
    )
    result = await answer("a che punto è l'ordine 22?", session=SESSION, toolset=toolset, llm=llm)
    assert orders.asked == [22]
    assert "22" in result.reply


async def test_chiamata_a_tool_non_registrato_non_viene_eseguita():
    """Se il modello inventa una chiamata a un tool assente, il loop non la esegue."""
    toolset = anon_toolset()
    llm = FakeLLM(
        AIMessage(
            content="",
            tool_calls=[{"name": "stato_ordine", "args": {"numero_ordine": 22}, "id": "c1"}],
        ),
        AIMessage(content="Per vedere i tuoi ordini devi accedere al tuo account."),
    )
    result = await answer("a che punto è l'ordine 22?", session=None, toolset=toolset, llm=llm)
    assert result.tools_used == []
    assert "accedere" in result.reply.lower()
