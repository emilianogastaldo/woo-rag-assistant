"""BM25 over verified Chroma chunks. No separate persistent source of truth."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

from langchain_core.documents import Document

from app.rag.chunks import verified_chunk_id

# Keep codes and decimal numbers whole: AB-123 != AB-124, 4,90 != 49.
TOKEN = re.compile(r"[^\W_]+(?:[-_.,/][^\W_]+)*", re.UNICODE)
STOPWORDS = frozenset(
    "a ad al alla alle allo ai agli anche che chi ci come con cosa da dal dalla dalle "
    "dei del della delle dello di e è ed gli ha ho i il in io la le lo ma mi ne nel "
    "nella nelle o per più può puoi quale quali quando quanto quanti questa questo "
    "se si sono su sul sulla tra un una uno vorrei sapere sku codice prodotto".split()
)


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.translate(str.maketrans({c: "-" for c in "‐‑‒–—−"}))
    return [token for token in TOKEN.findall(normalized) if token not in STOPWORDS]


def code_tokens(text: str) -> set[str]:
    """Explicit compound/alphanumeric identifiers; plain quantities are not codes."""
    return {
        token for token in tokenize(text)
        if any(c.isalpha() for c in token)
        and (any(c.isdigit() for c in token) or "-" in token or "_" in token)
    }


def searchable_text(doc: Document) -> str:
    # SKU stays metadata: chunk-v1 identity and ingestion text remain unchanged.
    return "\n".join((doc.page_content, str(doc.metadata.get("title", "")),
                      str(doc.metadata.get("sku", ""))))


class BM25Index:
    def __init__(self, documents: list[Document], *, k1: float = 1.5, b: float = 0.75):
        if not math.isfinite(k1) or k1 <= 0 or not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError("invalid BM25 parameters")
        self.k1, self.b = k1, b
        self.documents = {
            identifier: doc for doc in documents
            if (identifier := verified_chunk_id(doc)) is not None
        }
        self.terms = {
            identifier: Counter(tokenize(searchable_text(doc)))
            for identifier, doc in self.documents.items()
        }
        self.lengths = {key: sum(counts.values()) for key, counts in self.terms.items()}
        self.average_length = sum(self.lengths.values()) / (len(self.lengths) or 1)
        self.frequencies = Counter(term for counts in self.terms.values() for term in counts)

    def search(self, query: str, k: int) -> list[tuple[Document, float]]:
        terms = set(tokenize(query))
        hits = []
        for identifier, counts in self.terms.items():
            score = 0.0
            for term in sorted(terms & counts.keys()):
                df, n = self.frequencies[term], len(self.documents)
                idf = math.log1p((n - df + 0.5) / (df + 0.5))
                tf = counts[term]
                norm = 1 - self.b + self.b * self.lengths[identifier] / self.average_length
                score += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
            if score > 0:
                hits.append((self.documents[identifier], score))
        # Stable ties, independent of Chroma get order / Python hash randomization.
        return sorted(hits, key=lambda hit: (-hit[1], hit[0].metadata["chunk_id"]))[:k]


def documents_from_records(records: dict) -> list[Document]:
    """Require both stored record ID and verified metadata ID to agree."""
    docs = []
    for identifier, text, metadata in zip(
        records["ids"], records["documents"], records["metadatas"], strict=True,
    ):
        if not text or not metadata:
            continue
        doc = Document(id=identifier, page_content=text, metadata=metadata)
        if verified_chunk_id(doc) == identifier:
            docs.append(doc)
    return docs
