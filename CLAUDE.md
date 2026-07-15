# woo-rag-assistant

Assistente clienti per e-commerce WooCommerce, basato su RAG + tool calling.
Project work individuale per il Master AI Engineering (Boolean). Repo pubblica, pensata anche come portfolio.

## Obiettivo

Chatbot embedded in un negozio WooCommerce che:
1. Risponde a domande sulla conoscenza statica del negozio (prodotti, FAQ, policy di spedizione e reso) tramite **RAG**, citando le fonti.
2. Risponde a domande sullo stato dinamico (stato ordini, disponibilità/stock) tramite **tool calling** verso le API REST di WooCommerce.
3. Instrada autonomamente tra RAG, tool o entrambi (caso misto: "posso ancora rendere l'ordine X?" = tool per la data di consegna + RAG per la policy di reso).

## Perimetro v1 (vincolante)

- **Solo lettura.** Nessuna azione di scrittura (no annullamenti, no modifiche indirizzo, no rimborsi). Le chiavi API WooCommerce sono generate con permessi read-only.
- **Fuori dominio → declina.** Se la domanda non riguarda il negozio, il bot declina con garbo e riporta la conversazione in tema.
- **Mai inventare.** Se il retrieval non trova nulla di pertinente: "non lo so, contatta l'assistenza". Mai allucinare policy o dati.
- Evoluzioni future (fuori v1): azioni di scrittura con human-in-the-loop.

## Regole di sicurezza NON negoziabili

1. **L'autorizzazione non la fa mai l'LLM.** È imposta nel codice, mai nel prompt.
2. **Il customer ID vive nella sessione server-side**, mai nel prompt e mai visibile al modello. Il backend valida il token di sessione e associa il customer ID alla conversazione.
3. **Tool scoped in partenza.** La firma del tool esposta al modello accetta solo il numero d'ordine; il customer ID lo inietta il codice. La query filtra sempre per entrambi.
4. **Registrazione condizionale dei tool.** Utente anonimo = i tool ordini NON vengono registrati per quella conversazione (non "vietati via prompt": proprio assenti). Il modello degrada con grazia invitando al login.
5. **Ordine altrui → "ordine non trovato"**, mai "non autorizzato" (non confermare l'esistenza dell'ordine).

## Architettura

```
Widget chat (JS) → Backend FastAPI → { ChromaDB | LLM API | WooCommerce REST }
```

Backend FastAPI, componenti interni:
- **Middleware auth**: valida la sessione, registra condizionalmente i tool.
- **Agente router**: decide RAG, tool o entrambi.
- **Catena RAG**: retrieval + generazione con citazione fonti (LangChain).
- **Tool ordini**: read-only, scoped sul cliente della sessione.

Pipeline di **ingestion** offline (script one-shot, profilo Docker `ingest`): legge prodotti/pagine da WooCommerce → chunking → embedding → ChromaDB.

## Stack

- Python 3.12, FastAPI, LangChain, Pydantic, httpx (async)
- ChromaDB come vector store
- LLM: OpenAI (`gpt-4.1-mini`) come provider primario per generazione ed embedding (`text-embedding-3-small`), architettura predisposta per multi-provider
- LlamaParse (LlamaCloud) per il parsing dei documenti in fase di ingestion
- WordPress + WooCommerce + MariaDB via Docker
- Widget frontend: JS vanilla o Vue (da decidere)
- Docker Compose per l'intero ambiente; porte: WordPress 8080, FastAPI 8000, ChromaDB 8001

## Struttura repo

```
docker-compose.yml
.env.example          # template variabili, mai valori reali
chatbot/              # backend FastAPI
  Dockerfile
  pyproject.toml
  app/
    main.py           # endpoint /chat, middleware sessione
    ingest.py         # pipeline di ingestion
    rag/              # chunking, retrieval, chain
    tools/            # tool WooCommerce scoped
    auth/             # validazione sessione, registrazione condizionale tool
widget/               # frontend chat
seed/                 # dati demo: products.csv, docs/ (policy, FAQ), setup.sh (WP-CLI)
evals/                # golden dataset e script di valutazione (RAGAS)
docs/                 # architettura e decisioni di design
```

## Dati demo e scenari di test

Il seed (script WP-CLI in `seed/setup.sh`) crea due clienti demo con ordini distinti. Scenari di demo/test obbligatori:
1. Anonimo chiede delle spedizioni → RAG, risposta ok.
2. Anonimo chiede di un ordine → declino garbato, invito al login.
3. Cliente A loggato chiede del proprio ordine → tool, risposta ok.
4. Cliente A loggato chiede dell'ordine del cliente B → "ordine non trovato".

Per la demo l'autenticazione è mockata: toggle nella UI ("Continua come ospite" / "Accedi come cliente demo") che imposta o meno un token fittizio.

## Convenzioni

- `main` sempre funzionante; feature branch `feat/...` per i blocchi grossi.
- Segreti solo in `.env` (gitignored); `.env.example` sempre aggiornato.
- WordPress core NON è versionato: lo fornisce l'immagine Docker, i dati vivono nei volumi.
- Le decisioni di design vanno documentate in `docs/architecture.md` man mano che vengono prese.
- Golden dataset in `evals/` da alimentare fin da subito (domanda, risposta attesa, fonte corretta).
- Lint: ruff. Test: pytest. CI con GitHub Actions (lint + test su PR) da aggiungere presto.

## Comandi

```bash
docker compose up -d              # avvia l'ambiente completo
docker compose run --rm ingest    # (ri)popola il vector store
docker compose exec wordpress wp ...   # WP-CLI dentro il container
```

## Nota per le chiamate interne

Dal container FastAPI, WooCommerce si raggiunge via `http://wordpress` (nome servizio Docker), NON `localhost:8080`. Attenzione ai redirect se il `siteurl` di WordPress è `localhost:8080`.
