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
WordPress. Signer di produzione in `chatbot/app/tools/woo_client.py` (TODO).
- Base string: `METHOD & urlencode(url) & urlencode(param_sorted)`.
- Chiave di firma: `consumer_secret&` (nessun token secret).
- Verificato end-to-end con chiave **read-only** (permessi `read`): auth ok, POST → 401.

### DEC-002 — Scoping ordini lato query
La separazione tra clienti si ottiene filtrando la query REST per `customer=<id>`:
l'ordine di un altro cliente non compare nei risultati. Il customer ID sarà iniettato
dal codice (dalla sessione), mai dal modello — coerente con le regole di sicurezza.

### Nota ambiente — stabilità Docker Desktop su WSL2
Claude Code e l'integrazione Docker Desktop girano nella **stessa distro WSL `ubuntu`**:
se l'integrazione crasha, WSL riavvia la distro e cadono entrambi (container `exit 137`).
Mitigazioni: `.wslconfig` con RAM/swap espliciti, oppure Docker Engine nativo in WSL.
Il seed idempotente rende un crash a metà sempre recuperabile.
