"""Eval di RETRIEVAL per il RAG (deterministico, senza LLM).

Misura se il retriever pesca la fonte giusta e in che posizione, facendo uno sweep
su diversi chunk_size per aiutare a scegliere i parametri. Le metriche di generazione
(faithfulness/correctness via RAGAS) verranno aggiunte quando esisterà la catena RAG.

Esecuzione (dalla root del repo):
  docker compose run --rm -v "$PWD/evals:/evals" ingest python /evals/run_eval.py

Metriche:
  - hit@k : frazione di domande per cui la fonte attesa è tra i primi k risultati
  - MRR   : media di 1/rango della prima fonte corretta (0 se fuori dai primi k)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ingest import gather_documents
from app.rag.store import get_chroma_client, get_vector_store

GOLDEN = Path("/evals/golden.jsonl")
MAX_K = 5
KS = (1, 3, 5)
# (chunk_size, overlap ~15%)
CONFIGS = [(400, 60), (600, 90), (800, 120), (1000, 150), (1200, 180)]
RETRIEVAL_TYPES = {"page", "product", "mixed"}


def load_cases() -> list[dict]:
    return [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]


def matches(meta: dict, case: dict) -> bool:
    if case["expected_type"] == "product":
        return meta.get("sku") == case["expected_source"]
    if case["expected_type"] in ("page", "mixed"):
        return meta.get("title") == case["expected_source"]
    return False


def first_hit_rank(results: list, case: dict) -> int | None:
    for rank, (doc, _score) in enumerate(results, start=1):
        if matches(doc.metadata, case):
            return rank
    return None


def main() -> None:
    cases = load_cases()
    retrieval_cases = [c for c in cases if c["expected_type"] in RETRIEVAL_TYPES]
    ood_cases = [c for c in cases if c["expected_type"] == "out_of_domain"]
    print(f"Golden: {len(cases)} casi totali | {len(retrieval_cases)} di retrieval | {len(ood_cases)} fuori dominio\n")

    print("Raccolta documenti sorgente (una volta)...")
    docs = asyncio.run(gather_documents())
    client = get_chroma_client()

    print("\n=== SWEEP RETRIEVAL ===")
    header = f"{'chunk/overlap':<16}{'#chunk':>8}{'hit@1':>8}{'hit@3':>8}{'hit@5':>8}{'MRR':>8}"
    print(header)
    print("-" * len(header))

    best = None
    for cs, ov in CONFIGS:
        chunks = RecursiveCharacterTextSplitter(chunk_size=cs, chunk_overlap=ov).split_documents(docs)
        name = f"eval_{cs}_{ov}"
        try:
            client.delete_collection(name)
        except Exception:
            pass
        store = get_vector_store(client=client, collection_name=name)
        store.add_documents(chunks)

        ranks = []
        for case in retrieval_cases:
            results = store.similarity_search_with_score(case["question"], k=MAX_K)
            ranks.append(first_hit_rank(results, case))

        n = len(retrieval_cases)
        hits = {k: sum(1 for r in ranks if r is not None and r <= k) / n for k in KS}
        mrr = sum((1.0 / r) for r in ranks if r is not None) / n
        print(f"{f'{cs}/{ov}':<16}{len(chunks):>8}{hits[1]:>8.2f}{hits[3]:>8.2f}{hits[5]:>8.2f}{mrr:>8.3f}")

        score = (hits[3], mrr)
        if best is None or score > best[0]:
            best = (score, cs, ov, name)

        # tieni l'ultima collection buona per l'analisi OOD, pulisci le altre
        if best[3] != name:
            try:
                client.delete_collection(name)
            except Exception:
                pass

    _score, best_cs, best_ov, best_name = best
    print(f"\nMigliore per hit@3/MRR: chunk_size={best_cs} overlap={best_ov}")

    # --- Separazione in-dominio vs fuori-dominio (per soglia "non lo so") ---
    store = get_vector_store(client=client, collection_name=best_name)
    print("\n=== SEPARAZIONE (distanza top-1: più bassa = più pertinente) ===")

    def top1_distance(q: str) -> float:
        res = store.similarity_search_with_score(q, k=1)
        return res[0][1] if res else float("nan")

    in_d = [top1_distance(c["question"]) for c in retrieval_cases]
    ood = [top1_distance(c["question"]) for c in ood_cases]
    print(f"  in-dominio : min={min(in_d):.3f}  max={max(in_d):.3f}  media={sum(in_d)/len(in_d):.3f}")
    if ood:
        print(f"  fuori-dom. : min={min(ood):.3f}  max={max(ood):.3f}  media={sum(ood)/len(ood):.3f}")
        print(f"  -> una soglia tra {max(in_d):.3f} e {min(ood):.3f} separerebbe i due gruppi"
              if max(in_d) < min(ood) else "  -> ATTENZIONE: i gruppi si sovrappongono, soglia netta non ovvia")

    try:
        client.delete_collection(best_name)
    except Exception:
        pass


if __name__ == "__main__":
    main()
