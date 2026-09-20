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
- **Chunking**: `RecursiveCharacterTextSplitter` (800/120, configurato in
  `app/config.py`) con metadati `source`/`title`/`type`, `start_index` e `chunk_id`.
  Gli ID deterministici sono anche gli ID dei record Chroma (vedi DEC-010).
- **Versioni immutabili**: candidata con manifest deterministico, validation completa
  e switch atomico del puntatore; la collection attiva non viene azzerata (DEC-016).
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

**I metadati delle fonti non li produce l'LLM.** Il retrieval registra i chunk
candidati; soltanto gli ID citati nella risposta finale e validati contro quel
registro generano fonti HTTP. La sola presenza nel retrieval non dimostra uso nella
risposta. Tool e registro appartengono al `Toolset`, con isolamento per esecuzione
(DEC-010).

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

### DEC-008 — La consegna è un dato di tracking esplicito
WooCommerce espone `date_completed`, che indica il completamento amministrativo
dell'ordine ma non certifica che il corriere abbia consegnato il pacco. Il tool ordini
la restituisce quindi con l'etichetta **Data completamento** e non la usa mai per
calcolare un reso.

La fonte scelta per la demo è il metadata ordine `_wrag_delivery_date`, popolato
dall'integrazione di tracking soltanto alla conferma del corriere e salvato in ISO 8601.
Il tool accetta esclusivamente quel metadata valido come **Data consegna verificata**.
Se manca o non è leggibile, riporta esplicitamente che la scadenza del reso non è
calcolabile con certezza; non stima la data dal completamento o dallo stato `completed`.
Quando la data è disponibile, il tool calcola la scadenza aggiungendo 30 giorni a
quella data, in linea con la policy di reso.

Il seed assegna questo metadata all'ordine demo completato di Mario e applica una
piccola migrazione idempotente (`wrag_seed_delivery_date_v1`) per gli ambienti seed
creati prima dell'introduzione della convenzione.

### DEC-009 — Evaluation del loop con fixture e live separati

`evals/run_agent_eval.py` valuta `answer()` direttamente: include prompt, toolset
condizionale, loop, retrieval con soglia, servizi ordini/catalogo e raccolta fonti.
HTTP, emissione token, WordPress e Chroma remoto restano fuori da questo benchmark;
l'autenticazione HTTP continua a essere verificata dai test dell'API.

Il golden dichiara strada (`rag`, `data`, `mixed`, `none`), set di tool, fonte,
esito e regole testuali positive/negative. Le fixture sono indipendenti dalle
aspettative: il fake LLM segue piani espliciti e legge i ToolMessage effettivi;
non copia la risposta attesa dal golden. I servizi reali ricevono dati Woo
sintetici, incluso un ordine altrui restituito intenzionalmente dal fake server
per verificare il filtro locale. La data del prompt è fissata al 19/09/2026.

Offline, rete bloccata nel runner, in pytest e nel profilo Docker `eval-offline`.
Il risultato verifica regressioni del codice e delle metriche, **non** la capacità
di routing di un modello reale. I contatori sono raccolti tramite `AgentTrace`,
opzionale e server-side: non modifica il payload HTTP e non memorizza contenuti.

Il live richiede consenso esplicito prima della costruzione dei client. Usa OpenAI
per generazione ed embedding di un corpus sintetico versionato, ricerca esatta
coseno in memoria e gli stessi servizi su dati Woo simulati. Non legge clienti
reali né cambia collection. Permette di confrontare prompt/modello/soglia a parità
di dati; per misurare ingestion, chunking e Chroma reali rimane lo sweep
`evals/run_eval.py`, anch'esso live opt-in e con un perimetro dati distinto.

Report: schema versionato, hash di dataset/fixture/implementazione, configurazione
numerica, ID domanda, metriche e contatori; nessun prompt, risposta, argomento tool,
URL, email, customer ID, credenziale o eccezione grezza. Baseline incompatibili
vengono rifiutate prima delle chiamate live. Correttezza testuale e precisione delle
fonti sono indicatori parziali di groundedness: non dimostrano l'assenza di ogni
affermazione inventata e non sostituiscono la revisione delle risposte live.

### DEC-010 — Citazioni esplicite con identità deterministica del chunk

`app/rag/chunks.py` è condiviso da ingestion e fixture/sweep eval. L'ID è
`chunk-v1-` seguito da SHA-256 completo, esadecimale minuscolo, della lista JSON
`["v1", source, title, type, start_index, page_content]`, serializzata con
`ensure_ascii=False`, separatori `,`/`:` e codifica UTF-8. Non usa UUID, hash Python,
ordine globale dei documenti, timestamp o credenziali. A parità di documento e
chunking, ingestion ripetute producono gli stessi ID anche riordinando le fonti.
Testo, metadati o offset diversi producono ID diversi; cambiare chunking può quindi
cambiare gli ID. Duplicati identici vengono deduplicati prima di scrivere nello store.

Il retrieval applica la soglia e ricontrolla hash, offset e metadati obbligatori:
record legacy, incompleti o incoerenti non entrano nel contesto. Per ogni chunk
valido produce `[chunk-id] testo` e conserva la mappa ID → `Source`. I contenuti
documentali e i dati WooCommerce sono esplicitamente trattati nel prompt come
dati non fidati; eventuali ID nel loro testo non registrano altre fonti.

Ogni `answer()` crea un registro vuoto tramite `ContextVar` del toolset, lo aggiorna
con le sole ricerche di quell'esecuzione e lo ripristina in `finally`, anche in caso
di errore. Questo isola turni sequenziali e concorrenti con toolset riutilizzato.
La cronologia, il messaggio utente e i risultati dei tool dati non popolano il
registro. Un ID usato in passato è nuovamente valido solo se recuperato in questo
turno. Nessuna nuova autorizzazione viene affidata al modello: scoping e toolset
ordini rimangono quelli di DEC-004.

`app/rag/citations.py` estrae i marcatori `[chunk-…]` dal solo testo finale,
rimuove quelli non presenti nel registro e raggruppa i validi per URL e tipo.
Ordine delle fonti e degli ID: prima citazione nel testo. Ogni fonte HTTP contiene
`title`, `url`, `type`, `chunk_ids` (solo ID citati, senza ripetizioni). Più ricerche
e più chunk dello stesso documento non moltiplicano le fonti. Il widget usa questa
mappa per riferimenti numerati, usa gli ID originali per le fonti; la history autorevole è server-side e rende
testo/etichette con nodi DOM; sono cliccabili solo URL HTTP(S).

**Policy senza citazioni:** dopo qualsiasi chiamata RAG, se nessuna citazione è
valida, il testo generato è sostituito da `UNCITED_REPLY` e le fonti sono vuote.
Questo copre anche retrieval vuoto/legacy e risposte miste senza citazioni: si
rinuncia conservativamente anche alla parte dati, evitando di separare frasi con
euristiche fragili. Il limite dei passi produce `FALLBACK_REPLY` senza fonti.
Non si aggiungono chiamate di riparazione al modello. Senza RAG, risposte dati e
declini mantengono il testo con eventuali marcatori non validi rimossi, senza fonti.

**Limite:** la validazione prova esistenza, provenienza e citazione del chunk nella
richiesta; non dimostra che il passaggio sostenga semanticamente la frase, né che
ogni frase documentale abbia una citazione. Un ID valido non certifica la verità
del documento e non è una difesa generale contro prompt injection.

**Migrazione:** ricostruire l'immagine ingest e reindicizzare la collection dopo
il deploy; fino ad allora i vecchi record non sono citabili. È un'operazione live
separata, con embedding e reset della collection, da autorizzare esplicitamente.
Nessuna ingestion live è necessaria ai test: lo store viene simulato.

### DEC-011 — Hybrid sperimentale, gate indipendenti dai punteggi RRF

`KnowledgeBase` accetta una `RetrievalConfig` immutabile, validata anche al caricamento
delle variabili d'ambiente. Strategie `semantic` e `hybrid`; `k`, candidati per
canale, costante/pesi RRF, parametri BM25, soglia coseno, score/copertura lessicale
e limite retry sono configurabili. Candidati >= k, pesi positivi, valori finiti,
retry 0/1. Il percorso semantic mantiene k e soglia precedenti.

Nel percorso hybrid, un `get(documents, metadatas)` legge il contenuto corrente
della collection. I record devono avere ID Chroma uguale al `chunk_id` verificato
dalla #2. `BM25Index` è costruito in memoria su questi soli record. SKU e titolo
sono campi lessicali aggiuntivi, senza alterare testo o identità dei chunk.
Non ci sono sidecar da sincronizzare, cache a TTL o snapshot persistenti: ogni
ricerca rilegge Chroma, anche dopo sostituzioni con lo stesso numero di record.
Il costo è O(corpus) per ricerca: adatto al corpus della demo; per corpus grandi
servirà un indice versionato e pubblicato atomicamente, misurandone il costo.
L'ingestion corrente non è transazionale: una ricerca durante reset/upsert può
vedere un corpus parziale. Il deploy deve ancora coordinare le reindicizzazioni.

Tokenizzazione Unicode NFKC/casefold con stopword italiane; codici composti e
decimali rimangono interi (`ZX-104` diverso da `ZX-140`, `4,90` diverso da `49`).
Niente stemming o spezzatura dei codici. BM25 usa IDF positivo
`log(1 + (N-df+0.5)/(df+0.5))`, saturazione k1 e normalizzazione lunghezza b.
I pareggi lessicali/fusi sono risolti per ID, le duplicazioni per ID sono eliminate
prima di assegnare ranghi. RRF somma `peso / (costante + rango)` con rango da 1;
il valore assoluto dei punteggi dei due canali non è confrontato.
Riferimenti: [BM25](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf),
[RRF](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf).

Dopo la fusione il gate ammette distanza coseno <= soglia **oppure** score BM25 >=
soglia e copertura dei termini significativi >= minimo (default sperimentale 1.0).
I codici espliciti nella query devono essere presenti esattamente nel chunk o nei
suoi campi lessicali: un prodotto semanticamente simile non giustifica un codice
sconosciuto. RRF non entra mai in questo gate. Si prendono i primi k candidati
ammissibili; `cosine_distance`, `bm25_score`, `rrf_score`, ranghi e motivo del gate
restano distinti nella traccia. I chunk semantici non presenti nello snapshot
verificato non entrano nella fusione.

Il retry, opt-in e al massimo uno per chiamata RAG, parte se nessun passaggio supera
il gate. La riformulazione è locale: stopword e poche equivalenze (`restituire` →
`reso`), mantenendo codici, numeri e negazioni. Una query invariata/vuota non viene
ripetuta. Un `passage_assessor` locale iniettabile può segnalare che passaggi non
vuoti non rispondono: il segnale svuota il contesto prima dell'eventuale retry.
Non è installato un giudice semantico di default; il gate non rileva ogni domanda
senza risposta. Il secondo tentativo richiede inoltre copertura lessicale dei
termini riformulati >= `lexical_min_coverage`, anche se supera il gate coseno:
una domanda compressa non può riaprire l'astensione solo perché cambia distanza.
Questa salvaguardia nasce dalla regressione `absent-policy` misurata nello smoke
con embedding reali e corretta con replay offline dei medesimi punteggi.
Non ci sono chiamate di generazione per riscrivere. La riformulazione è distinta
dal retry tecnico: la prima reagisce a evidenza insufficiente, il secondo soltanto
a failure transitori. Entrambi consumano però il budget condiviso descritto in
DEC-013; i retry impliciti del provider sono disabilitati.

Solo il contesto finale ammesso viene registrato per le citazioni; passaggi
scartati dall'assessor non diventano citabili. Il registro per esecuzione, le
regole di astensione senza citazioni e l'isolamento dei tool della #2 restano attivi.

### DEC-012 — Tre prove separate e default conservativo

La suite schema v2/FakeStore resta una regressione dell'orchestrazione. Un nuovo
benchmark applica davvero semantic/BM25/RRF allo stesso corpus di 12 chunk e a 16
domande sintetiche, con vettori locali calcolati dal testo. Ogni leva è confrontata
con semantic e con la configurazione parent; ranghi iniziali e risultati dopo retry
sono separati. I vettori locali ignorano intenzionalmente i codici: servono a
esercitare il recupero lessicale, non a stimare le prestazioni di OpenAI.

L'harness di integrazione usa Chroma reale in un progetto Compose univoco, volume
nuovo, nessuna porta pubblicata, rete `internal` e socket Python limitati a
`chroma:8000`. Non carica `.env`, controlla configurazione effettiva, collisioni,
nomi, mount e immagini; registra inventario e pulisce/verifica soltanto le risorse
della propria esecuzione. Il blocco di rete della suite pytest ordinaria rimane.

Uno smoke separato può richiedere **un solo batch** di embedding reali per sei
casi, dopo consenso, riusando i vettori identici fra strategie. Corpus/query sono
sintetici; generazione e Woo restano locali; nessun accesso a collection/store.
Timeout, input e spesa stimata sono limitati prima della chiamata, retry SDK zero;
un input mancante nella cache non può generare un'altra chiamata. Tariffa e token
effettivi sono riportati separando stima economica e costo fatturato non misurato.

La classificazione degli errori usa conoscenza del golden/corpus, non il modello:
fonte assente → corpus miss; fonte non candidata o rifiutata dal gate/assessor →
retrieval miss; candidata ammissibile fuori dal contesto top-k → ranking miss;
fonte presente nel contesto ma risposta/citazione errata → generation/citation miss.
Questa diagnostica è server-side/eval, non un nuovo campo pubblico HTTP.
Default semantic senza retry: manca ancora un benchmark semantico autorizzato e
ripetuto che giustifichi il cambio. Nessun MMR/reranker viene aggiunto per intuizione.

### DEC-013 — Failure tipizzati e budget unico dei tentativi

Ogni richiesta crea un `AttemptBudget` con deadline, massimo tentativi esterni e
massimo retry. Chiamate modello, query retrieval e richieste GET Woo consumano il
medesimo oggetto tramite `ContextVar`. Anche il secondo tentativo di retrieval della
#4 è un retry ai fini del budget: se lo consuma, non aumenta il numero di retry
disponibili a HTTP/provider. I limiti locali definiscono quali operazioni possono
chiedere un retry, mentre il budget globale è sempre il tetto effettivo.
Anche ogni dispatch tool (compresi nomi sconosciuti e argomenti invalidi) consuma
una unità: il massimo è conservativo, non un conteggio esclusivo di richieste HTTP.
Una riformulazione consuma una unità e un retry; ogni sua successiva chiamata fisica
consuma un'altra unità. Timeout e cancellazione sono applicati all'intero turno.

Il percorso chat usa `KnowledgeReader`, adapter REST Chroma v2 asincrono in sola
lettura. Embedding, risoluzione collection e query/get hanno tentativi separati:
un errore Chroma non riesegue l'embedding già ottenuto. La collection è risolta a
ogni lettura, senza crearla, e un guasto svuota il registro citazioni del turno.
L'ingestion conserva il client SDK sincrono; i timeout del percorso chat non
lasciano thread di rete in esecuzione. L'adapter assume tenant/database Chroma
predefiniti e metrica coseno configurata dall'ingestion del progetto.

Solo letture possono essere ritentate. OpenAI ha retry SDK zero; il codice gestisce
timeout/connessione, rate limit e 5xx entro `PROVIDER_RETRY_ATTEMPTS`. Il client Woo
ritenta GET per timeout/connessione, 429 e 5xx entro `WC_RETRY_ATTEMPTS`, rigenerando
nonce/firma OAuth e rispettando `Retry-After` senza superare la deadline. 4xx,
validazione e failure permanenti non vengono ripetuti. `AGENT_MAX_STEPS` ferma i
giri modello/tool e due failure uguali dello stesso tool fermano anticipatamente il
loop; entrambi restituiscono un fallback fisso.

La tassonomia separa validazione, timeout, 4xx, 5xx, rate limit, risposta malformata,
Chroma indisponibile, provider indisponibile, tool ignoto e budget esaurito. I failure
recuperabili dei tool diventano `ToolMessage` redatti, così il modello può spiegare
il disservizio. Nessun risultato conserva `NESSUN_RISULTATO_PERTINENTE`; un guasto
Chroma imposta invece il fallback temporaneo e non pubblica fonti precedenti.
Errori non classificati continuano a emergere: il loop non usa `except Exception`.

FastAPI possiede un `WooClient` e un `httpx.AsyncClient` provider per lifecycle e li
chiude allo shutdown. Request e conversation ID vivono in `ContextVar`. Ogni evento
esterno/tool registra JSON con ID, nome operazione/tool, durata, tentativo, esito e
classe di failure tramite allowlist; argomenti, query, URL, credenziali, prompt ed
eccezioni non entrano nel log. Il payload HTTP limita messaggi e storia prima di
raggiungere provider e tool.

L'integrazione della #5 usa API e server Woo/OpenAI-compatible reali sulla rete
interna di un progetto Compose univoco, più Chroma reale fissato per digest. Inietta
timeout, 429, 4xx, 5xx e JSON malformato, misura il limite temporale, verifica riuso
del client e arresta/riavvia soltanto il Chroma dedicato. Collection, volume,
credenziali e nomi sono sintetici; nessuna porta è pubblicata e il cleanup rimuove
soltanto il progetto creato dal run.

### DEC-014 — History autorevole e identità della conversazione (#6)

Il browser invia soltanto `message` e `conversation_id`; Pydantic rifiuta campi
extra, inclusi history e ruoli. L'ID è casuale (32 byte, base64url), creato dal
server e verificato insieme all'owner. Un ID ignoto, scaduto o appartenente ad
altra sessione restituisce lo stesso 404. L'owner autenticato è un digest del
token firmato completo e del customer ID risolto: nuove emissioni e cambi nella
mappatura email→ID non ereditano la history. Il token include un nonce casuale.
L'owner anonimo deriva da un cookie ospite firmato con subject in namespace
`guest:`, mai da un valore di identità arbitrario inviato nel body.

`ConversationStore` espone acquisizione, commit e rilascio. L'implementazione
`MemoryConversationStore` verifica owner, TTL assoluto, turni, capienza e flag busy
senza await fra controllo e acquisizione nel singolo event loop. Una seconda
richiesta sullo stesso ID riceve 409; il finally rilascia anche su errori o
cancellazione. Il commit salva solo user e risposta finale del server, non tool
message o messaggi assistant del client. La history elimina coppie intere dalla
coda più vecchia per rispettare il limite in byte, senza resettare i turni.

Default e status sono nella tabella del README e in `.env.example`. Nessuna
espulsione delle conversazioni attive per accettarne di nuove: a capienza piena
503. Il provider riceve contesto limitato e output massimo; ogni chiamata fisica,
incluso ogni retry, prenota dal budget generazione byte UTF-8 serializzati dei
messaggi, overhead per messaggio/schema e massimo output token. È una stima
conservativa per i tokenizer byte-pair usati, non telemetria né costo misurato.
Contesto/budget esaurito restituiscono il fallback stabile. I token embedding non
consumano questo budget, ma input, dispatch, retry e deadline restano limitati.

Lo store è volutamente volatile e per processo: un worker per v1. Riavvio/reload
perde history e quote; un altro worker non ha la conversazione e restituisce 404.
La futura sostituzione deve rendere atomici owner/TTL/busy/commit e condividere
anche il rate limiter; sticky session da sola non rende globali quote e capienza.
Cache email→ID: TTL fisso monotono, accesso LRU e rimozione prima dell'inserimento,
con capienza globale per processo. Nessuna cache di errori o clienti inesistenti.

### DEC-015 — Demo esplicita, minimizzazione dati e limiti HTTP (#6)

`DEMO_ENABLED=false` è il default: la route `/demo/login` non viene registrata.
Production rifiuta secret vuoto/predefinito/corto e qualunque attivazione demo.
`development` è un ambiente locale, non un'alternativa al controllo production.
L'emissione token tramite un'identità Woo/SSO realmente verificata resta a carico
dell'integrazione di deployment. Il token demo è restituito solo al login e non
viene usato come prova che il chiamante sia il cliente reale del negozio.

Il widget scopre il flag con `/session/config`, conserva il token solo in memoria,
azzera conversazione e DOM ad ogni cambio sessione e usa una generazione numerica
per scartare login/risposte tardivi. 401 azzera l'identità, 404/409 la conversazione,
429 mostra l'attesa senza replay automatico. Cookie ospite HttpOnly, SameSite=Lax,
Secure in production: widget/API sullo stesso site o proxy sul dominio negozio.
Il logout del widget elimina il token locale; non è revoca server-side di token
copiati, che restano validi fino alla scadenza. Ruotare il secret invalida tutti.

Il limite `/chat` precede autenticazione e parsing JSON, comprende richieste
invalide e usa digest del peer di rete: finestra fissa e `Retry-After` su 429.
Il body è letto per chunk entro una dimensione massima; errori di validazione
non includono input o segreti. Middleware CORS esterno applica gli header anche
ai rifiuti anticipati. Con `--no-proxy-headers`, X-Forwarded-For non permette di
cambiare quota. Dietro proxy applicare quote al proxy su IP verificati; altrimenti
il backend vede un solo peer condiviso. Il rate limiter non rimuove chiavi attive
per fare spazio a nuove identità; a capienza piena rifiuta temporaneamente.

Gli output tool (inclusi documenti e campi Woo) entrano nel modello solo come
`ToolMessage` con oggetto JSON `untrusted_data`. Le istruzioni di sistema indicano
che i valori sono evidenze non fidate; eventuali delimitatori o ruoli sono stringhe
JSON, non nuovi messaggi. Questa delimitazione non dimostra resistenza semantica
del modello: la sicurezza degli ordini rimane nei controlli di autorizzazione.

Prima di prompt, tool message, history e risposta vengono oscurati email,
credenziali note, token riconoscibili, riferimenti etichettati a customer ID e valori
d'identità della sessione. `privacy_scope` usa ContextVar per isolare le richieste.
Il formatter ordini mantiene l'allowlist di campi e il filtro customer/id prima
di trasmettere dati. La redazione è difesa aggiuntiva, non classificazione DLP di
qualsiasi stringa segreta offuscata: la knowledge base deve contenere solo dati
pubblici. Metadati/fonti della risposta HTTP passano dalla stessa redazione.

I client non possono scegliere gli ID di log: entrambi sono generati dal server
per la richiesta e non coincidono con token o handle di conversazione. I log
operativi mantengono soltanto metadata allowlisted; access log Uvicorn disabilitati
per non conservare query string. Proxy e tracing esterni devono rispettare la
stessa minimizzazione. I test del provider sintetico controllano anche il payload
HTTP effettivamente ricevuto dal modello, senza conservarlo nei report.


### DEC-016 — Collection immutabili e registro POSIX condiviso

L'ingestion acquisisce un lock amministrativo prima del fetch e costruisce una
collection `kb-<namespace>-<manifest sha256>`. Manifest e collection registrano
modello, dimensioni e contenuti ordinati, con gli ID di DEC-010. Prima dello switch
si controllano conteggio, uguaglianza completa dei record, dimensioni/validità dei
vettori e query strutturale. Nessuna cancellazione dell'attiva precede la build.

Chroma non viene usato come lock distribuito o alias con compare-and-swap: la
promozione è un `os.replace` di un puntatore persistito con `fsync`, nel volume
POSIX locale condiviso da API e ingest. Un lock non bloccante serializza gli
amministratori; processi concorrenti falliscono esplicitamente. Questo contratto
supporta il deployment Compose su un host, non volumi indipendenti o NFS.

Ogni ricerca mantiene uno snapshot via ContextVar e lock condiviso per l'intero
retrieval, inclusi BM25 e retry. Promozione/rollback non bloccano quelle già avviate.
Cleanup con target esatto verifica ownership, protegge attiva/precedente e rifiuta
la cancellazione in presenza di lettori. Non esiste garbage collection automatica;
le candidate fallite restano diagnosticabili. Durante cleanup nuove ricerche possono
ricevere indisponibilità temporanea: eseguirlo come manutenzione separata.

Prima della prima migrazione il reader può continuare a leggere la collection
legacy, mai scritta dal nuovo ingest. Readiness distingue processo vivo da servizi
e KB pronti, senza chiamare provider AI. API/ingest installano il wheel completo;
lock Python e digest Docker sono condivisi fra build, CI e harness locale.

Protocollo, crash recovery, bootstrap e limiti sono descritti nella
[guida operativa](ingestion-deployment.md). I test su WordPress/Woo e Chroma reali
usano solo una rete interna e provider deterministici, non dati della demo.
