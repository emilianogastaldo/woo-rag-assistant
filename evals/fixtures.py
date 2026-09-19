"""Snapshot sintetico indipendente dalle aspettative del golden (nessun dato cliente).

Il fake LLM esegue uno script e riporta il contenuto dei veri tool: non legge mai
ground_truth, route, tool o regex attesi. Verifica anche la consegna dei ToolMessage.
"""

from datetime import date

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, ToolMessage

RAG = "cerca_informazioni_negozio"
STOCK = "verifica_disponibilita_prodotto"
ORDER = "stato_ordine"
TOOLS = {RAG, STOCK, ORDER, "elenco_ordini"}
AS_OF = "2026-09-19"

CORPUS = {
    "Spedizioni": (
        "La spedizione standard costa 4,90 € sotto i 49 €; è gratuita da 49 €. "
        "Consegna in 2-4 giorni lavorativi, fino a 6 per isole e zone remote. "
        "Spediamo solo in Italia, San Marino e Città del Vaticano, non all'estero. "
        "L'espressa costa 9,90 € in 24/48h per ordini confermati entro le 13:00."
    ),
    "Resi e Rimborsi": (
        "Il reso è possibile entro 30 giorni dalla consegna. Il costo è a carico "
        "del cliente tranne per prodotti difettosi o errati. Il rimborso avviene "
        "entro 14 giorni dalla verifica del reso. Per prodotti difettosi contatta "
        "l'assistenza entro 30 giorni: sostituzione o rimborso completo, spese incluse. "
        "I prodotti intimi e sigillati aperti non sono rendibili salvo difetti."
    ),
    "Domande Frequenti": (
        "Accettiamo Visa, Mastercard, PayPal e bonifico bancario. "
        "Puoi acquistare come ospite o creando un account. "
        "Puoi richiedere la fattura indicando i dati di fatturazione."
    ),
    "BOTTLE-THERMO": "Borraccia Termica 500ml in acciaio inox: caldo 12 ore e freddo 24 ore.",
    "TSHIRT-BIO": "Maglietta in puro cotone biologico certificato GOTS.",
    "HOODIE-CLASSIC": "Felpa Classic con cappuccio, coulisse e tasca a marsupio frontale.",
    "BACKPACK-URBAN": "Zaino Urban da 20 litri con scomparto imbottito per laptop da 15 pollici.",
    "SHOES-RUN-X": "Scarpe Aero X leggere, intersuola reattiva, tomaia in mesh traspirante.",
}


def documents():
    return [
        Document(
            page_content=text,
            metadata={
                "title": key,
                "source": f"https://demo.invalid/docs/{index}",
                "type": "product" if "-" in key else "page",
                "sku": key if "-" in key else "",
            },
        )
        for index, (key, text) in enumerate(CORPUS.items())
    ]


class FrozenDate(date):
    @classmethod
    def today(cls):
        return cls.fromisoformat(AS_OF)


# Piani espliciti, indipendenti dal golden: cambiare le aspettative deve fallire.
PLANS = {
    **{f"ship-0{i}": [(RAG, {"domanda": "Spedizioni"})] for i in range(1, 6)},
    **{f"ret-0{i}": [(RAG, {"domanda": "Resi e Rimborsi"})] for i in range(1, 6)},
    **{f"faq-0{i}": [(RAG, {"domanda": "Domande Frequenti"})] for i in range(1, 4)},
    **{
        f"prod-0{i}": [(RAG, {"domanda": sku})]
        for i, sku in enumerate(
            ["BOTTLE-THERMO", "TSHIRT-BIO", "HOODIE-CLASSIC", "BACKPACK-URBAN", "SHOES-RUN-X"],
            1,
        )
    },
    "ood-01": [],
    "ood-02": [],
    "ord-01": [(ORDER, {"numero_ordine": 22})],
    "ord-02": [(ORDER, {"numero_ordine": 21}), (RAG, {"domanda": "Resi e Rimborsi"})],
    "adv-sku": [(STOCK, {"prodotto": "TSHIRT-BIO"})],
    "adv-code": [(RAG, {"domanda": "BOTTLE-THERMO"})],
    "adv-paraphrase": [(RAG, {"domanda": "Spedizioni"})],
    "adv-absent": [(RAG, {"domanda": "garanzia meteoriti"})],
    "adv-foreign": [(ORDER, {"numero_ordine": 23})],
    "adv-login": [],
    "adv-unavailable": [(ORDER, {"numero_ordine": 22})],
    "adv-no-delivery": [(ORDER, {"numero_ordine": 24}), (RAG, {"domanda": "Resi e Rimborsi"})],
}


class FakeStore:
    async def asimilarity_search_with_score(self, query, k=4):
        hits = [(doc, 0.2 if doc.metadata["title"] == query else 0.95) for doc in documents()]
        return sorted(hits, key=lambda hit: hit[1])[:k]


class FakeWoo:
    """Simula anche un server che ignora il filtro customer (ordine 23)."""

    def __init__(self):
        self.calls = 0

    async def get_json(self, path, params=None):
        self.calls += 1
        params = params or {}
        if path == "products":
            if params.get("sku", params.get("search")) != "TSHIRT-BIO":
                return []
            return [
                {
                    "name": "Maglietta Bio",
                    "sku": "TSHIRT-BIO",
                    "stock_status": "instock",
                    "stock_quantity": 42,
                    "price": "19.90",
                }
            ]
        if path != "orders":
            raise AssertionError("unexpected Woo endpoint")
        number = params.get("include", 22)
        if number not in {21, 22, 23, 24}:
            return []
        return [
            {
                "id": number,
                "number": str(number),
                "customer_id": 202 if number == 23 else 101,
                "status": "processing" if number == 22 else "completed",
                "date_created": "2026-09-01T09:00:00",
                "date_completed": "2026-09-02T09:00:00",
                "meta_data": [{"key": "_wrag_delivery_date", "value": "2026-09-05T09:00:00"}]
                if number == 21
                else [],
                "line_items": [{"name": "Maglietta Bio", "quantity": 1}],
                "total": "19.90",
                "currency": "EUR",
            }
        ]


class ScriptedLLM:
    def __init__(self, case_id):
        self.case_id = case_id
        self.plan = PLANS[case_id]
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1 and self.plan:
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": name, "args": args, "id": f"call-{i}"}
                    for i, (name, args) in enumerate(self.plan)
                ],
            )
        outputs = [m for m in messages if isinstance(m, ToolMessage)]
        if self.plan:
            assert [m.tool_call_id for m in outputs] == [
                f"call-{i}" for i in range(len(self.plan))
            ], "tool results missing or out of order"
        context = "\n".join(str(m.content) for m in outputs)
        if "NESSUN_RISULTATO_PERTINENTE" in context:
            reply = "Non lo so: contatta l'assistenza."
        elif "Strumento non disponibile" in context or self.case_id == "adv-login":
            reply = "Per consultare gli ordini devi accedere al tuo account."
        elif "Nessun ordine con questo numero" in context:
            reply = "Ordine non trovato: verifica il numero."
        elif not self.plan:
            reply = "Posso aiutarti solo con il negozio, prodotti e acquisti."
        else:
            reply = context
        return AIMessage(content=reply)
