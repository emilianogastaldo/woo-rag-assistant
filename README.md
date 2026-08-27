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
docker compose up -d                      # ambiente completo
docker compose run --rm wpcli /seed/setup.sh   # installa WP/Woo e i dati demo
docker compose run --rm ingest            # popola il vector store
```

Il seed stampa le chiavi API read-only alla prima esecuzione (`__WC_KEYS__ <ck> <cs>`):
vanno copiate in `.env` come `WC_CONSUMER_KEY` / `WC_CONSUMER_SECRET`.

- Negozio WordPress: <http://localhost:8080>
- API del chatbot: <http://localhost:8000/docs>
- Pagina di demo del widget: <http://localhost:8000/widget/>

## Demo

L'autenticazione della demo è mockata: il widget offre «Continua come ospite» oppure
l'accesso come cliente demo. `POST /demo/login` emette un token firmato HMAC per uno
dei clienti creati dal seed — cambia la *provenienza* dell'identità, non il modo in
cui viene verificata.

Scenari da provare (elencati anche nella pagina di demo). I numeri d'ordine sono
quelli stampati da `seed/setup.sh`: se nel tuo ambiente differiscono, sostituiscili.

| # | Sessione | Domanda | Atteso |
| --- | --- | --- | --- |
| 1 | ospite | «Quanto costa la spedizione standard?» | RAG con fonti |
| 2 | ospite | «A che punto è il mio ordine 22?» | declino, invito ad accedere |
| 3 | Mario | «A che punto è il mio ordine 22?» | tool ordini |
| 4 | Mario | ordine di Luigi | «ordine non trovato» |
| 5 | Mario | «Posso ancora restituire l'ordine 21?» | tool + RAG |
| 6 | qualsiasi | «Che tempo farà domani?» | fuori dominio, declina |

## Sviluppo

```bash
docker compose run --rm --no-deps chatbot-api ruff check .
docker compose run --rm --no-deps chatbot-api pytest -q
```

I test non toccano la rete: WooCommerce, ChromaDB e il modello sono sostituiti da
doppi di test. La CI (GitHub Actions) esegue lint e test su ogni PR.

## Valutazione

`evals/golden.jsonl` contiene il golden dataset (domanda, risposta attesa, fonte
attesa) diviso per tipo: `page`, `product`, `mixed`, `order`, `out_of_domain`.

```bash
docker compose run --rm -v "$PWD/evals:/evals" ingest python /evals/run_eval.py
```

Lo script fa uno sweep su più `chunk_size` misurando hit@k e MRR, e confronta le
distanze in-dominio e fuori-dominio per calibrare la soglia di pertinenza
(`RETRIEVAL_MAX_DISTANCE`, vedi DEC-005).

## Stack

Python 3.12 · FastAPI · LangChain · ChromaDB · OpenAI (`gpt-4.1-mini`,
`text-embedding-3-small`) · WordPress + WooCommerce + MariaDB · Docker Compose
