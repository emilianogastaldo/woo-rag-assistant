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
