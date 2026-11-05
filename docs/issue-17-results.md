# Issue #17 — baseline con provider reale

Stato al 2026-11-03: preparazione e controlli offline completati. **Nessuna chiamata
AI live eseguita e nessuna spesa autorizzata in questa attività.** Qualità, latenza
e costo del provider reale restano da misurare dopo consenso esplicito.

## Perimetro ripetibile

Si riusa `evals.run_agent_eval` della #3, con i suoi 30 casi originali invariati,
corpus sintetico di 8 documenti, catalogo Woo e sessioni sintetici. Il dataset
additivo `evals/issue17.jsonl` contiene quattro casi: follow-up sulla spedizione,
follow-up su un ordine, richiesta ambigua senza prodotto e isolamento di un ordine
altrui dopo aver consultato il proprio. Tre casi ricevono una **storia sintetica
prefissata**: non sono conversazioni generate dal modello da un turno all'altro
e non verificano persistenza, API HTTP o autenticazione WordPress end-to-end.

Il live usa generazione e embedding OpenAI reali sullo stesso corpus in memoria,
con ricerca coseno esatta. Non legge clienti, ordini o documenti del negozio; non
modifica Chroma. L'endpoint è fissato a `https://api.openai.com/v1`, indipendentemente
da override di sviluppo `OPENAI_BASE_URL`. Non usa LLM judge o LlamaParse.

## Preflight e consenso ancora richiesto

Modelli configurati: `gpt-4.1-mini` e `text-embedding-3-small`. Tariffe standard
verificate il 2026-11-03: $0.40 input e $1.60 output per milione di token generativi;
$0.02 per milione di token embedding. Il calcolo non applica sconti cache.
Fonti: [GPT-4.1 Mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
[text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small).
La documentazione contrassegna GPT-4.1 Mini come deprecated: la disponibilità
effettiva dell'account va verificata nello smoke, senza sostituzioni automatiche.

Con i default attuali: 4 step, 12 tentativi e 2 retry condivisi per turno,
100.000 unità di budget token per turno, 512 token output per chiamata, deadline
30 secondi per `answer()`. Timeout SDK generativo 15 secondi e retry SDK zero;
il retry applicativo resta limitato dal budget condiviso. Il setup embedding ha
una deadline propria di 30 secondi. Ogni input embedding è limitato a 8.191 byte
UTF-8; il preventivo somma separatamente i byte di tutti i documenti del corpus.

| Piano | Smoke iniziale | Baseline completa, consenso separato |
| --- | ---: | ---: |
| Casi × ripetizioni | 6 × 1 | 34 × 3 |
| Generazioni massime | 36 | 612 |
| Richieste embedding massime, incluso setup | 73 | 1.225 |
| Input generativo massimo conservativo | 600.000 | 10.200.000 |
| Output generativo massimo | 18.432 | 313.344 |
| Input embedding massimo conservativo | 590.913 | 10.026.945 |
| Preventivo massimo conservativo, USD | 0.28130946 | 4.78188930 |
| Soglia proposta per il preflight, USD | 0.30 | 5.00 |
| Somma deadline setup + turni, secondi | 210 | 3.090 |

Questi sono limiti conservativi per categoria, non quantità da sommare come
richieste indipendenti: modello, embedding e tool competono per il budget tentativi.
La somma delle deadline riguarda il lavoro del provider; import, costruzione client,
cleanup e scrittura del report aggiungono tempo locale al comando.

`--max-estimated-usd` rifiuta un live oltre preventivo o con modelli senza tariffa
registrata, prima di costruire client. È obbligatorio nella CLI live. **Non è un
limite di fatturazione del provider**: tariffa, disponibilità e consumo di richieste
interrotte devono essere riconciliati con l'account. Il report calcola il costo
stimato dai token di usage ricevuti e conta separatamente le richieste senza usage;
in quel caso il costo osservato è parziale. Il preflight non autorizza la spesa.

## Comandi pronti

Stima senza rete, chiavi o costruzione di client:

```bash
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --live --estimate --case ship-01 --case adv-sku --case ord-01 \
  --case ord-02 --case adv-absent --case adv-foreign
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --live --estimate --extra-golden /evals/issue17.jsonl --repeats 3
```

Smoke da eseguire **soltanto dopo autorizzazione esplicita** ai sei casi e al budget:

```bash
docker compose run --rm --no-deps -e PYTHONPATH=/app:/ chatbot-api \
  python -m evals.run_agent_eval --live --allow-external --max-estimated-usd 0.30 \
  --case ship-01 --case adv-sku --case ord-01 --case ord-02 \
  --case adv-absent --case adv-foreign --output /evals/results/issue-17-smoke.json
```

Il consenso allo smoke non comprende la baseline completa. Dopo il relativo
consenso, usare `--extra-golden /evals/issue17.jsonl --repeats 3
--max-estimated-usd 5.00` al posto della selezione `--case` e salvare
`issue-17-live-before.json`. Una replica confrontabile mantiene dataset e ripetizioni,
aggiunge `--baseline /evals/results/issue-17-live-before.json` e scrive un altro file.
Ripetere prima il preflight se cambiano modello, budget o configurazione.

## Evidenze offline

Validati 102/102 pass del runner esteso e **62 test mirati passati**: i 50 test
esistenti dell'eval e 12 controlli aggiuntivi su storia, preflight, selezione casi,
deadline setup, token embedding, usage mancante, percentili e assenza di payload
nel report. Ruff e `git diff --check` passano. I test bloccano le connessioni esterne;
la suite è stata rieseguita fuori sandbox perché il sandbox impedisce anche la
creazione del socket usato dal test della guardia di rete. Gli stessi **62 test
passano anche nel container backend** già presente, con `network_mode: none`:

```bash
docker compose run --rm --no-deps eval-offline pytest -q -p no:cacheprovider \
  tests/test_evals.py tests/test_issue17_eval.py
```

Comandi locali usati, con dipendenze già presenti:

```bash
OPENAI_API_KEY= PYTHONPATH=chatbot:. /home/emilianogastaldo/personal/aie/.venv/bin/python \
  -m pytest -q -p no:cacheprovider chatbot/tests/test_evals.py chatbot/tests/test_issue17_eval.py
OPENAI_API_KEY= PYTHONPATH=chatbot:. /home/emilianogastaldo/personal/aie/.venv/bin/python \
  -m evals.run_agent_eval --extra-golden evals/issue17.jsonl --repeats 3 \
  --commit 6eca6c1c3d6ddbe08708d706bf41a71102f94b17 \
  --output evals/results/issue-17-offline.json
```

Snapshot locale: commit base `6eca6c1c3d6ddbe08708d706bf41a71102f94b17`, con modifiche
non committate del lavoro parallelo. Report gitignored
`evals/results/issue-17-offline.json`:

| Fingerprint | SHA-256 |
| --- | --- |
| Dataset | `75a2dd9ae3ca0fbf8d2fac5283ede4cea7a9502fb32d627c7a713eedc39a6fc0` |
| Fixture | `5e442b55ccfcf255d0552314fe52da3f53f463b739486920bef16a850d068519` |
| Implementazione al momento del run | `0c22de072ef4d0bbd81cff116ea6e33a2763824245ff32c9ae7b5cda52321b55` |

L'aggiunta di `history` al dataset validato e dei piani sintetici cambia i digest:
le baseline precedenti vengono correttamente rifiutate, anche sui 30 casi originali.
Lo schema delle metriche resta 2; serve una nuova baseline con questi fingerprint.

Il 100% offline misura regressioni di orchestrazione con LLM scriptato, non qualità,
tempi o costi di un provider reale. Il live misurerà routing, tool, controlli lessicali
sui fatti/astensioni, hit@k/MRR, citazioni, token, chiamate e latenza p50/p95/massima.
Le regex possono penalizzare parafrasi valide o perdere contraddizioni non previste;
le citazioni verificano provenienza, non ogni implicazione semantica. Lo smoke con
sei osservazioni serve a verificare il flusso; la p95 sarà il massimo del campione.

Restano da misurare tutti i risultati live, inclusi disponibilità del modello,
failure mode reali, variazione fra ripetizioni e costo per risposta. Questa attività
non ha eseguito lo sweep sui dati reali del negozio né la latenza HTTP/Woo/Chroma.

## Revisione prima del push

Corretto il percorso Python `evaluate(live=True, allow_external=True)`: ora
richiede `max_estimated_usd` esattamente come la CLI, prima di costruire provider.
La regressione copre anche il budget assente. Sul lavoro integrato delle issue
#16–19 sono passati **248 test offline**, lint completo e `git diff --check`.
Nessuna run live è stata autorizzata o eseguita durante la revisione.
