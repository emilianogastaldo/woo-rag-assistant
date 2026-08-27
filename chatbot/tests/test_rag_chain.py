"""Catena RAG: soglia di pertinenza e citazione delle fonti."""
from __future__ import annotations

from langchain_core.documents import Document

from app.config import settings
from app.rag.chain import NO_RESULTS, KnowledgeBase


class FakeStore:
    def __init__(self, hits: list[tuple[Document, float]]) -> None:
        self.hits = hits
        self.queries: list[str] = []

    async def asimilarity_search_with_score(self, query: str, k: int = 4):
        self.queries.append(query)
        return self.hits[:k]


def doc(title: str, text: str, url: str = "http://localhost:8080/spedizioni") -> Document:
    return Document(
        page_content=text,
        metadata={"title": title, "source": url, "type": "page"},
    )


async def test_chunk_pertinenti_producono_contesto_e_fonti():
    store = FakeStore([(doc("Spedizioni", "La spedizione standard costa 4,90 €."), 0.2)])
    result = await KnowledgeBase(store=store).search("quanto costa la spedizione?")
    assert result.found
    assert "4,90" in result.context
    assert [s.title for s in result.sources] == ["Spedizioni"]


async def test_chunk_oltre_soglia_scartati_niente_invenzioni():
    oltre = settings.retrieval_max_distance + 0.1
    store = FakeStore([(doc("Spedizioni", "testo non pertinente"), oltre)])
    result = await KnowledgeBase(store=store).search("che tempo fa domani?")
    assert not result.found
    assert result.context == NO_RESULTS
    assert result.sources == []


async def test_fonti_deduplicate_su_piu_chunk_dello_stesso_documento():
    store = FakeStore(
        [
            (doc("Resi e Rimborsi", "parte uno", "http://x/resi"), 0.1),
            (doc("Resi e Rimborsi", "parte due", "http://x/resi"), 0.15),
        ]
    )
    result = await KnowledgeBase(store=store).search("come funziona il reso?")
    assert len(result.sources) == 1
    assert "parte uno" in result.context and "parte due" in result.context
