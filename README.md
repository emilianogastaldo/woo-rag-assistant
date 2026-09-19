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
citazioni, correttezza/astensione, latenza e chiamate, senza salvare conversazioni
o segreti. `--baseline` evidenzia le regressioni per domanda. Il live richiede
**entrambi** `--live --allow-external` e usa solo dati sintetici; anche il precedente
sweep di retrieval è ora protetto da opt-in. Comandi, costi, definizioni delle
metriche e limiti sono in [`evals/README.md`](evals/README.md).

## Stack

Python 3.12 · FastAPI · LangChain · ChromaDB · OpenAI (`gpt-4.1-mini`,
`text-embedding-3-small`) · WordPress + WooCommerce + MariaDB · Docker Compose
