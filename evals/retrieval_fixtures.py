"""Synthetic retrieval benchmark: actual queries, corpus and vector computation.

The local embeddings intentionally ignore identifiers. They are a mechanical
stress adapter, not a simulation or estimate of production semantic accuracy.
Neither adapter nor model reads the expected result of a benchmark case.
"""
from __future__ import annotations

import math
from collections import Counter

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage, ToolMessage

from app.rag.chunks import split_documents
from app.rag.lexical import tokenize
from evals.fixtures import ORDER, RAG, documents


def corpus():
    return documents() + split_documents([
        Document(
            page_content=text,
            metadata={"source": f"https://synthetic.invalid/{key}", "title": title,
                      "type": "product" if sku else "page", "sku": sku},
        )
        for key, title, text, sku in (
            ("bottle-2", "Borraccia Termica Plus", "Borraccia Termica 750ml in acciaio: "
             "caldo 18 ore, freddo 36 ore.", "BOTTLE-THERMO-2"),
            ("kit-104", "Kit Aster", "Kit Aster. Manuale ZX-104, revisione 7. "
             "Montaggio con chiave da 12 mm.", "KIT-104"),
            ("kit-140", "Kit Aster Pro", "Kit Aster Pro. Manuale ZX-140, revisione 9. "
             "Montaggio con chiave da 14 mm.", "KIT-140"),
            ("shipping-code", "Ritiro in sede", "Il codice RIT-204 permette il ritiro "
             "in sede dopo 48 ore dalla conferma.", ""),
        )
    ])


# Hand-authored, inspectable cases independent of the embedding vocabulary.
CASES = [
    {"id": "sku-only", "query": "BOTTLE-THERMO", "source": "BOTTLE-THERMO", "group": "code"},
    {"id": "sku-question", "query": "Quale prodotto ha SKU TSHIRT-BIO?",
     "source": "TSHIRT-BIO", "group": "code"},
    {"id": "sku-neighbor", "query": "BOTTLE-THERMO-2",
     "source": "BOTTLE-THERMO-2", "group": "adversarial"},
    {"id": "manual-code", "query": "manuale ZX-104", "source": "KIT-104", "group": "code"},
    {"id": "manual-neighbor", "query": "manuale ZX-140",
     "source": "KIT-140", "group": "adversarial"},
    {"id": "pickup-code", "query": "codice RIT-204",
     "source": "Ritiro in sede", "group": "code"},
    {"id": "numeric", "query": "chiave da 14 mm", "source": "KIT-140", "group": "exact"},
    {"id": "exact-name", "query": "Zaino Urban laptop",
     "source": "BACKPACK-URBAN", "group": "exact"},
    {"id": "shipping", "query": "Quanto costa la spedizione standard?",
     "source": "Spedizioni", "group": "semantic"},
    {"id": "paraphrase", "query": "Quando arriva il pacco?",
     "source": "Spedizioni", "group": "paraphrase"},
    {"id": "return-rewrite", "query": "Vorrei restituire",
     "source": "Resi e Rimborsi", "group": "paraphrase"},
    {"id": "absent", "query": "garanzia meteoriti",
     "source": None, "group": "absent"},
    {"id": "unknown-sku", "query": "BOTTLE-THERMO-999",
     "source": None, "group": "adversarial"},
    {"id": "unknown-code", "query": "manuale ZX-999",
     "source": None, "group": "adversarial"},
    {"id": "absent-policy", "query": "Spedizione sulla Luna con garanzia meteoriti",
     "source": None, "group": "adversarial"},
    {"id": "mixed", "query": "Reso ordine 21: entro quanti giorni dalla consegna?",
     "source": "Resi e Rimborsi", "group": "mixed", "order": 21},
]


class LocalEmbeddings(Embeddings):
    # Sparse bag of domain concepts plus an unknown dimension. No learned model,
    # code hashing, expected IDs, query→rank table or network access.
    concepts = (
        {"spedizione", "spedizioni", "pacco", "arriva", "consegna", "giorni"},
        {"costa", "costo", "standard", "gratuita", "euro"},
        {"reso", "resi", "rimborso", "rimborsi", "difettosi"},
        {"pagamenti", "visa", "mastercard", "paypal", "bonifico"},
        {"borraccia", "termica", "acciaio", "caldo", "freddo"},
        {"maglietta", "cotone", "biologico", "gots"},
        {"felpa", "cappuccio", "tasca"},
        {"zaino", "laptop", "urban", "litri"},
        {"scarpe", "mesh", "aero", "tomaia"},
        {"kit", "aster", "manuale", "chiave", "montaggio", "mm"},
        {"ritiro", "sede", "conferma"},
    )

    def __init__(self):
        self.document_calls = 0
        self.query_calls = 0

    def vector(self, text):
        terms = Counter(tokenize(text))
        vector = [float(sum(terms[t] for t in group)) for group in self.concepts]
        vector.append(1.0 if not any(vector) else 0.0)
        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm for v in vector]

    def embed_documents(self, texts):
        self.document_calls += 1
        return [self.vector(text) for text in texts]

    def embed_query(self, text):
        self.query_calls += 1
        return self.vector(text)


class VectorStore:
    """Exact cosine over vectors; shared query cache across strategy experiments."""

    def __init__(self, docs=None, embeddings=None):
        self.docs = corpus() if docs is None else docs
        self.embeddings = embeddings or LocalEmbeddings()
        self.vectors = self.embeddings.embed_documents([d.page_content for d in self.docs])
        self.query_vectors = {}

    def get(self, **kwargs):
        return {"ids": [d.metadata["chunk_id"] for d in self.docs],
                "documents": [d.page_content for d in self.docs],
                "metadatas": [d.metadata for d in self.docs]}

    async def asimilarity_search_with_score(self, query, k=4):
        if query not in self.query_vectors:
            self.query_vectors[query] = self.embeddings.embed_query(query)
        vector = self.query_vectors[query]
        hits = [(doc, max(0.0, 1 - sum(a * b for a, b in zip(vector, dv, strict=True))))
                for doc, dv in zip(self.docs, self.vectors, strict=True)]
        return sorted(hits, key=lambda hit: (hit[1], hit[0].metadata["chunk_id"]))[:k]


class LocalModel:
    """Calls actual user query; quotes actual retrieved blocks, without expectations."""

    def __init__(self, query, order=None):
        self.query, self.order = query, order

    async def ainvoke(self, messages):
        outputs = [m for m in messages if isinstance(m, ToolMessage)]
        if not outputs:
            calls = [{"name": RAG, "args": {"domanda": self.query}, "id": "rag"}]
            if self.order:
                calls.append({"name": ORDER, "args": {"numero_ordine": self.order}, "id": "data"})
            return AIMessage(content="", tool_calls=calls)
        return AIMessage(content="\n".join(str(m.content) for m in outputs))
