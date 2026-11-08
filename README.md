# woo-rag-assistant

Assistente clienti per e-commerce WooCommerce, basato su **RAG** e **tool calling**.
Project work individuale per il Master AI Engineering (Boolean).

Consegna del codice su GitHub entro la mezzanotte del **18/12**; presentazione
facoltativa il **19/12**. [Indicazioni Boolean e checklist di consegna](docs/consegna.md).

Per preparare la presentazione facoltativa: [traccia del progetto](docs/presentazione.md),
con scaletta, demo, risultati verificati e prossimi miglioramenti.

Il chatbot si incorpora in un negozio WooCommerce e:

1. risponde sulla conoscenza statica del negozio (prodotti, FAQ, policy di spedizione
   e reso) tramite RAG, **citando le fonti**;
2. risponde sullo stato dinamico (stato ordini, disponibilità) tramite tool calling
   verso le API REST di WooCommerce;
3. instrada da solo tra RAG, tool o entrambi — per esempio «posso ancora restituire
   l'ordine 21?» richiede il tool (data di consegna) *e* il RAG (policy di reso).

Per provare il progetto da un clone: [avvio guidato per docenti e assistenti AI](#avvio).

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
| Tool catalogo | `chatbot/app/tools/catalog.py` | elenco prodotti, disponibilità e prezzo in tempo reale |
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

Il Compose usa **WordPress 7.1.4 e PHP 8.5.12**, con immagini bloccate per digest,
e il seed installa **WooCommerce 11.2.2**. Anche WP-CLI usa PHP 8.5.12.
[Verifica aggiornamento WooCommerce e studio MCP](docs/woocommerce-mcp.md).
Per una demo preesistente, cambiare immagine non aggiorna automaticamente il core
WordPress nel volume: consultare la [nota di aggiornamento](docs/wordpress-7.1.4.md).

### Prerequisiti

- Git, Docker Engine/Docker Desktop **avviato** e Docker Compose v2 o successivo
  (`docker compose version`). Su Windows eseguire i comandi in **WSL2/Bash**;
  su Linux/macOS usare un terminale Bash compatibile.
- Connessione Internet per scaricare immagini Docker, dipendenze e WooCommerce.
- Una propria chiave API OpenAI con credito disponibile e accesso ai modelli
  configurati. Ingestion e chat fanno chiamate fatturate dal provider.
  Senza chiave è possibile eseguire i [test offline](#sviluppo), ma non provare
  le risposte del chatbot reale. La chiave LlamaCloud non serve per questa demo.
- Porte 8080, 8000 e 8001 libere. La procedura è per un **nuovo ambiente locale**:
  non eseguirla sul database di un negozio reale o su una demo da conservare.

Il Compose distribuito pubblica le porte sulle interfacce dell'host: usarlo su
una macchina/rete fidata, senza esposizione Internet. Le password di WordPress,
MariaDB e dei clienti sono pubbliche perché i dati sono sintetici. Il file di
override privato dell'autore non è necessario e non è incluso nel repository.

### 1. Clonare e configurare

```bash
git clone https://github.com/emilianogastaldo/woo-rag-assistant.git
cd woo-rag-assistant
cp .env.example .env
```

Se `.env` esiste già, modificarlo senza sovrascriverlo. Aprirlo in un editor e
configurare questi valori **prima di avviare i container**:

| Variabile | Valore per questa demo |
| --- | --- |
| `OPENAI_API_KEY` | La propria chiave API, solo nel file locale `.env`. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1`; impostarlo esplicitamente, senza lasciarlo vuoto. |
| `OPENAI_MODEL` | Lasciare `gpt-4.1-mini`. |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | Lasciare `text-embedding-3-small` / `1536`. |
| `SESSION_SECRET` | Un segreto casuale di almeno 32 caratteri. |
| `WRAG_BRIDGE_SECRET` | Un secondo segreto casuale, diverso dal primo, di almeno 32 caratteri; abilita la chat in WordPress. |
| `APP_ENV` / `DEMO_ENABLED` | Lasciare `development` / `false`: il negozio usa il login WordPress reale. |
| `WC_CONSUMER_KEY` / `WC_CONSUMER_SECRET` | Lasciare vuoti fino al passo 2. |

Per generare ciascun segreto, se Python 3 è disponibile, eseguire due volte
`python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` e copiare i risultati
nei rispettivi campi. Non condividere `.env`, i segreti o l'output con le chiavi
in commit, issue, report o conversazioni con un LLM.

### 2. Creare il negozio e caricare il seed

```bash
docker compose up -d db wordpress chromadb
docker compose run --rm wpcli /seed/setup.sh
```

WordPress può risultare `unhealthy` **prima del seed**: il controllo attende anche
WooCommerce. Per questo il primo comando non usa `--wait`.

Il seed installa WordPress/WooCommerce e crea sei prodotti, tre pagine informative,
due clienti e tre ordini. Annotare gli ID degli ordini stampati, che possono variare.
Alla prima esecuzione stampa anche `__WC_KEYS__ <ck> <cs>`: copiare i due valori in
`.env` come `WC_CONSUMER_KEY` e `WC_CONSUMER_SECRET` **prima di proseguire**. Le chiavi
hanno permessi di sola lettura. Una riesecuzione non ristampa il segreto esistente:
se perso, generare una nuova chiave read-only dal pannello WooCommerce e aggiornare
`.env`, senza cancellare il database.

### 3. Indicizzare e avviare il chatbot

Questo passaggio invia al provider i testi sintetici di prodotti e policy per gli
embedding. Le successive domande in chat usano il modello configurato. Chi esegue
la procedura deve essere autorizzato a usare la chiave e sostenere questi costi.

```bash
docker compose build chatbot-api ingest
docker compose run --rm ingest
docker compose up -d --wait chatbot-api
```

Proseguire all'ultimo comando soltanto se l'ingestion termina senza errori. Il corpus
standard comprende sei prodotti e tre pagine; la homepage non viene indicizzata.

### 4. Verificare e provare

```bash
docker compose ps
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/ready
```

Gli endpoint devono restituire rispettivamente `{"status":"ok"}` e
`{"status":"ready"}`. Il primo prova che il backend risponde; il secondo verifica
WooCommerce e l'indice, senza chiamare OpenAI. Per verificare anche il provider,
aprire il negozio e chiedere «Quanto costa la spedizione standard?»: attendersi una
risposta con fonte consultabile, non un messaggio di indisponibilità.

- **Demo principale:** <http://localhost:8080>, con pulsante chat nel negozio.
- **Account cliente:** pulsante Account, `mario.rossi` / `demo_secret_a` oppure
  `luigi.verdi` / `demo_secret_b`. Provare gli ordini usando gli ID del proprio seed.
- **Amministrazione:** <http://localhost:8080/wp-admin/>, `admin` / `admin_secret`.
- **API:** <http://localhost:8000/docs>.
- **Widget autonomo opzionale:** <http://localhost:8000/widget/>; il login mock
  richiede il toggle descritto nella sezione [Demo](#demo), non necessario in WordPress.

### Arresto, ripresa e problemi comuni

`docker compose stop` ferma la demo conservando i dati; `docker compose start`
riavvia i container già creati. Non occorre ripetere seed e ingestion a ogni avvio.
Dopo modifiche alla configurazione del backend usare `docker compose up -d chatbot-api`;
se cambia il segreto del ponte, ricreare anche WordPress con
`docker compose up -d wordpress chatbot-api`.
**Non usare `docker compose down -v` per un normale arresto:** elimina i volumi.

| Sintomo | Controllo / azione |
| --- | --- |
| Docker non raggiungibile | Avviare Docker Desktop/Engine e verificare `docker info`. |
| Porta già occupata | Fermare il servizio in conflitto. Cambiare solo la porta di WordPress non basta: URL del sito e firma OAuth devono restare coerenti. |
| Widget assente nel negozio | Configurare `WRAG_BRIDGE_SECRET`, ricreare WordPress e backend, ricaricare la pagina. |
| Errore WooCommerce 401 durante ingestion | Controllare le due chiavi read-only e `WC_SIGN_URL=http://localhost:8080/wp-json/wc/v3`. |
| URL provider senza protocollo | Impostare `OPENAI_BASE_URL=https://api.openai.com/v1`, quindi rieseguire il servizio interessato. |
| OpenAI 401 / 429 con `insufficient_quota` o `credit_balance_exhausted` | Correggere la chiave o il credito del relativo progetto OpenAI; non insistere con retry. Poi ripetere l'ingestion se non era riuscita. |
| `/health` risponde ma `/ready` restituisce 503 | Verificare seed, chiavi Woo e successo dell'ingestion. Consultare `docker compose logs --tail=80 chatbot-api` senza pubblicare credenziali. |

### Istruzioni da dare a un assistente AI

Un assistente con accesso al terminale può seguire questo incarico; un LLM senza
strumenti può soltanto spiegare i passaggi:

> Leggi il README di woo-rag-assistant e segui la sezione Avvio in un ambiente
> locale nuovo. Verifica prima Docker, porte e presenza di un'installazione
> precedente: non sovrascrivere `.env` o volumi esistenti. Chiedimi di inserire
> la mia chiave nel file locale senza incollarla in chat. Configura due segreti
> distinti, esegui il seed e trasferisci le chiavi Woo in `.env` senza mostrarle.
> Prima delle chiamate al provider verifica che ne abbia autorizzato l'uso.
> Controlla `/health`, `/ready` e gli scenari della sezione Demo con gli ID
> effettivi del seed. Non avviare benchmark live estesi e non cancellare volumi.
> Riporta cosa è stato verificato e gli eventuali blocchi, senza segreti.

Il setup applica anche **Trama**, child theme del tema WordPress Twenty Twenty-Five:
homepage, navigazione, policy formattate e sei immagini locali con categorie.
Tema e asset sono montati dal Compose, senza page builder o script incollati.
Lo stesso comando di setup può essere ripetuto: mantiene ID, media, pagine e menu;
come il seed originale, aggiorna prezzi, descrizioni e stock dei sei SKU demo.
Conserva le categorie aggiunte dal negoziante e non riapplica impostazioni del tema
già inizializzate. Provenienza e CC0 dei soli asset: [catalogo](seed/assets/README.md).

Su un negozio già popolato, il solo allestimento del tema si applica con:

```bash
docker compose run --rm wpcli wp eval-file /seed/storefront.php
```

Il comando conserva la configurazione già inizializzata e non aggiorna i prodotti.

Per la chat dentro WordPress impostare in `.env` **`WRAG_BRIDGE_SECRET`** casuale
di almeno 32 caratteri, distinto da `SESSION_SECRET`, quindi:

```bash
docker compose up -d --force-recreate wordpress chatbot-api
```

Il ponte usa `http://chatbot-api:8000` nella rete Docker e carica il widget nel
footer. Il pulsante Account usa il login WordPress nativo: `mario.rossi` /
`demo_secret_a`, oppure `luigi.verdi` / `demo_secret_b`. Sono credenziali pubbliche
per dati sintetici locali; [configurazione e limiti del ponte](docs/issue-18-results.md).
Il login del negozio funziona con `DEMO_ENABLED=false`; il toggle descritto sotto
appartiene invece alla pagina autonoma `/widget/`.

## Demo

La demo del **widget autonomo** richiede `DEMO_ENABLED=true` in ambiente `development` (default: disabilitata).
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
| 0 | ospite | «Che prodotti ci sono?» | elenco WooCommerce con prezzi e disponibilità attuali |
| 1 | ospite | «Quanto costa la spedizione standard?» | RAG con fonti |
| 2 | ospite | «A che punto è il mio ordine 22?» | declino, invito ad accedere |
| 3 | Mario | «A che punto è il mio ordine 22?» | tool ordini |
| 4 | Mario | ordine di Luigi | «ordine non trovato» |
| 5 | Mario | «Posso ancora restituire l'ordine 21?» | tool + RAG; scadenza dai 30 giorni dalla consegna verificata |
| 6 | qualsiasi | «Che tempo farà domani?» | fuori dominio, declina |

Per preparare il **18/12/2026** (consegna del codice) la prova di reso per la
presentazione del **19/12**, dopo il setup ordinario aggiungere una sola fixture:

```bash
docker compose run --rm wpcli wp eval-file /seed/demo-returns.php 2026-12-18
```

Usare l'ID stampato: consegna verificata **19/11/2026**, termine **19/12/2026**;
il 18 è entro termine, il 19 è l'ultimo giorno, il 20 è fuori termine. Confrontare
con l'ordine storico consegnato il 22/06 (termine 22/07) e quello senza tracking
(astensione). La preparazione conserva gli storici; ripeterla con la stessa data
non cambia ordini o date. Il backend usa il clock reale: una domanda datata
esplicitamente prima della presentazione resta una simulazione.
Per una prova valida in un'altra data usare un **nuovo ambiente isolato** e passare
quella data; il comando rifiuta di spostare una fixture già preparata.
ID d'esempio e domande: [scenari reso](docs/issue-24-results.md).

La verifica finale ripetibile da un clone, con volumi propri e provider sintetici,
è `python3 evals/run_issue19_import.py --demo-final`; prerequisiti, comandi di build,
risultati e schermate sono nel [report finale](docs/issue-25-results.md).
Anteprime Trama: [homepage desktop](docs/screenshots/trama-home-desktop.png),
[mobile](docs/screenshots/trama-home-mobile.png),
[catalogo](docs/screenshots/trama-catalog-desktop.png) e
[chat mobile](docs/screenshots/trama-chat-mobile.png) con risposta simulata.

`cerca_prodotti` filtra il catalogo live per testo, categoria (nome/slug verificato),
prezzo, stock e pagina. La disponibilità predefinita è `instock`; gli altri stati
richiedono un filtro esplicito. La valuta ISO si configura con `WC_CURRENCY`
(default `EUR`), che deve corrispondere alla valuta del negozio. I prezzi REST non
includono una valuta per prodotto.

Ogni ricerca legge una pagina di massimo 10 prodotti e, per ciascun prodotto
variabile, una pagina di massimo 10 varianti. Riporta solo varianti pubblicate che
rispettano budget e disponibilità: il prezzo del padre non prova il prezzo di una
variante acquistabile. `may_have_more` segnala una pagina potenzialmente parziale;
non viene effettuata una scansione completa. Il filtro categoria verifica un nome
o slug esatto nei primi 20 risultati della ricerca categorie; in caso ambiguo o
assente chiede di precisarlo. Prodotti privati o nascosti sono esclusi anche se il
server ignora i filtri. Per le caratteristiche si usa la KB, per prezzo e stock
i risultati live.

`POST /chat` aggiunge `products` (default `[]`) ai campi già esistenti. Le schede
provengono esclusivamente dall'ultima ricerca prodotti verificata del turno;
testo e cronologia del modello non possono crearle. Una nuova ricerca vuota o
fallita azzera le schede di quel turno. Il widget usa testo DOM e link/immagini
HTTP(S) verificati, senza interpretare HTML del modello o del catalogo.

I tre casi sintetici in `evals/catalog-gifts.jsonl` verificano il meccanismo di
consiglio entro budget, astensione e chiarimento con `ScriptedLLM` e Woo finti:
`pytest -q tests/test_product_cards.py`. Non misurano la capacità di un modello
reale di scegliere prodotti pertinenti; quella prova resta separata in #17.

L’elenco generale usa `elenco_prodotti`, senza ricerca vettoriale: legge fino a
10 prodotti pubblicati e segnala se il catalogo continua. Le risposte basate solo
su questi dati non hanno citazioni documentali (`sources: []`). Per descrizioni
e caratteristiche si usa il RAG, per un nome/SKU specifico il tool disponibilità.

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
WordPress/WooCommerce è disponibile tramite il ponte opzionale della
[issue #18](docs/issue-18-results.md): verifica cookie e nonce a ogni turno,
con un segreto separato e token backend mai esposti al browser. Prima di usarlo
in produzione configurare HTTPS/rete privata, cache delle pagine e rate limit.
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
| `/chat`: 20 richieste / 60 s per visitatore attestato o peer diretto, massimo 10000 chiavi | Finestra fissa; anche richieste invalide consumano quota; 429 con `Retry-After` in secondi |
| `/chat`: 200 richieste / 60 s complessive (`RATE_LIMIT_GLOBAL_REQUESTS`) | Tetto separato, condiviso tra bridge e accessi diretti; include richieste rifiutate |

Le unità del budget sono una stima superiore conservativa per i tokenizer byte-pair
OpenAI, non token fatturati misurati. Le chiamate embedding sono limitate da input,
numero di tool/tentativi e deadline; il budget `MODEL_TOKEN_BUDGET` riguarda la
generazione. Per provider/tokenizer diversi verificare la stima prima del deploy.
Tutti i valori sono configurabili in `.env.example` e passati dal Compose.

Le conversazioni sono salvate in **SQLite** dopo ogni turno completato. Un
riavvio/reload del backend conserva history, owner, scadenza assoluta e contatore
dei turni. Compose monta il volume `conversation_state`; nell'avvio Python locale
`CONVERSATION_DB_PATH` indica il file (default `state/conversations.sqlite3`).
La ripresa richiede lo stesso token/cookie valido e il `conversation_id`: il widget
li conserva in memoria, quindi ricaricare la pagina avvia una nuova chat.

Avviare un solo worker: un lock POSIX sul database impedisce a due processi di
usare contemporaneamente lo stesso store. Cache e rate limiter restano in memoria
e si azzerano al riavvio. Le conversazioni scadute vengono eliminate all'avvio e
alla successiva acquisizione; un turno interrotto non viene salvato. SQLite contiene
solo messaggi utente e risposte finali già redatti, più il digest dell'owner; il
file non è cifrato. Proteggere volume e backup come dati di conversazione. Il file
e il lock sono creati con permessi `0600`; un errore di salvataggio restituisce 503.

Il rate limit diretto usa il peer di rete, non header forniti dal client. Il Compose avvia
Uvicorn con `--no-proxy-headers`: dietro proxy, tutti i client condividono la quota
del proxy; configurare limiti al proxy per IP reali verificati. Nessuna espulsione
di chiavi rate attive a capienza esaurita: nuove chiavi ricevono 429.

Il bridge WordPress attesta invece una quota per account autenticato o IP ospite,
così gli utenti non condividono la sola quota del server WP. L'attestazione resta
server-side e non autentica clienti; il tetto globale continua a valere. Le porte
della demo sono pubblicate solo su `127.0.0.1`.
[Configurazione e verifica di rete, proxy e quote](docs/bridge-deployment.md).

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

## Collegamento con Modulo 3 · Lezione 12

Il laboratorio viene applicato ai dati del negozio: ingestion Woo/WordPress e
Chroma per i documenti, tool REST scoped per i dati aggiornati, citazioni verificate
e valutazione con risposte attese in `evals/golden.jsonl`. Le API WooCommerce
coprono il ruolo delle tabelle SQL del laboratorio mantenendo l'autorizzazione
per cliente. La persistenza SQLite completa l'obiettivo della chat riprendibile
dopo il riavvio del backend, usando il loop agente già presente.

`chatbot/tests/test_conversation_persistence.py` verifica offline il follow-up
dopo riavvio per ospiti e clienti, l'isolamento fra sessioni, TTL, turni, capienza,
concorrenza e rollback dopo un errore di scrittura. Per routing, fonti e risposte
si riusa il runner di valutazione descritto sotto, con ripetizioni e baseline.

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
`--live --allow-external --max-estimated-usd <budget>` e usa solo dati sintetici; anche il precedente
sweep di retrieval è ora protetto da opt-in. Comandi, costi, definizioni delle
metriche e limiti sono in [`evals/README.md`](evals/README.md).

Il [report #17](docs/issue-17-results.md) documenta i casi contestuali aggiuntivi,
preflight e costi da usage; le prove con provider reale restano da autorizzare.
Per caricare prodotti di prova, vedere il [confronto seed/CSV ufficiale #19](docs/issue-19-results.md).

## Stack

Python 3.12 · FastAPI · LangChain · ChromaDB · OpenAI (`gpt-4.1-mini`,
`text-embedding-3-small`) · WordPress + WooCommerce + MariaDB · Docker Compose
