"""Attribuisce solo i chunk citati nella risposta e recuperati nel turno corrente."""
from __future__ import annotations

import re
from typing import TypedDict

from app.rag.chain import Source

# Comprende anche ID inventati/malformati per rimuoverli dal testo restituito.
CITATION = re.compile(r"\[(chunk-[^\[\]\s]*)\]")


class CitedSource(TypedDict):
    title: str
    url: str
    type: str
    chunk_ids: list[str]


def validate_citations(reply: str, chunks: dict[str, Source]) -> tuple[str, list[CitedSource]]:
    sources: dict[tuple[str, str], CitedSource] = {}
    for match in CITATION.finditer(reply):
        identifier = match.group(1)
        source = chunks.get(identifier)
        if source is None:
            continue
        key = (source.url, source.type)
        if key not in sources:
            sources[key] = CitedSource(
                title=source.title, url=source.url, type=source.type, chunk_ids=[],
            )
        if identifier not in sources[key]["chunk_ids"]:
            sources[key]["chunk_ids"].append(identifier)
    cleaned = CITATION.sub(lambda m: m.group(0) if m.group(1) in chunks else "", reply)
    return cleaned.strip(), list(sources.values())
