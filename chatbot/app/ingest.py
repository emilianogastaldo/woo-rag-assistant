"""Pipeline di ingestion offline (script one-shot).

Esecuzione: `docker compose run --rm ingest`

Flusso previsto:
  1. Legge prodotti e pagine (FAQ, spedizioni, resi) da WooCommerce.
  2. Chunking del contenuto.
  3. Embedding dei chunk.
  4. Scrittura nel vector store ChromaDB.

v1: stub. L'implementazione arriverà nel blocco dedicato al RAG.
"""


def main() -> None:
    print("[ingest] stub: la pipeline di ingestion non è ancora implementata.")


if __name__ == "__main__":
    main()
