# Architettura e decisioni di design

> Documento vivo: le decisioni vanno annotate qui man mano che vengono prese.

## Panoramica

```
Widget chat (JS) → Backend FastAPI → { ChromaDB | LLM API | WooCommerce REST }
```

## Componenti backend

- **Sessione** (`app/auth/session.py`) — verifica il token firmato, risolve il
  customer ID su WooCommerce e lo tiene server-side.
- **Agente router** (`app/agent.py`) — costruisce il toolset in base alla sessione e
  lascia al modello la scelta fra RAG, tool o entrambi.
- **Catena RAG** (`app/rag/chain.py`) — retrieval con soglia di pertinenza e fonti
  ricostruite dai metadati dei chunk.
- **Tool ordini** (`app/tools/orders.py`) — sola lettura, scoped sul cliente.
- **Tool catalogo** (`app/tools/catalog.py`) — disponibilità e prezzo in tempo reale.

## Pipeline di ingestion (offline)

Script one-shot (`docker compose run --rm ingest`): legge prodotti/pagine da
WooCommerce → chunking → embedding → ChromaDB.

- **Fonti**: prodotti via WC REST (OAuth, `WooClient`), pagine via WP REST
  (`/wp/v2/pages`, pubbliche). Solo conoscenza *statica* (descrizioni, policy, FAQ);
  stock e ordini restano ai tool.
- **Pagine incluse**: whitelist di slug (`spedizioni`, `resi-e-rimborsi`,
  `domande-frequenti`) per escludere le pagine di sistema WooCommerce (cart, checkout,
  shop, my-account) e la Sample Page.
- **Estrazione**: HTML→testo con BeautifulSoup. **LlamaParse** è predisposto ma
  riservato ai documenti veri (es. policy in PDF), non usato su HTML semplice.
- **Chunking**: `RecursiveCharacterTextSplitter` (800/120) con metadati
  `source`/`title`/`type` per la citazione delle fonti.
- **Idempotenza**: la collection `woo_knowledge` viene azzerata e riscritta a ogni run.
- Store condiviso con la catena RAG in `app/rag/store.py`.

## Ambiente di seed

- **WP-CLI** non è incluso nell'immagine `wordpress:php8.3-apache`: è fornito da un
  servizio companion `wpcli` (immagine `wordpress:cli-php8.3`, profilo `cli`) che
  condivide il volume `wp_data` e monta `./seed`.
- **Seed riproducibile e idempotente**: `seed/setup.sh` fa da bootstrap (install
  WP/Woo, permalink, opzioni store) ed esegue `seed/seed.php` via `wp eval-file`.
  I dati sorgente sono in `seed/products.csv` e `seed/docs/*.md`.
  - Idempotenza: prodotti per SKU, pagine per slug, clienti per email, ordini con
    gate su option `wrag_seed_orders_done`, API key per description.
- Esecuzione: `docker compose run --rm wpcli /seed/setup.sh`.

## Decisioni

### DEC-001 — Autenticazione REST verso WooCommerce: OAuth 1.0a nel client
WooCommerce accetta la Basic Auth solo su HTTPS; su HTTP puro (sia `localhost:8080`
sia `http://wordpress` interno alla rete Docker) richiede **OAuth 1.0a one-legged**
([WC docs](https://developer.woocommerce.com/docs/apis/rest-api/)).
Scelta: il backend firma le richieste con OAuth 1.0a (HMAC-SHA256), senza modificare
WordPress. Signer in `chatbot/app/tools/woo_client.py` (`WooClient`).
- Base string: `METHOD & urlencode(url) & urlencode(param_sorted)`.
- Chiave di firma: `consumer_secret&` (nessun token secret).
- Verificato end-to-end con chiave **read-only** (permessi `read`): auth ok, POST → 401.

**Quirk `home_url` (importante).** WooCommerce ricostruisce la base string della firma
dal proprio `home_url` (`http://localhost:8080`), **non** dall'host a cui il client si
connette. In Docker il backend si connette a `http://wordpress` ma deve firmare con
l'URL pubblico. Per questo `WooClient` distingue:
- `WC_BASE_URL` → host di **connessione** (`http://wordpress/wp-json/wc/v3`)
- `WC_SIGN_URL` → URL **pubblico** per la firma (`http://localhost:8080/wp-json/wc/v3`)

Se `WC_SIGN_URL` è vuoto, coincide con `WC_BASE_URL` (caso host/HTTPS in produzione).

### DEC-002 — Scoping ordini lato query
La separazione tra clienti si ottiene filtrando la query REST per `customer=<id>`:
l'ordine di un altro cliente non compare nei risultati. Il customer ID sarà iniettato
dal codice (dalla sessione), mai dal modello — coerente con le regole di sicurezza.

### Nota ambiente — stabilità Docker Desktop su WSL2
Claude Code e l'integrazione Docker Desktop girano nella **stessa distro WSL `ubuntu`**:
se l'integrazione crasha, WSL riavvia la distro e cadono entrambi (container `exit 137`).
Mitigazioni: `.wslconfig` con RAM/swap espliciti, oppure Docker Engine nativo in WSL.
Il seed idempotente rende un crash a metà sempre recuperabile.

### DEC-003 — Routing come tool calling, non come classificatore
Il routing RAG/tool/misto non è una catena di `if` né un classificatore a monte: i
tool sono esposti al modello (`ChatOpenAI.bind_tools`) e la scelta è sua, dentro un
loop con tetto a `AGENT_MAX_STEPS` giri.

Motivo: il caso misto («posso ancora restituire l'ordine 21?») richiede due tool nella
stessa risposta e un ordine di invocazione che dipende dal contenuto. Un classificatore
a etichetta singola lo spezzerebbe; il tool calling lo gestisce senza codice dedicato.

Conseguenze accettate:
- il numero di chiamate al modello per risposta non è fisso (da qui il tetto);
- una chiamata a un tool inesistente è possibile e va gestita: il loop risponde
  "strumento non disponibile" invece di sollevare, e il modello si corregge.

**Le fonti non le produce l'LLM.** Sono raccolte dai metadati dei chunk restituiti dal
retrieval e restituite a parte nella risposta HTTP: una citazione inventata è
strutturalmente impossibile, non solo scoraggiata dal prompt. Tool e fonti viaggiano
insieme in un `Toolset`, così chi costruisce i tool non può perdere le citazioni.

### DEC-004 — Autorizzazione: toolset condizionale e doppio filtro
Tre livelli, tutti nel codice:

1. **Registrazione condizionale.** `build_toolset(session)` aggiunge `stato_ordine` e
   `elenco_ordini` solo con una sessione valida. Per l'anonimo quei tool non esistono:
   non è una regola di prompt aggirabile con una riformulazione.
2. **Firma scoped.** Lo schema esposto al modello contiene solo `numero_ordine`. Il
   customer ID è chiuso nel costruttore di `OrderService` e non compare nel prompt
   (verificato da test).
3. **Doppio filtro sul risultato.** La query REST filtra per `customer=<id>` *e* il
   codice ricontrolla `customer_id` e `id` di ogni ordine restituito. Se il filtro
   remoto cambiasse comportamento, il controllo locale regge comunque.

Esito uniforme: ordine di altri, ordine inesistente e numero non valido producono lo
stesso messaggio "ordine non trovato". Non si distingue fra "non esiste" e "non è tuo",
altrimenti la differenza fra le due risposte diventerebbe un oracolo di esistenza.

**Token della demo.** L'autenticazione è mockata (`POST /demo/login` emette un token
per un cliente del seed), ma il token è firmato HMAC-SHA256 con `SESSION_SECRET` e
verificato con `hmac.compare_digest`: modificare l'identità nel payload invalida la
firma. Cambia da dove arriva l'identità, non come viene verificata — così sostituire il
mock con un login vero non tocca il resto della catena.

### DEC-005 — Distanza coseno e soglia di pertinenza
La collection Chroma è creata con `hnsw:space = cosine` invece della L2 di default: il
punteggio resta in `[0, 2]` ed è interpretabile (0 = identico), quindi
`RETRIEVAL_MAX_DISTANCE` è confrontabile tra collection con chunking diverso.

I chunk oltre la soglia vengono scartati **prima** di arrivare al modello: se non ne
resta nessuno il tool restituisce un contesto vuoto con l'istruzione esplicita di
dichiarare di non sapere. Il "non lo so" è quindi una proprietà del retrieval, non una
buona intenzione del prompt.

Il default (`0.6`) è un punto di partenza: va calibrato con `evals/run_eval.py`, che
stampa le distanze top-1 dei casi in-dominio e di quelli fuori dominio e indica se
esiste una soglia che separa i due gruppi. Lo script usa lo stesso store condiviso
dell'ingestion, così misura la metrica che poi gira in produzione.

### DEC-006 — Widget in JS vanilla
Il widget è un singolo file senza build step, incorporabile con un tag
`<script src="/widget/chat.js" data-api="...">`. Con Vue servirebbero bundler e step di
build per una UI che è una lista di messaggi e una form; il costo non si giustifica, e
l'assenza di toolchain rende l'inserimento in un tema WordPress banale.

Il token di sessione vive solo in memoria (non in `localStorage`) e viaggia
nell'header `Authorization`. In sviluppo il backend serve il widget su `/widget/` come
static mount, con CORS limitato alle origini in `CORS_ORIGINS`.

### DEC-007 — Stock fuori dal RAG
Le quantità a magazzino non vengono indicizzate: nel vector store sarebbero corrette
solo fino alla vendita successiva. La disponibilità passa dal tool catalogo, che legge
le API al momento della domanda. Nel RAG finisce solo la conoscenza che cambia di rado
(descrizioni, policy, FAQ).
