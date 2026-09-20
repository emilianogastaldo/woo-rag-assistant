# Ingestion e deployment riproducibili

## Versioni e promozione

API e ingest devono montare **lo stesso volume POSIX locale** in
`KNOWLEDGE_STATE_DIR` (Compose: `knowledge_state:/state/knowledge`) e usare lo
stesso `CHROMA_COLLECTION`, endpoint Chroma, modello e `EMBEDDING_DIMENSIONS`.
Il protocollo è per un solo host Docker; volumi distinti, NFS e amministratori
che scrivono direttamente in Chroma non partecipano ai lock e non sono supportati.

`CHROMA_COLLECTION` identifica il namespace logico. Il registro vive nella sua
sottodirectory SHA-256. Un manifest schema 1 contiene modello, dimensione, chunking
e tutti i record ordinati per ID, inclusi testo e metadati. Il nome fisico è
`kb-<primi 16 hex SHA256 namespace>-<SHA256 manifest>`; JSON canonico UTF-8, chiavi
ordinate, separatori compatti e numeri non finiti vietati. Ordine delle fonti,
timestamp e UUID non influenzano l'identità. Non modificare i manifest a mano.
Il registro contiene copie dei documenti pubblici: proteggerlo e includerlo nel
backup come il database vettoriale, senza versionarlo in Git.

L'ingestion acquisisce un lock amministrativo non bloccante **prima del fetch**.
Due processi simultanei sullo stesso namespace non possono costruire o promuovere
in parallelo: il secondo termina con errore esplicito. I lock si rilasciano anche
se il processo muore; nessun lease temporale da forzare o file lock da cancellare.

1. Fetch completo Woo/WP, estrazione, chunking e controllo dei metadati/ID.
2. Embedding con modello e dimensione espliciti; rifiuto di vettori vuoti, non
   finiti, di dimensione errata o in numero diverso dai chunk.
3. Manifest persistito e collection candidata creata con ownership e digest.
   Scritture a batch di 100. Nessun reset, upsert o cancellazione dell'attiva.
4. Rilettura completa: conteggio, uguaglianza testo/metadati/ID, dimensioni e
   valori dei vettori. Query sull'indice con un vettore memorizzato: deve trovare
   un ID del manifest con distanza coseno circa zero. È uno smoke strutturale,
   non una misura di qualità semantica del provider.
5. Promozione: nuova verifica e sostituzione atomica di `active.json`, con `fsync`
   del file e directory. Il puntatore mantiene anche la precedente versione.

Un errore di fetch, embedding, scrittura o validation lascia invariata l'attiva.
Le candidate parziali restano in quarantena per diagnosi e cleanup esplicito.
Un retry con manifest identico riusa solo una collection interamente valida;
una collisione o scrittura incompleta produce errore, mai sovrascrittura.
Un crash dopo lo switch può lasciare il comando senza conferma: `status` è la
fonte per sapere quale versione sia attiva; ripetere la promozione è idempotente.

Ogni ricerca fissa una versione in un `ContextVar` e mantiene un lock condiviso
fino alla fine di BM25, query vettoriali e retry. Una promozione non aspetta i
lettori: quelli già partiti completano sulla vecchia versione, i nuovi leggono
la nuova. Citazioni e BM25 derivano dagli stessi record immutabili.

## Comandi operativi

Eseguire build/fetch/embedding soltanto sul corpus e provider autorizzati.
Le operazioni `status`, `promote`, `rollback`, `cleanup` non chiamano il provider AI.
`promote` e `rollback` ricontrollano i dati e interrogano Chroma.

```bash
docker compose build chatbot-api ingest
# Stato e inventario locale: nomi, ruoli, conteggio e dimensione; nessun documento.
docker compose run --rm --no-deps ingest python -m app.ingest status
# Costruisce e promuove soltanto dopo validation.
docker compose run --rm ingest
# Oppure preparazione e promozione separate.
docker compose run --rm ingest python -m app.ingest build --candidate-only
docker compose run --rm --no-deps ingest python -m app.ingest promote --target NOME_ESATTO
# Torna esclusivamente alla versione indicata come previous.
docker compose run --rm --no-deps ingest python -m app.ingest rollback --target NOME_PREVIOUS
# Rimuove una sola candidata fallita o versione obsoleta di questo namespace.
docker compose run --rm --no-deps ingest python -m app.ingest cleanup --target NOME_OBSOLETO
```

`NOME_*` sono segnaposto da sostituire con i nomi completi mostrati da `status`.
Non esistono wildcard, prune automatico o cleanup per prefisso. Il cleanup verifica
nome, manifest, ownership remota e protezione di attiva/precedente. Si rifiuta se
ci sono ricerche in corso; riprovarlo in un momento tranquillo. Mentre detiene il
lock esclusivo dei lettori, nuove ricerche/readiness possono restituire temporanea
indisponibilità: il cleanup è un'operazione di manutenzione, distinta dalla
promozione senza downtime. Non usare `delete_collection` direttamente.

La precedente resta protetta anche dopo rollback; una terza promozione rende
eliminabili le versioni più vecchie, quando nessuna ricerca le usa. Una candidata
parziale va eliminata esplicitamente prima di ricostruirla. Se la cancellazione
remota è riuscita ma il processo si è interrotto prima della rimozione del manifest,
lo stesso cleanup può completare la sola rimozione locale. Altri errori remoti,
permessi o ownership diversa sono propagati e richiedono diagnosi.

## Bootstrap e readiness

```bash
cp .env.example .env
# Compilare .env; questo comando avvia i servizi anche prima del seed.
docker compose up -d db wordpress chromadb
docker compose run --rm wpcli /seed/setup.sh
# Inserire le chiavi read-only create dal seed, poi eseguire l'ingestion autorizzata.
docker compose build chatbot-api ingest
docker compose run --rm ingest
docker compose up -d --wait chatbot-api
```

Il seed attende che WordPress sia avviato e il DB sano; non richiede WordPress
healthy prima dell'installazione. API e ingest invece dipendono da WordPress e
Chroma `service_healthy`. Non avviare l'intero stack con `--wait` prima del seed:
WordPress diventa pronto solo dopo installazione e attivazione di WooCommerce.

| Sonda | Significato |
| --- | --- |
| MariaDB healthcheck | Connessione e InnoDB inizializzato |
| WordPress healthcheck | REST type `product` raggiungibile via HTTP: PHP, DB e Woo attivi |
| Chroma healthcheck | `/api/v2/heartbeat` risponde HTTP 200 |
| API `/health` | Processo HTTP vivo, anche con dipendenze indisponibili |
| API `/ready` e Docker healthcheck | Woo pronto, collection attiva presente, digest/owner/conteggio coerenti col manifest |

Readiness ha timeout complessivo 5 s, non chiama OpenAI e non crea collection.
Restituisce 503 all'avvio senza KB o durante indisponibilità delle dipendenze;
recupera automaticamente al loro ritorno. Le condizioni Compose regolano l'avvio,
non riavviano a cascata servizi diventati unhealthy. Un modello non raggiungibile
viene gestito dai budget/retry della chat e non è certificato da `/ready`.

## Wheel, immagini e dipendenze

`chatbot/requirements.lock` blocca tutte le dipendenze dirette/transitive, incluse
quelle di sviluppo e build, dalle versioni della baseline #6. `pyproject.toml`
blocca anche i requisiti diretti e include `app` e `app.*`. Docker e CI installano
il lock, costruiscono/installano senza nuova risoluzione il wheel e verificano
`pip check`. Il container importa da `site-packages`, non da un package stub.
La build esclude `.env`, cache e report. Il runtime include i tool dev per mantenere
riproducibile il servizio offline; non è un'immagine minimizzata.

Python 3.12.14 slim è fissato a digest; WordPress, WP-CLI, MariaDB, Chroma e il
Node usato dai test storici sono fissati a digest nei Compose. Il seed nuovo usa
WooCommerce 10.0.4; l'harness ne verifica anche SHA-256 dell'archivio. Le immagini
locali API/ingest usano tag espliciti `woo-rag-api:issue7` e `woo-rag-ingest:issue7`.
Per distribuire una release in un registry registrare il digest della propria build,
senza riutilizzare il tag per codice diverso. Le evidenze locali coprono Linux amd64;
altre architetture richiedono build e verifica dedicate. Nessun `latest` Docker.

Aggiornare lock e digest con una modifica dedicata, eseguendo gli stessi controlli.
I pin impediscono aggiornamenti impliciti; non sostituiscono la manutenzione di
sicurezza. Un volume WordPress già popolato conserva plugin e contenuti esistenti:
una nuova immagine non rende automaticamente riproducibile quel volume.

## Migrazione e recovery

Prima della prima ingestion versionata, il reader usa in sola lettura la collection
legacy `CHROMA_COLLECTION`, se presente. Non viene eliminata o modificata. La
readiness legacy verifica presenza e conteggio positivo; solo le nuove versioni
hanno la garanzia del manifest. Il protocollo richiede che nessuna vecchia ingestion
che cancella la collection sia eseguita durante la transizione.

La migrazione della demo **non è stata eseguita**. Richiede un piano e un consenso
separati: identificare endpoint/collection/volumi, fare backup coerente di Chroma
e registro, stimare embedding sul corpus autorizzato, aggiornare entrambi i servizi
con lo stesso volume di stato, preparare candidata e controllare query prima della
promozione. Conservare immagini e configurazione precedenti. Il primo switch da
legacy non ha `previous` versionata: il rollback iniziale consiste nel ripristino
coordinato del registro pre-migrazione e dell'app precedente, mantenendo la
collection legacy intatta. Per le successive promozioni usare il comando rollback.

Backup e restore devono riguardare **insieme** Chroma e `knowledge_state`, sospendendo
solo gli amministratori durante lo snapshot coerente. Non ricreare un registro vuoto
accanto a collection versionate: perderebbe il puntatore e tornerebbe al fallback
legacy. Se il registro è corrotto, fermare le operazioni amministrative, conservare
una copia per diagnosi e ripristinare il backup; non inventare un puntatore tramite
ordinamento dei nomi. Un manifest non autorizza cancellazione di una collection con
ownership diversa.

Limiti: fetch, embedding e validation completa stanno in memoria, adatti al catalogo
demo; non sono una pipeline streaming per corpus molto grandi. Un cambio di modello,
dimensione o provider embedding va coordinato con la configurazione dei reader;
il controllo modello/dimensione rifiuta versioni incompatibili. Il digest non può
rilevare un provider che cambia internamente i pesi dietro lo stesso nome modello:
versionare i modelli anche sul provider quando disponibile.

## Verifica senza dati reali

```bash
docker compose run --rm --no-deps eval-offline ruff check . /evals --config /app/pyproject.toml
docker compose run --rm --no-deps eval-offline pytest -q
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --repeats 3 --baseline /evals/results/issue-7-before.json \
  --output /evals/results/issue-7-after.json
python3 evals/run_issue7_integration.py
```

Il runner locale costruisce API e ingest con tag univoci, WordPress/Woo e adapter
locali. Poi avvia un progetto casuale: rete `internal`, nessuna porta pubblicata,
nessun `.env`, volumi nuovi, credenziali sintetiche. Audita mount, endpoint, immagini
e ownership prima dei test e del cleanup. API e ingest standalone non montano codice;
un servizio distinto verifica anche il sorgente montato. Download e build precedono
l'esecuzione interna; non autorizzano chiamate a provider AI esterni.

Le prove comprendono import di tutti i sottopacchetti del wheel, fetch Woo reale,
fallimenti fetch/embedding HTTP locali, scrittura parziale, validation, query
concorrenti A→B→A, collisione fra processi, cleanup protetto, idempotenza, startup
ritardato e arresto/ripartenza dei soli WordPress/Chroma di test. I report privi di
payload sono gitignored in `evals/results/woo-issue7-*/`; le immagini restano per
ispezione. Un fallimento non autorizza a toccare lo stack `woo-chatbot`.

Live esterno e reindicizzazione demo: **NON ESEGUITI**, consenso assente. Un eventuale
smoke con embedding reali serve a verificare il contratto/dimensione e il comportamento
semantico effettivo del provider: corpus sintetico, 4–6 query, una ripetizione,
nessun judge, collection separata. Prima di eseguirlo occorre concordare modelli,
dati, numero massimo di richieste/retry, limiti di tempo/token e costo aggiornato;
l'harness locale non costituisce autorizzazione né runner con budget per il live.
