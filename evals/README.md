# Evaluation del loop agente

Il golden ha 30 casi: RAG, dati, RAG+dati, nessuna fonte. Comprende SKU/codici,
parafrasi, conoscenza assente, login, ordine altrui, tool assente e un tentativo di
usare il completamento amministrativo come prova di consegna. I campi precedenti
`ground_truth`, `expected_type`, `expected_source` restano compatibili con lo sweep.

## Offline e CI

Dalla root, con l'immagine backend già disponibile:

```bash
docker compose run --rm --no-deps eval-offline ruff check . /evals --config /app/pyproject.toml
docker compose run --rm --no-deps eval-offline pytest -q
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --repeats 3 --output /evals/results/before.json
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --repeats 3 --baseline /evals/results/before.json --output /evals/results/after.json
```

Il container non ha rete, credenziali o dipendenze di servizio. L'installazione
dell'immagine/delle dipendenze è un passaggio separato che richiede rete; il runner
offline e pytest bloccano DNS e connessioni anche quando eseguiti senza Docker.
CI usa questi stessi test e il runner, e pubblica `ci.json` come artifact della PR.

`fixtures.py` contiene corpus, dati Woo e script del modello, indipendenti dalle
aspettative del golden. Si usano `answer()`, `KnowledgeBase`, `OrderService` e
`CatalogService` reali. Il modello finto controlla che il loop gli consegni i risultati
dei tool e riporta quei contenuti. L'ordine 23 appartiene a un cliente diverso;
l'ordine 21 è consegnato il 05/09/2026 (scadenza 05/10/2026), il 24 è completato ma
senza consegna verificata. Il prompt usa sempre il 19/09/2026.

I punteggi offline sono test di regressione dell'orchestrazione, **non** una stima
dell'accuratezza di un LLM o della qualità degli embedding. Metriche funzionali e
contatori sono deterministici; tempi di esecuzione e setup sono misurati e variabili.

## Live sintetico, solo dopo autorizzazione

Per stimare senza alcuna chiamata esterna:

```bash
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --live --estimate --repeats 3
```

Il live invia a OpenAI le domande, il prompt, le descrizioni dei tool, il corpus
sintetico versionato e i risultati sintetici dei tool. Non legge ordini reali.
Richiede `OPENAI_API_KEY`; usa `OPENAI_MODEL` e `EMBEDDING_MODEL` del backend.
Le due opzioni di consenso sono obbligatorie, anche quando la chiave è già presente:

```bash
# ESEGUIRE SOLTANTO DOPO AUTORIZZAZIONE ESPLICITA alle chiamate esterne.
docker compose run --rm --no-deps -e PYTHONPATH=/app:/ chatbot-api \
  python -m evals.run_agent_eval --live --allow-external --repeats 3 \
  --output /evals/results/live-before.json
# Dopo la modifica da confrontare, mantenendo stesso dataset/fixture/ripetizioni:
docker compose run --rm --no-deps -e PYTHONPATH=/app:/ chatbot-api \
  python -m evals.run_agent_eval --live --allow-external --repeats 3 \
  --baseline /evals/results/live-before.json --output /evals/results/live-after.json
```

La ricerca live usa embedding veri e distanza coseno esatta in memoria; non verifica
l'indice ANN di Chroma né ingestion/chunking del negozio. Woo e le sessioni restano
sintetici, mentre il modello sceglie liberamente i tool. Il caso tool indisponibile
verifica il rifiuto dell'ospite nel live; lo script offline forza esplicitamente una
chiamata a un tool assente per esercitare quel ramo del loop.

Costo: con N casi, R ripetizioni e S=`AGENT_MAX_STEPS`, al massimo N×R×S richieste di
generazione e 1+N×R×S richieste embedding (un batch iniziale per gli 8 documenti).
Tool calling parallelo disabilitato, retry SDK disabilitati, timeout 30 secondi e
massimo 512 token generati per chiamata. Con 30 casi, 3 ripetizioni e S=4: fino a
360 richieste di generazione, 361 di embedding, 184.320 token di output; **ogni run**
prima/dopo ha questo budget. Non ci sono chiamate a un LLM judge.

Il costo monetario dipende dai token di input (prompt/storia/tool inclusi), output
ed embedding e dalle tariffe del modello scelto: `input_tokens × prezzo_input +
output_tokens × prezzo_output + embedding_tokens × prezzo_embedding`, usando le
unità della tariffa. La stima è di richieste, non un preventivo in euro né un limite
di spesa. Il report misura token generativi e chiamate effettive; non misura i token
embedding. Una temperatura zero non rende le risposte live deterministiche:
confrontare più ripetizioni e interpretare le variazioni prima di attribuirle al codice.

## Metriche e confronto

| Campo | Definizione |
| --- | --- |
| `routing_accuracy` | Strada derivata dai tool eseguiti uguale a quella attesa. RAG selezionato ma vuoto resta `rag`; `none` significa nessun tool eseguito. |
| `tool_accuracy` | Uguaglianza dei set di tool attesi/eseguiti. Le ripetizioni non cambiano il set ma aumentano i contatori. |
| `hit_at_k`, `mrr` | Presenza e rango reciproco della fonte attesa nel primo retrieval reale della domanda, prima della soglia; k è nella configurazione. Mancato retrieval con fonte attesa vale zero. |
| `citation_precision` | Fonti strutturate corrette / fonti strutturate uniche restituite; riconoscimento da SKU o titolo nei metadati del retrieval. Zero se manca una fonte richiesta, `null` se non è richiesta e non ci sono citazioni. |
| `citation_recall` | Presenza della fonte richiesta, per impedire che omettere tutte le fonti migliori la precisione. |
| `answer_correct` | Tutte le regex `answer_all` trovate e nessuna `answer_none`. Le regex includono fatti, astensioni, invito al login e divieti di divulgazione. |
| `abstention_correct` | Stesso controllo nei soli casi `abstain`, `decline`, `login`, `not_found`; `null` negli altri. |
| `latency_ms` | Durata del singolo `answer()`, include modello/tool; setup del corpus separato. |
| `*_calls`, `*_tokens` | Tentativi modello, tool richiesti (inclusi assenti), tool assenti, retrieval, chiamate Woo simulate, token input/output generativi. `embedding_calls` a livello run include il setup. |

Le metriche opzionali `null` sono escluse dalla media: ogni aggregato riporta anche
`n`, il denominatore. Ogni errore di esecuzione produce una riga fallita e non viene
escluso dal report. Il pass richiede tutti i controlli qualitativi applicabili a 1
(MRR può essere inferiore a 1 se la fonte è comunque nei primi k).

La correttezza è un controllo lessicale riproducibile, non una valutazione semantica
completa: può bocciare parafrasi corrette o non cogliere contraddizioni inattese.
La precisione valuta `sources`, non le citazioni libere nel testo. Queste misure sono
indicatori parziali di groundedness e non certificano l'assenza di allucinazioni.

Il JSON versionato salva ID, ripetizione, strada/tool da un vocabolario chiuso,
metriche, hash del dataset/fixture/implementazione e configurazione. I nomi modello
sono identificati da hash; chiavi, URL, email, customer ID, prompt, argomenti tool,
risposte e stack trace non vengono scritti. I report locali sono gitignored.

`--baseline` richiede stessi schema, golden, fixture, modalità e ripetizioni;
configurazione e implementazione possono cambiare. L'incompatibilità è verificata
prima di chiamare i provider. `comparison` contiene prima/dopo/delta per ogni domanda
e una lista di regressioni: cali qualitativi, aumenti di chiamate/token e latenza
che aumenta **sia** oltre il 20% **sia** oltre 10 ms. Non è un test statistico.
Codici di uscita: 0 tutti passati senza regressioni, 1 fallimenti/regressioni,
2 errore di configurazione/dataset/baseline/setup; gli errori grezzi sono soppressi.

## Sweep di retrieval del negozio (perimetro distinto)

`run_eval.py` rimane lo sweep su chunk size/Chroma per calibrare la soglia. Legge
documenti dal negozio e li invia al provider embedding: richiede una **specifica
autorizzazione anche per questi dati**, non soltanto per il benchmark sintetico.

```bash
# Solo stima, senza rete:
docker compose run --rm --no-deps eval-offline python /evals/run_eval.py --estimate
# Solo dopo autorizzazione per i documenti del negozio:
docker compose run --rm -v "$PWD/evals:/evals:ro" ingest \
  python /evals/run_eval.py --live --allow-external
```

Lo sweep precedente stampa hit@1/3/5, MRR e distanze; i report JSON prima/dopo sono
forniti dal nuovo runner dell'agente. Non eseguire ingestion o il live in CI.
