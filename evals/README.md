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

Costo: `--estimate` calcola limiti conservativi usando step, tentativi e retry
condivisi. Con 30 casi × 3 e i default #5: al massimo 1.080 unità di budget per
run (incluse le operazioni locali contabilizzate), fino a 540 richieste modello
e 276.480 token output. Il tetto embedding conservativo è 1.081 includendo il
batch iniziale del corpus. Questi massimi per categoria non si sommano: modello,
embedding, tool e retry competono per il medesimo budget. Retry SDK zero, output
512 token/chiamata e deadline 30 s/turno. Non ci sono chiamate a un LLM judge.

Il costo monetario dipende dai token di input (prompt/storia/tool inclusi), output
ed embedding e dalle tariffe del modello scelto: `input_tokens × prezzo_input +
output_tokens × prezzo_output + embedding_tokens × prezzo_embedding`, usando le
unità della tariffa. La stima è di richieste, non un preventivo in euro né un limite
di spesa. Il report misura token generativi e chiamate effettive; non misura i token
embedding. Una temperatura zero non rende le risposte live deterministiche:
confrontare più ripetizioni e interpretare le variazioni prima di attribuirle al codice.
Gli ID espliciti e le istruzioni di citazione aumentano i token di input/output:
il numero massimo di chiamate rimane invariato, il costo per risposta può aumentare.

Dalla #5 la stima usa anche `AGENT_MAX_ATTEMPTS` e `AGENT_RETRY_BUDGET`: il primo
è il tetto conservativo di tentativi e dispatch per turno, il secondo è condiviso da
riformulazione retrieval, HTTP e provider. I prodotti dei massimi locali non sono
considerati spendibili: ogni retry deve rientrare nel budget globale.

## Integrazione locale #5

```bash
python3 evals/run_issue5_integration.py
```

Usa soltanto immagini già presenti: API HTTP reale, provider/Woo HTTP deterministici
e Chroma reale sulla rete interna di un progetto nuovo. Nessuna porta pubblicata,
nessun `.env` demo, collection e volumi nuovi. L'harness verifica mount, endpoint,
credenziali sintetiche, nomi e cleanup. Copre timeout, 429/Retry-After, deadline,
4xx/5xx, payload Woo/modello malformati, riuso connessione, scoping ordini e assenza
di segreti nei log. Arresta/riavvia solo Chroma del run e sostituisce il corpus con
lo stesso numero di record, verificando che vengano citati soltanto i nuovi ID.
Gli inventari includono commit base, hash dell'implementazione non committata e
fixture; report e metriche temporali rimangono gitignored. Il blocco di rete
ordinario di pytest non viene modificato.

## Metriche e confronto

| Campo | Definizione |
| --- | --- |
| `routing_accuracy` | Strada derivata dai tool eseguiti uguale a quella attesa. RAG selezionato ma vuoto resta `rag`; `none` significa nessun tool eseguito. |
| `tool_accuracy` | Uguaglianza dei set di tool attesi/eseguiti. Le ripetizioni non cambiano il set ma aumentano i contatori. |
| `hit_at_k`, `mrr` | Presenza e rango reciproco della fonte attesa nel primo retrieval reale della domanda, prima della soglia; k è nella configurazione. Mancato retrieval con fonte attesa vale zero. |
| `citation_precision` | Fonti strutturate corrette e sostenute da ID citati validi / fonti strutturate uniche restituite; riconoscimento da SKU o titolo. Zero se manca una fonte richiesta, `null` se non è richiesta e non ci sono citazioni. |
| `citation_recall` | Presenza della fonte richiesta, per impedire che omettere tutte le fonti migliori la precisione. |
| `citation_validity` | Gli ID nel testo coincidono con quelli attribuiti in `sources`, sono ammessi dai gate nel turno e corrispondono ai metadati della fonte. Coseno e BM25 sono verificati separatamente, mai confrontando RRF con la soglia coseno. Una fonte attesa richiede almeno un ID; senza fonte attesa non devono esserci citazioni. |
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
La precisione valuta `sources` e richiede citazioni esplicite valide nel testo;
`citation_validity` esegue un controllo indipendente dal validatore dell'agente.
Queste misure verificano attribuzione e provenienza, non implicazione semantica
tra ogni affermazione e il passaggio: non certificano l'assenza di allucinazioni.

Le fixture usano gli stessi ID deterministici dell'ingestion. Il modello offline
riporta i marcatori effettivi dei ToolMessage; i test di regressione rimuovono o
inventano citazioni e iniettano fonti non citate per verificare che l'eval fallisca.
Il benchmark mantiene i 30 scenari della #3; i test aggiungono deduplica, ricerche
multiple, isolamento fra turni/concorrenza, HTTP e stabilità di due ingestion finte.
Il backend si astiene dopo RAG senza citazioni valide, anche per una risposta mista.

Il report passa a **schema 2** per la nuova semantica delle citazioni; cambia anche
l'hash delle fixture. Baseline della #3/schema 1 vengono intenzionalmente rifiutate:
rigenerare una baseline con questo schema per successivi confronti automatici.
Per la migrazione confrontare separatamente i 30 casi invariati e i contatori;
non alterare gli hash per far accettare report incompatibili. Nessun contenuto
dei chunk o testo delle risposte viene aggiunto ai report. Dalla #4 la diagnostica
include gli ID opachi dei chunk, i punteggi tipizzati e gli hash delle query.

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

## Issue #4: strategie effettive e classificazione dei failure

La baseline `issue-4-before.json` è stata prodotta dalla main `fa7e52a` dopo #2/#3,
prima di modificare il codice: schema 2, golden e fixture invariati, 30×3 casi.
`issue-4-after.json --baseline ...` è confrontabile direttamente: la #4 aggiunge
campi diagnostici, ma non cambia il contratto delle metriche schema 2. `commit`
può essere passato con `--commit`; l'hash dell'implementazione identifica sempre
il contenuto eseguito. I vecchi fixture/schema incompatibili continuano a fallire.
La baseline salvata è stata arricchita solo con commit/comando di provenienza.

`FakeStore` continua a verificare il loop dell'agente; il suo 100% non misura
la qualità del retrieval. Usare il benchmark distinto `retrieval-ablation`,
schema 1 proprio (non confrontabile tramite `compare` con l'agent schema 2):

```bash
docker compose run --rm --no-deps eval-offline python -m evals.run_retrieval_eval \
  --repeats 3 --output /evals/results/issue-4-retrieval-offline.json
python3 evals/run_local_integration.py
```

Il primo comando calcola davvero distanze/BM25/RRF, senza rete. Il secondo fa
upsert/lettura/query/delete su **Chroma 1.0.0 reale**, fissato per digest, con gli
stessi 12 chunk e 16 casi (6 configurazioni × 16 × 3 = 288 esecuzioni). Il progetto
Compose, collection, rete e volume sono univoci; nessuna porta pubblicata, `.env`
escluso, credenziali sintetiche, rete interna e allowlist socket `chroma:8000`.
L'harness verifica la configurazione effettiva e registra nomi/digest/cleanup in
`evals/results/woo-issue4-<run>/inventory.json`. Non usa né ferma la demo.
Serve l'immagine backend già costruita; `pull_policy: never` separa esplicitamente
download/build ed esecuzione locale. L'harness host deve poter scrivere in
`evals/results/` (se creato da un container root, assegnare la directory al proprio UID).

I vettori locali sono bag of concepts con codici intenzionalmente ignorati,
senza tabella query→ranking. Il modello locale inoltra la query effettiva al tool
e cita i passaggi restituiti; non consulta le attese. Il caso misto usa `OrderService`
reale con Woo sintetico. Queste prove non misurano routing/generazione di un LLM.

Le configurazioni variano **una leva per volta**: semantic; hybrid (12 candidati,
RRF 60, pesi 1/1); hybrid con 4 candidati; RRF 20; peso lessicale 2; un retry.
`comparison` confronta ogni variante con semantic e con il proprio parent,
segnalando per domanda regressioni qualitative, incremento chiamate e latenza.
Non si sceglie automaticamente il default dal miglior punteggio.

Ogni tentativo riporta tutti i candidati ottenuti (non il ranking dell'intero
corpus oltre il limite), ranghi semantico/BM25/fuso, distanza coseno, score BM25/RRF,
motivo del gate, ID del contesto finale e posizione del chunk atteso.
`first_hit_at_k`/`first_mrr` misurano il **contesto ammesso al primo tentativo**;
`final_*` il contesto dopo retry. Sono volutamente distinti dalle metriche agent
v2 che misurano il primo ranking prima del gate. Assessor e gate rifiutati non
autorizzano citazioni; il report conserva anche quei tentativi.

`failure`: `corpus_miss`, `retrieval_miss`, `ranking_miss`,
`generation/citation_miss` oppure `none`; definizioni in DEC-012. Per un caso
senza fonte attesa, una risposta documentale indebita è generation/citation miss.
Il campo è una diagnosi sul golden, non una prova semantica automatica.

`second_stage_ms` comprende lettura snapshot/costruzione BM25, ranking lessicale,
fusione, gate, riformulazione e assessor locale; `retry_ms` isola la durata del
secondo tentativo (la riformulazione è nel primo). I tempi di ciascuno stadio sono
anche separati. Nel locale, embedding/modello/Woo sono adapter: chiamate provider,
token provider e costo provider zero. I contatori del modello locale non sono
richieste OpenAI. Il costo computazionale locale non è monetizzato.

## Smoke con embedding veri e budget limitato

Richiede consenso separato. Il runner `run_embedding_smoke` fissa modello
`text-embedding-3-small`, sei casi, una ripetizione, 12 documenti sintetici e al
massimo un batch con le query e le eventuali riformulazioni. Niente LLM generativo,
judge, Woo reale o Chroma. I vettori identici vengono riutilizzati tra strategie;
una cache miss fallisce senza chiamare il provider. Retry SDK zero, 30 s/richiesta,
60 s/run. Il conteggio conservativo dei byte UTF-8 limita l'input a 12.000 token
byte-BPE (8.000 per stringa); la spesa massima approvabile è $0,001.
Il batch attuale contiene al massimo 1.723 token con questo limite conservativo.

Tariffa verificata il 19/09/2026: $0,02/milione di token input
([OpenAI](https://developers.openai.com/api/docs/models/text-embedding-3-small)).
Il report distingue token misurati e costo **stimato** da tariffa, non fatturato;
le latenze delle strategie escludono il batch condiviso, misurato in `provider`.
Prima di riusare il runner in futuro verificare nuovamente la tariffa.

```bash
# Nessuna rete, nessuna chiave richiesta
docker compose run --rm --no-deps eval-offline python -m evals.run_embedding_smoke --estimate
# Solo DOPO consenso per questa specifica esecuzione; usare un nome progetto nuovo
docker compose --env-file .env -f evals/compose.smoke.yml -p woo-issue4-smoke-UNIQUE \
  run --rm --no-deps smoke python -m evals.run_embedding_smoke \
  --live --allow-external --max-cost-usd 0.001 --output /results/issue-4-embedding-smoke.json
docker compose --env-file .env -f evals/compose.smoke.yml -p woo-issue4-smoke-UNIQUE down
```

Lo smoke Compose riceve solo la chiave necessaria, senza montare `.env` nel
container; è separato dalla rete demo. Il suo comando predefinito è una stima,
non un'esecuzione live. Budget completo 30×3, ulteriori richieste o nuovi dati
richiedono nuova autorizzazione.

Per verificare una correzione senza ripagare gli embedding si possono rigiocare
**i punteggi completi registrati**, distinguendo chiaramente il livello di prova:

```bash
docker compose run --rm --no-deps eval-offline python -m evals.run_embedding_smoke \
  --replay /evals/results/issue-4-embedding-smoke.json \
  --output /evals/results/issue-4-embedding-replay.json
```

Il replay valida schema/modalità, dataset e corpus, rifiuta query prive di ranking
completo e ricalcola BM25/fusione/gate. Non aggiorna vettori, non riprova Chroma,
non effettua chiamate esterne e non sovrascrive la registrazione originale.
Risultati, regressione trovata nel retry e decisione finale in
[`docs/issue-4-results.md`](../docs/issue-4-results.md).


## Issue #6: sessioni, history e widget

```bash
python3 evals/run_issue6_integration.py
```

Il runner non legge `.env`: crea un progetto/collection/volume univoci, controlla
nomi, mount, endpoint, immagini, assenza di porte e rete `internal`, poi avvia tre
processi API (demo, production senza demo, limiti ridotti), Chroma e provider
Woo/OpenAI-compatible sintetici. Due ulteriori avvii production devono fallire con
secret vuoto/predefinito. Riavvia soltanto la propria API per verificare perdita
history e prova accesso da un altro processo allo stesso ID. Cache, TTL, rate limit,
ordini incrociati e payload modello vengono verificati via HTTP.

`widget_security.mjs` esegue il JS del widget in un DOM minimale Node contro l'API
reale sulla rete interna: contratto, login/logout, scadenza, risposta tardiva e
isolamento identità. **Non è un browser né una verifica visuale**: non prova layout,
policy cookie/CORS del browser o rendering. Richiede l'immagine locale
l’immagine Node fissata a digest nel Compose oltre alle immagini API/Chroma; nessun download automatico.

I report sotto `evals/results/woo-issue6-*/` contengono inventario, hash codice/
fixture, esiti, durata e contatori sintetici senza payload, token o email. Il numero
di token dell'adapter è convenzionale, non tokenizzazione reale né consumo a
pagamento. Cleanup verificato del solo progetto del run. Live esterno non eseguito:
nessuna autorizzazione API/spesa è implicita nel lancio di questo harness.


## Issue #7: ingestion e deployment

`python3 evals/run_issue7_integration.py` costruisce immagini univoche e verifica
API/ingest standalone (wheel installato, nessun mount del codice), WordPress con
WooCommerce 10.0.4 e Chroma reali. Dataset `issue7-synthetic-v1`, nessun ordine o
cliente reale, provider locali deterministici, rete Docker interna e nessuna porta.
Include un secondo servizio API con sorgenti montati per il caso di sviluppo.

Controlla query continue durante build/promozione/rollback, collisione fra processi,
validation, fetch/embedding HTTP falliti, scrittura parziale, cleanup protetto e
readiness all'avvio ritardato e dopo arresti mirati di WP/Chroma. Il runner audita
configurazione e ownership, non legge `.env`, non modifica volumi `woo-chatbot_*`.
Download dipendenze e Woo avvengono solo in build; esecuzione senza egress.

Report schema 1 in `results/woo-issue7-*/inventory.json` e `scenarios.json`: commit,
hash implementazione, immagini/risorse, casi, esiti, latenze e contatori del provider
sintetico. Il benchmark agente resta schema 2 e usa dataset/fixture invariati per
il confronto `issue-7-before.json`/`issue-7-after.json` con `--baseline` e 3 ripetizioni.
Non confondere i contatori sintetici con token/costi di un modello esterno.

La suite offline resta `network_mode: none` con DNS/socket bloccati da pytest;
comprende anche costruzione wheel offline e import da installazione temporanea.
Live esterno e migrazione della demo richiedono consenso separato. Dettagli:
[guida ingestion/deployment](../docs/ingestion-deployment.md).
