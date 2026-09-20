# woo-rag-assistant

Assistente clienti per e-commerce WooCommerce, basato su **RAG** e **tool calling**.
Project work individuale per il Master AI Engineering (Boolean).

Il chatbot si incorpora in un negozio WooCommerce e:

1. risponde sulla conoscenza statica del negozio (prodotti, FAQ, policy di spedizione
   e reso) tramite RAG, **citando le fonti**;
2. risponde sullo stato dinamico (stato ordini, disponibilità) tramite tool calling
   verso le API REST di WooCommerce;
3. instrada da solo tra RAG, tool o entrambi — per esempio «posso ancora restituire
   l'ordine 21?» richiede il tool (data di consegna) *e* il RAG (policy di reso).

## Architettura

```
Widget chat (JS) → Backend FastAPI → { ChromaDB | OpenAI | WooCommerce REST }
```

| Componente | File | Ruolo |
| --- | --- | --- |
| Endpoint chat | `chatbot/app/main.py` | sessione dall'header, orchestrazione, risposta |
| Agente router | `chatbot/app/agent.py` | toolset condizionale e loop di tool calling |
| Catena RAG | `chatbot/app/rag/chain.py` | retrieval con soglia e fonti citabili |
| Tool ordini | `chatbot/app/tools/orders.py` | sola lettura, scoped sul cliente |
| Tool catalogo | `chatbot/app/tools/catalog.py` | disponibilità e prezzo in tempo reale |
| Sessione | `chatbot/app/auth/session.py` | verifica token, risoluzione customer ID |
| Ingestion | `chatbot/app/ingest.py` | WooCommerce/WP → chunking → embedding → Chroma |
| Widget | `widget/chat.js` | UI chat incorporabile con un solo tag |

Le decisioni di design sono in [`docs/architecture.md`](docs/architecture.md).

## Hybrid retrieval e diagnostica

`RETRIEVAL_STRATEGY=hybrid` abilita BM25 + ricerca semantica con Reciprocal Rank
Fusion. BM25 legge i chunk correnti da Chroma, usando testo, titolo e SKU, e
conserva gli stessi ID della pipeline di ingestion. Non richiede un secondo
indice persistente né la reindicizzazione della demo per attivarlo su record #2.

Il default resta **`semantic`**, `k=4`, soglia coseno `0.6`, senza retry: i test
locali misurano la correttezza dei meccanismi, non la qualità degli embedding in
produzione. Nessun MMR/reranker è attivato senza evidenze. Parametri di candidati,
RRF, BM25 e gate lessicale sono espliciti in `.env.example` e passati dal Compose
al backend. `RETRIEVAL_RETRY_ATTEMPTS=1` consente al massimo una riformulazione
locale dopo retrieval senza evidenza; il default è `0`.

Gli eval distinguono corpus miss, retrieval miss, ranking miss e generation/citation
miss, con chunk atteso, candidati, ranghi/punteggi per canale, contesto ammesso,
primo tentativo e retry separati. Il punteggio RRF **non è una distanza** e non
viene confrontato con la soglia coseno. La copertura lessicale è un'euristica:
un passaggio recuperato o citato non prova da solo che contenga la risposta.

```bash
# Benchmark delle strategie con vettori locali, senza rete/provider
docker compose run --rm --no-deps eval-offline python -m evals.run_retrieval_eval
# Chroma reale isolato, adattatori locali, rete interna e cleanup del solo test
python3 evals/run_local_integration.py
```

Risultati, limiti e smoke opzionale con embedding veri:
[`evals/README.md`](evals/README.md) e [`report issue #4`](docs/issue-4-results.md).

## Citazioni verificabili

Ogni chunk riceve un ID `chunk-v1-<sha256>` deterministico da URL, titolo, tipo,
posizione nel documento e testo. Il tool RAG restituisce `[chunk-id] testo`;
l'agente deve citare gli ID dei passaggi usati. Il backend valida le citazioni
contro i soli chunk recuperati **nella richiesta corrente**, anche con più ricerche.
Una fonte recuperata ma non citata non compare in `sources`.

`POST /chat` restituisce `conversation_id`, `reply`, `sources`, `authenticated` e `tools_used`.
Ogni fonte contiene `title`, `url`, `type` e `chunk_ids`: solo gli ID effettivamente
citati, deduplicati; la fonte compare una sola volta per URL e tipo. Il widget
converte le citazioni valide in riferimenti numerati `[1]`, collegati alla fonte.
Lo schema completo è disponibile in `/docs` e `/openapi.json`.

Gli ID sconosciuti vengono rimossi dal testo. Se è stato usato il RAG ma manca
qualsiasi citazione valida, il backend restituisce un'astensione e `sources: []`,
anche nel caso misto RAG+dati. Nessuna chiamata aggiuntiva di riparazione. Risposte solo dati,
saluti e fuori dominio senza RAG hanno fonti vuote. La verifica attesta la
provenienza del passaggio, **non** la correttezza semantica di ogni affermazione.
Documenti e dati WooCommerce restano dati non fidati, mai istruzioni.

**Migrazione:** gli indici precedenti senza ID vengono scartati dal retrieval.
Dopo l'aggiornamento occorre ricostruire l'immagine ingest e reindicizzare con
`docker compose build ingest` e `docker compose run --rm ingest`, solo dopo
autorizzazione alle chiamate WooCommerce/WordPress, OpenAI e ChromaDB.
Il chunking mantiene i default 800/120, configurati in `app/config.py`
(`CHUNK_SIZE` e `CHUNK_OVERLAP` nell'ambiente del processo ingest).

## Perimetro v1

**Sola lettura**: nessun annullamento, nessuna modifica, nessun rimborso. Le chiavi
API WooCommerce hanno permessi `read`. Fuori dominio il bot declina; se il retrieval
non trova nulla dichiara di non saperlo invece di inventare.

## Sicurezza

Quattro invarianti, imposte nel codice e non nel prompt:

1. **L'autorizzazione non la fa l'LLM.** Sta nella query e nel toolset.
2. **Il customer ID vive server-side.** Non transita nel payload della richiesta e
   non compare mai nel prompt né nella firma dei tool.
3. **Tool scoped in partenza.** `stato_ordine` accetta solo il numero d'ordine; il
   cliente lo inietta il codice, e la query REST filtra sempre per `customer`.
4. **Registrazione condizionale.** Per un utente anonimo i tool ordini non vengono
   registrati: non sono vietati, sono assenti. Il modello degrada invitando ad accedere.

L'ordine di un altro cliente produce «ordine non trovato», mai «non autorizzato»:
non si conferma nemmeno che quell'ordine esista.

## Avvio

```bash
cp .env.example .env                      # e valorizza le variabili
docker compose up -d db wordpress chromadb # bootstrap servizi, prima del seed
docker compose run --rm wpcli /seed/setup.sh   # installa WP/Woo e i dati demo
docker compose build chatbot-api ingest
docker compose run --rm ingest            # solo dopo autorizzazione al provider/corpus
docker compose up -d --wait chatbot-api    # attende WordPress/Woo, Chroma e KB pronta
```

Il seed stampa le chiavi API read-only alla prima esecuzione (`__WC_KEYS__ <ck> <cs>`):
vanno copiate in `.env` come `WC_CONSUMER_KEY` / `WC_CONSUMER_SECRET`.

- Negozio WordPress: <http://localhost:8080>
- API del chatbot: <http://localhost:8000/docs>
- Pagina di demo del widget: <http://localhost:8000/widget/>

## Demo

La demo richiede `DEMO_ENABLED=true` in ambiente `development` (default: disabilitata).
L'autenticazione della demo è mockata: il widget offre «Continua come ospite» oppure
l'accesso come cliente demo. `POST /demo/login` emette un token firmato HMAC per uno
dei clienti creati dal seed — cambia la *provenienza* dell'identità, non il modo in
cui viene verificata.

Scenari da provare (elencati anche nella pagina di demo). I numeri d'ordine sono
quelli stampati da `seed/setup.sh`: se nel tuo ambiente differiscono, sostituiscili.

Per il caso di reso il tool calcola la scadenza di 30 giorni solo dalla **data di
consegna verificata** presente nel tracking (`_wrag_delivery_date`). La data di
completamento WooCommerce è mostrata separatamente e non prova la consegna; se il
tracking non fornisce la data, il bot non determina la scadenza e invita a contattare
l'assistenza.

| # | Sessione | Domanda | Atteso |
| --- | --- | --- | --- |
| 1 | ospite | «Quanto costa la spedizione standard?» | RAG con fonti |
| 2 | ospite | «A che punto è il mio ordine 22?» | declino, invito ad accedere |
| 3 | Mario | «A che punto è il mio ordine 22?» | tool ordini |
| 4 | Mario | ordine di Luigi | «ordine non trovato» |
| 5 | Mario | «Posso ancora restituire l'ordine 21?» | tool + RAG; scadenza dai 30 giorni dalla consegna verificata |
| 6 | qualsiasi | «Che tempo farà domani?» | fuori dominio, declina |

## Ingestion e deploy versionati

L'ingestion costruisce una collection candidata con manifest deterministico,
verifica record e vettori, poi cambia atomicamente il puntatore attivo. Fetch,
embedding o scritture falliti preservano la versione precedente; ciascuna ricerca
usa una sola versione per BM25, vettori e citazioni. API e ingest condividono il
volume `knowledge_state` sullo stesso host Docker.

`python -m app.ingest status` mostra attiva, precedente e candidate;
`promote`, `rollback` e `cleanup` richiedono il nome esatto con `--target`.
Cleanup protegge attiva, precedente e ricerche in corso. `/health` indica liveness;
`/ready` verifica Woo e KB senza chiamate al provider. WordPress diventa healthy
solo dopo il seed: al primo avvio seguire l'ordine dei comandi sopra.

Dipendenze Python bloccate in `chatbot/requirements.lock`, immagini terze a digest,
wheel completo installato nella build. L'harness `python3 evals/run_issue7_integration.py`
verifica immagini standalone, servizi reali isolati e guasti con provider sintetici.

Comandi, vincoli POSIX, backup, recovery e migrazione della demo:
[guida operativa](docs/ingestion-deployment.md) e
[risultati verificati](docs/issue-7-results.md).
La demo esistente non viene reindicizzata automaticamente.

## Sviluppo

```bash
docker compose run --rm --no-deps eval-offline ruff check . /evals --config /app/pyproject.toml
docker compose run --rm --no-deps eval-offline pytest -q
```

Il profilo `eval-offline` usa l'immagine del backend già costruita, senza rete,
credenziali o servizi dipendenti. Al primo utilizzo costruiscila con
`docker compose build chatbot-api` (richiede il download delle dipendenze).
Pytest blocca anche DNS e socket: WooCommerce, ChromaDB e il modello sono sostituiti
da doppi di test. La CI esegue lint, test ed eval offline su ogni PR.

### Timeout, retry ed errori

L'API usa un budget per richiesta condiviso da modello, retrieval e WooCommerce:
`AGENT_MAX_ATTEMPTS` limita tutti i tentativi esterni, i dispatch tool e le
riformulazioni, mentre `AGENT_RETRY_BUDGET` limita
i tentativi aggiuntivi. La riformulazione RAG abilitata da
`RETRIEVAL_RETRY_ATTEMPTS=1` consuma lo stesso budget dei retry provider e HTTP;
non esistono cicli di retry annidati con budget indipendenti. `AGENT_MAX_STEPS`,
`AGENT_MAX_REPEATED_ERRORS` e `REQUEST_DEADLINE_SECONDS` forniscono gli altri tetti.

Sono ritentate al massimo `PROVIDER_RETRY_ATTEMPTS`/`WC_RETRY_ATTEMPTS` volte e
solo operazioni di lettura: timeout, connessione, 429 (rispettando `Retry-After`) e
5xx. I 4xx ordinari non sono ritentati. I retry impliciti dell'SDK OpenAI sono
disabilitati. Nessun risultato RAG produce l'astensione documentale; Chroma o
provider indisponibili producono invece il fallback temporaneo stabile.
La generazione ha inoltre un limite predefinito di 512 token per chiamata e un
budget conservativo di token per turno (vedi sotto). Non è un tetto monetario; il provider può fatturare richieste
ricevute anche quando il client scade o annulla l'attesa.

FastAPI mantiene e chiude nei propri hook di lifecycle i client HTTP asincroni
condivisi. I log operativi JSON contengono request/conversation ID, tool, durata,
tentativo ed esito, senza argomenti dei tool, URL, prompt, token o eccezioni grezze.
Gli ID di correlazione sono generati dal server; `X-Request-ID` e
`X-Conversation-ID` del client vengono ignorati per impedire inserimento di dati
sensibili nei log. `X-Request-ID` torna nella risposta. Access log Uvicorn disabilitato
per non registrare query string; configurare allo stesso modo eventuali proxy.

### Sessioni e nuovo contratto chat

Inviare `POST /chat` con `{"message":"...","conversation_id":null}` per iniziare;
nei turni successivi usare il `conversation_id` della risposta. Il server rifiuta
`history`, ruoli e qualsiasi altro campo extra con 422 senza riflettere il payload.
Il widget conserva solo il token e l'ID in memoria; login/logout azzerano anche il
contenuto visibile e scartano le risposte pendenti della sessione precedente.

Per clienti autenticati serve `Authorization: Bearer ...`. Ogni emissione del token
ha un nonce distinto: una nuova sessione, anche dello stesso cliente, non può
riprendere conversazioni precedenti. L'owner comprende anche il customer ID risolto.
Per ospiti il server emette un cookie firmato `wrag_guest`, HttpOnly, SameSite=Lax
(Secure in production); usare `credentials: "include"` e un'origine CORS esplicita.
Il widget e l'API devono essere sullo stesso **site**; per domini diversi usare un
reverse proxy sul dominio del negozio. Il solo conversation ID non autorizza accesso.

`APP_ENV=production` rifiuta segreti vuoti, predefiniti o inferiori a 32 caratteri e
rifiuta `DEMO_ENABLED=true`. Generare un segreto casuale; `.env.example` è solo un
template di sviluppo. `/demo/login` è assente anche da OpenAPI quando disabilitato;
`/session/config` consente al widget di nascondere i pulsanti demo. Il login reale
Woo/SSO resta un'integrazione da fornire prima di esporre ordini in produzione.
Il token demo è restituito solo dall'endpoint di login, senza campo email;
nessuna credenziale viene inclusa nelle risposte chat.

| Limite (default) | Comportamento |
| --- | --- |
| Sessione: 8 ore | Token invalido/scaduto: 401; mai degradazione silenziosa a ospite |
| Conversazione: 30 minuti dalla creazione, 1000 voci | Scaduta/ignota/altrui: stesso 404; store pieno: 503 |
| 20 turni, una richiesta attiva per conversazione | Limite o concorrenza: 409; iniziare una nuova conversazione |
| Messaggio: 4000 byte UTF-8; body: 24000 byte | 422 / 413 prima del modello |
| History: 16000 byte UTF-8 | Rimozione delle coppie user/assistant più vecchie; TTL non si rinnova |
| Output tool: 12000 byte; contesto modello: 32000 byte | Tool troncato prima della delimitazione JSON; contesto eccedente: fallback |
| Budget modello: 100000 unità conservative per turno | Prenota byte UTF-8 serializzati + overhead/schema + massimo output prima di ogni chiamata/retry; nessun rimborso |
| Output modello: 512 token per chiamata | Limite inviato al provider, incluso nella prenotazione |
| Cache email→ID: TTL fisso 300 s, capienza 1000 | Scadenza e rimozione LRU; nessun customer ID entra nel contesto |
| `/chat`: 20 richieste / 60 s per IP, massimo 10000 chiavi | Finestra fissa; anche richieste invalide consumano quota; 429 con `Retry-After` in secondi |

Le unità del budget sono una stima superiore conservativa per i tokenizer byte-pair
OpenAI, non token fatturati misurati. Le chiamate embedding sono limitate da input,
numero di tool/tentativi e deadline; il budget `MODEL_TOKEN_BUDGET` riguarda la
generazione. Per provider/tokenizer diversi verificare la stima prima del deploy.
Tutti i valori sono configurabili in `.env.example` e passati dal Compose.

Store, cache e rate limiter sono **in memoria per processo**. Avviare un solo worker:
riavvio/reload perde history, cache e quote; più worker hanno store separati e
moltiplicano le quote. L'interfaccia `ConversationStore` è sostituibile per un futuro
store condiviso; nessuna infrastruttura esterna viene introdotta. Le voci scadute
sono eliminate alla successiva operazione, entro la capienza globale.

Il rate limit usa il peer di rete, non header forniti dal client. Il Compose avvia
Uvicorn con `--no-proxy-headers`: dietro proxy, tutti i client condividono la quota
del proxy; configurare limiti al proxy per IP reali verificati. Nessuna espulsione
di chiavi rate attive a capienza esaurita: nuove chiavi ricevono 429.

Output tool/documenti/campi Woo rimangono `ToolMessage` nel campo JSON
`untrusted_data`, separati dalle istruzioni di sistema. Il codice filtra gli ordini
prima di formattare i pochi campi ammessi e oscura email, credenziali note e identità
della sessione in input, history, output tool e risposta. Questo riduce i dati
trasmessi; non è un sistema DLP capace di riconoscere ogni segreto arbitrario o
codificato dentro documenti. Indicizzare soltanto conoscenza pubblica del negozio.
Il modello non decide mai l'autorizzazione.

Verifiche riproducibili e limiti: [report issue #6](docs/issue-6-results.md).
```bash
python3 evals/run_issue6_integration.py
```
L'harness usa API reali, Chroma dedicato, provider sintetici e test DOM del widget
con HTTP reale, senza porte pubblicate né accesso esterno. Nessuna modifica a `.env`
o alla demo condivisa.

## Valutazione

`evals/golden.jsonl` contiene 30 domande con risposta, fonte, strada e tool attesi:
RAG, dati, RAG+dati, nessuna fonte e casi avversari. Il runner attraversa il loop
reale dell'agente, il retrieval con soglia e i servizi ordini/catalogo.

```bash
docker compose run --rm --no-deps eval-offline
# Stima del live: nessuna rete, nessuna API chiamata
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval --estimate --repeats 3
```

I report JSON in `evals/results/` misurano routing, hit@k/MRR, precisione delle
citazioni, validità degli ID, correttezza/astensione, latenza e chiamate, senza salvare
conversazioni o segreti. `--baseline` evidenzia le regressioni per domanda. Il live richiede
**entrambi** `--live --allow-external` e usa solo dati sintetici; anche il precedente
sweep di retrieval è ora protetto da opt-in. Comandi, costi, definizioni delle
metriche e limiti sono in [`evals/README.md`](evals/README.md).

## Stack

Python 3.12 · FastAPI · LangChain · ChromaDB · OpenAI (`gpt-4.1-mini`,
`text-embedding-3-small`) · WordPress + WooCommerce + MariaDB · Docker Compose
