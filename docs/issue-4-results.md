# Issue #4 — risultati e decisione

Data: 19 settembre 2026. Default finale: **semantic, k=4, distanza massima 0.6,
retry=0**. Hybrid e retry sono disponibili esplicitamente; nessun MMR/reranker.
Lo smoke mostra un miglioramento mirato su SKU/codice avversario, ma non è un
benchmark sufficiente per promuovere un default su tutte le domande del negozio.

## Provenienza

- Baseline main: `fa7e52a9c3f9c8ac2ca90a9399006cdb9fdfca33`, dopo merge #3 e #2,
  worktree pulito e `git pull --ff-only` prima del branch.
- Primo smoke autorizzato: `f2b7798bba243572d4a9aeacb0361d234991dde0`.
- Correzione del retry: `3f0b3d9f75bfe872e3b7fc052b813b3ca6c7debb`.
- Codice dei report finali: `47dbbd7b35ed0c566116931fc1eabec19b689a8b`.
  I commit successivi di documentazione non cambiano il codice misurato.
- Agent eval: schema **2**, `golden.jsonl` e `fixtures.py` invariati, 30 casi × 3.
  Confronto automatico compatibile; nessun controllo di hash/schema aggirato.
- Ablazioni retrieval: benchmark distinto `retrieval-ablation`, schema proprio 1,
  `retrieval_fixtures.py`: 12 chunk, 16 domande, 6 configurazioni × 3 = 288 run.
  Hash di corpus/dataset/fixture/implementazione nei JSON. Non è una migrazione
  del report agent v2 né un confronto diretto con il suo 100%.
- Docker context `default`, Engine 29.8.0. Backend immagine locale
  `sha256:1c6ad01a731ecbfbaba94c1b4ad7993100adfdece57b7c33edde58c9ae2b71c6`.
  Nessuna dipendenza aggiunta o ricostruzione necessaria.
- Chroma 1.0.0 reale, immagine fissata a
  `sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6`.

Tutti i JSON restano gitignored. File finali in `evals/results/`:
`issue-4-before.json`, `issue-4-after.json`, `issue-4-retrieval-offline.json`,
`issue-4-embedding-smoke.json`, `issue-4-embedding-replay.json` e
`woo-issue4-ae5837ddb428/{integration,inventory}.json`.
Il report iniziale è conservato: l'unico arricchimento post-run è commit/comando
di provenienza, senza modifica di metriche, fixture o schema.

## Verifiche

| Livello | Esito | Evidenza e limite |
| --- | --- | --- |
| Lint | PASS | Ruff su backend, test ed eval. |
| Unit test offline | PASS | 148 test, rete bloccata; un warning preesistente Starlette/AnyIO. |
| Agent eval v2 | PASS | Prima 90/90, dopo 90/90; nessuna regressione qualitativa, di chiamate/token o oltre la soglia di latenza del comparatore. |
| Ablazioni con adapter locali | PASS meccanica; FAIL copertura completa | Hybrid recupera codici/SKU; `absent-policy` resta falso positivo sia semantic sia hybrid. Non è una stima della qualità OpenAI. |
| Integrazione Docker locale | PASS | Upsert ripetuto, ID, lettura/BM25, RRF/deduplica, citazioni, astensione su codici sconosciuti, sostituzione a parità di cardinalità e record legacy su Chroma reale. Stesso limite qualitativo `absent-policy` degli adapter locali. |
| Smoke embedding reale autorizzato | PASS hybrid senza retry; FAIL retry iniziale | Sei casi, un solo batch; nessuna generazione reale. Regressione del retry descritta sotto. |
| Replay offline della correzione | PASS | Medesimi punteggi coseno misurati, BM25/RRF/gate ricalcolati: nessuna regressione qualitativa, astensione ripristinata. |
| Nuovo live dopo la correzione | NON ESEGUITO | Il consenso autorizzava una sola richiesta, già usata; la correzione è verificata con replay e test locali. |
| Benchmark live completo/ripetuto | NON ESEGUITO | Richiede consenso separato; necessario prima di generalizzare il risultato e promuovere il default. |
| Generazione live, browser, demo/reingestion | NON ESEGUITO | Non coperti dallo smoke richiesto; collection e volumi della demo non modificati dall'harness. |

## Confronti con corpus e adapter locali

`first` misura il contesto ammesso prima del retry; `final` dopo l'eventuale retry.
Denominatori: 12 domande con fonte attesa, 4 senza risposta; ciascuna ripetuta 3 volte.
Vettori locali calcolati dal testo, con codici intenzionalmente ignorati: la loro
utilità è verificare i meccanismi. Le stesse metriche qualitative si riproducono
nello store coseno in memoria e in Chroma reale.

| Configurazione | Hit@4 first | MRR first | Hit@4 final | MRR final | Astensione |
| --- | ---: | ---: | ---: | ---: | ---: |
| semantic | 0.5833 | 0.5000 | 0.5833 | 0.5000 | 0.50 |
| hybrid, candidati 12, RRF 60, pesi 1/1 | 0.9167 | 0.8750 | 0.9167 | 0.8750 | 0.75 |
| hybrid, solo candidati → 4 | 0.9167 | 0.8750 | 0.9167 | 0.8750 | 0.75 |
| hybrid, solo RRF → 20 | 0.9167 | 0.8750 | 0.9167 | 0.8750 | 0.75 |
| hybrid, solo peso lessicale → 2 | 0.9167 | 0.9167 | 0.9167 | 0.9167 | 0.75 |
| hybrid, solo retry → 1 | 0.9167 | 0.8750 | 1.0000 | 0.9583 | 0.75 |

Variazioni per domanda, registrate nel JSON anche quando sono nulle:

- Hybrid recupera `sku-only`, `sku-question`, `sku-neighbor`, `pickup-code`;
  migliora il rango di `manual-neighbor` (2 → 1) e l'astensione di `unknown-code`.
- Candidati 4 e RRF 20 non migliorano metriche qualitative rispetto a hybrid.
- Peso lessicale 2 migliora soltanto `numeric` (rango 2 → 1): insufficiente per
  cambiare il peso di default senza altre evidenze.
- Retry recupera `return-rewrite` al **secondo** tentativo. Non altera first-hit;
  aggiunge una query anche a `unknown-sku` e `unknown-code` senza beneficio.
- `absent-policy` resta errata con i vettori locali, anche prima delle modifiche;
  non viene nascosta o attribuita al successo del retry. Nessuna regressione
  qualitativa nuova nelle varianti finali, ma questi risultati non sono “tutto corretto”.

Costi provider locali: **zero richieste/token/USD**. Latenze medie dell'ultimo
run su Chroma reale (millisecondi, misure indicative su tre ripetizioni, senza
test statistico, ordine delle varianti fisso):

| Configurazione | Totale agente locale | Secondo stadio | Solo retry |
| --- | ---: | ---: | ---: |
| semantic | 2.94 | 0.06 | 0 |
| hybrid | 5.88 | 2.86 | 0 |
| candidati 4 | 6.62 | 3.19 | 0 |
| RRF 20 | 5.94 | 2.90 | 0 |
| peso lessicale 2 | 5.90 | 2.86 | 0 |
| retry 1 | 6.56 | 2.97 | 0.59 |

Il secondo stadio include anche lettura/costruzione BM25 e gate, separati nel
report. Il costo di ripetere embedding veri dipende dal provider; nella produzione
il retry aggiunge al massimo una query embedding per chiamata RAG. Il runner
live dell'agente ora include quel moltiplicatore nella stima massima delle chiamate.

## Smoke autorizzato: embedding reali

Consenso esplicito in sessione: massimo **$0,001**, sei casi, una ripetizione,
una richiesta embedding, zero chiamate generative/judge/riscrittura/SDK retry.
Corpus sintetico versionato, 24 input deduplicati fra 12 testi e query/riformulazioni.
Modello effettivo: OpenAI `text-embedding-3-small`. Nessuna informazione del
negozio reale inviata, nessuna collection o servizio demo utilizzato.

Misurati: **1 richiesta, 557 token embedding, 725.52 ms** per il batch condiviso.
Costo stimato da usage × [tariffa ufficiale](https://developers.openai.com/api/docs/models/text-embedding-3-small)
di $0,02/milione: **$0,00001114**. Non è una lettura della fattura del provider.
Limite conservativo pre-run: 1.723 token, $0,00003446; limite hard input 12.000
token byte-BPE, timeout 30 s/richiesta e 60 s/run. Nessun'altra richiesta eseguita.

| Configurazione | Hit@4 (4 casi) | MRR | Astensione (2 casi) | Secondo stadio medio |
| --- | ---: | ---: | ---: | ---: |
| semantic | 1.00 | 0.875 | 0.50 | 0.045 ms |
| hybrid senza retry | 1.00 | 1.000 | 1.00 | 0.870 ms |
| candidati 4 | 1.00 | 1.000 | 1.00 | 0.643 ms |
| RRF 20 | 1.00 | 1.000 | 1.00 | 0.850 ms |
| peso lessicale 2 | 1.00 | 1.000 | 1.00 | 0.808 ms |
| retry iniziale | 1.00 | 1.000 | 0.50 | 0.943 ms |

Le latenze delle varianti sono locali, con embedding già in cache, e non includono
i 725.52 ms del batch. Generazione/ordini rimangono adapter locali. La precisione
delle citazioni riflette il modello locale che cita tutti i passaggi: non valuta
l'entailment di risposte prodotte da un LLM reale.

Risultati per caso: `sku-only` passa da rango 2 a 1; `unknown-code` da risposta
indebita ad astensione; `manual-code`, `paraphrase`, `mixed` e `absent-policy`
non regrediscono con hybrid senza retry. Nessuna evidenza per MMR/reranking.

**Regressione scoperta e corretta:** con retry, `absent-policy` inizialmente si
asteneva ma la query compressa produceva un falso positivo sopra soglia semantica.
Il primo tentativo rimane corretto: il fallimento è esclusivamente nel secondo.
La correzione richiede anche copertura lessicale dei termini riformulati
(`lexical_min_coverage=1.0`), mantenendo codici, numeri e negazioni. Un miglioramento
del solo score coseno dopo compressione non basta più per riaprire l'astensione.

Il report originale **non è stato sostituito**. Il replay senza rete ricostruisce
i ranking completi dai punteggi misurati e ricalcola BM25/RRF/gate con la correzione:
`absent-policy` torna ad astensione, 4/4 hit e 2/2 astensioni anche con retry,
senza altre regressioni. Una nuova unit regression copre la stessa condizione;
il caso positivo `return-rewrite` resta recuperabile con gli adapter locali.
Questo è **replay offline**, non un secondo smoke live o una nuova misura ANN.

## Comandi eseguiti

```bash
docker context show
docker info --format '{{.ServerVersion}}'
docker compose ls -a
docker compose run --rm --no-deps eval-offline ruff check . /evals --config /app/pyproject.toml
docker compose run --rm --no-deps eval-offline pytest -q
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --repeats 3 --output /evals/results/issue-4-before.json
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --repeats 3 --baseline /evals/results/issue-4-before.json \
  --output /evals/results/issue-4-after.json --commit 47dbbd7b35ed0c566116931fc1eabec19b689a8b
docker compose run --rm --no-deps eval-offline python -m evals.run_retrieval_eval \
  --repeats 3 --output /evals/results/issue-4-retrieval-offline.json \
  --commit 47dbbd7b35ed0c566116931fc1eabec19b689a8b
python3 evals/run_local_integration.py --commit 47dbbd7b35ed0c566116931fc1eabec19b689a8b
# Una sola esecuzione dopo consenso; progetto già ripulito:
docker compose --env-file .env -f evals/compose.smoke.yml -p woo-issue4-smoke-f2b7798 \
  run --rm --no-deps smoke python -m evals.run_embedding_smoke \
  --live --allow-external --max-cost-usd 0.001 \
  --commit f2b7798bba243572d4a9aeacb0361d234991dde0 \
  --output /results/issue-4-embedding-smoke.json
docker compose --env-file .env -f evals/compose.smoke.yml -p woo-issue4-smoke-f2b7798 down --timeout 10
docker compose run --rm --no-deps eval-offline python -m evals.run_embedding_smoke \
  --replay /evals/results/issue-4-embedding-smoke.json \
  --output /evals/results/issue-4-embedding-replay.json \
  --commit 47dbbd7b35ed0c566116931fc1eabec19b689a8b
```

Il sandbox ha richiesto accesso al socket Docker; nessun cambio del contesto
globale. Ogni integrazione ha creato e rimosso soltanto risorse `woo-issue4-*` del
proprio run; cleanup finale verificato per container, rete e volume. Nessun prune,
nessun reset/ingest della collection attiva. I nomi del run finale e i digest
effettivi sono conservati nell'inventario gitignored.

## Decisione e criterio ancora aperto

L'implementazione e le verifiche meccaniche sono disponibili. Il miglioramento
con embedding reali è misurato **solo sullo smoke di sei casi**: non dimostra
un guadagno generalizzato né una riduzione universale dei falsi positivi. La
selezione di un nuovo default e la calibrazione della soglia su un benchmark
semantico più ampio/ripetuto restano aperte, con consenso separato. Fino ad allora
semantic e retry disabilitato conservano il comportamento coperto dalla baseline.
