# Architettura e decisioni di design

> Documento vivo: le decisioni vanno annotate qui man mano che vengono prese.

## Panoramica

```
Widget chat (JS) → Backend FastAPI → { ChromaDB | LLM API | WooCommerce REST }
```

## Componenti backend

- **Middleware auth** — valida la sessione, registra condizionalmente i tool.
- **Agente router** — decide se usare RAG, tool o entrambi.
- **Catena RAG** — retrieval + generazione con citazione fonti (LangChain).
- **Tool ordini** — read-only, scoped sul cliente della sessione.

## Pipeline di ingestion (offline)

Script one-shot (`docker compose run --rm ingest`): legge prodotti/pagine da
WooCommerce → chunking → embedding → ChromaDB.

## Decisioni

_(nessuna decisione registrata ancora)_
