# Migrazione controllata della demo — risultati e prossimi consensi

**Preparazione locale PASS; migrazione non eseguita.**

Inventario iniziale: 20 settembre 2026. Preparazione autorizzata: 21 settembre
2026, ora italiana (snapshot il 20 settembre alle 22:20:50 UTC).
Nessuna issue nuova: il follow-up non assegna un numero. PR separata #15,
branch `docs/demo-migration-plan`; nessuna merge automatica.

## Autorizzazioni e revisioni

L'utente ha risposto **«si, autorizzo»** alla proposta di test isolati, backup
coerente, prova di ripristino e conteggio locale del corpus, con una finestra di
manutenzione fino a 15 minuti. Questa autorizzazione è stata utilizzata solo per
la preparazione locale. **Provider, candidate, promozione e deploy finale non sono
ancora autorizzati né eseguiti.**

- Worktree condiviso: branch `feat/issue-7-ingestion-deployment`, HEAD
  `f6aaa755ae296e550c80c0ad7eb1b5572d9e1a25`, pulito prima e dopo.
- Target integrato dopo #7: **`e1389ca0574bf33279d1fc1dcf11a0d415eb45b7`**,
  merge PR #14, acquisito con `git fetch origin`; tree applicativo uguale al
  worktree condiviso. Il suo branch non è stato cambiato.
- Preparazione nel worktree `/tmp/woo-demo-migration-report`. I test principali
  e l'harness hanno usato il commit documentale `9095042`, con codice, Dockerfile,
  lock e Compose identici al target. Il digest dei file applicativi è
  `a461b4cdce9081b370cd1264ac9f49f04efcef2df6fb48fe4f34f52c505fdcf4`.
- Nuovi file operativi: `scripts/demo_candidate.py` e relativo test. Non modificano
  app, CLI ordinario, modelli, chunking, retrieval o funzionalità della demo.
  Lint e test del runner sono aggiunti anche alla CI; i test bloccano DNS/socket.
- Letti istruzioni applicabili, `CLAUDE.md`, README, guida ingestion/deployment,
  report #7, Compose e codice del CLI/registry/readiness. Nessun `AGENTS.md`
  trovato nel percorso applicabile.

Nessuna modifica a `.env`, nessun seed, nessun ordine/cliente letto per ingestion,
nessuna chiamata AI. Docker e le chiavi disponibili non sono consenso al provider.

## Inventario e compatibilità

Contesto `default`, endpoint `unix:///var/run/docker.sock`, Engine 29.8.0,
progetto Compose `woo-chatbot`. Il progetto `databases` è fuori perimetro.
Nessun ingest demo concorrente rilevato; l'inventario dei processi accessibile
mostra una sessione Codex, ma non certifica tutte le sessioni dell'host.
Ricontrollare l'esclusività operativa prima della fase successiva.

| Container `woo-chatbot-…-1` | Immagine preesistente (SHA-256) | Dati / porta |
| --- | --- | --- |
| `chatbot-api` | `1c6ad01a731ecbfbaba94c1b4ad7993100adfdece57b7c33edde58c9ae2b71c6` | Bind `chatbot:/app`, `evals:/evals`, `widget:/widget:ro`; 8000 |
| `wordpress` | `cc795f5862b2f3891a805106917089558eef28a56755bd8ac8308d1ab57b28d7` | `woo-chatbot_wp_data:/var/www/html`; 8080 |
| `db` | `efb4959ef2c835cd735dbc388eb9ad6aab0c78dd64febcd51bc17481111890c4` | `woo-chatbot_db_data:/var/lib/mysql`; 3306 interna |
| `chromadb` | `1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6` | `woo-chatbot_chroma_data:/data`; 8001 → 8000 |

Le porte host sono pubblicate su IPv4 `0.0.0.0` e IPv6 `::`. MariaDB ha healthcheck
healthy; gli altri container attuali non hanno healthcheck. Gli ID dei quattro
container e delle immagini sono rimasti invariati dopo la manutenzione.

L'API preesistente usa Uvicorn `--reload` e una vecchia immagine con sorgenti attuali
montati: l'immagine da sola non identifica il codice servito. I sorgenti sono
inclusi nel backup di recupero. Non sono stati modificati mentre montati.

I digest target di **Chroma, MariaDB e WordPress coincidono con quelli in uso**:
nessun downgrade o cambio di binari sui loro volumi. Chroma restituisce `1.0.0`;
il client target `chromadb==1.5.9` è stato provato sul ripristino isolato.
WordPress e DB non sono stati fermati, aggiornati, ricreati o sottoposti a restore.
Un loro coinvolgimento futuro richiede un piano esteso ai rispettivi backup.

Build eseguita da sorgenti target:

```bash
docker build -t woo-rag-api:demo-e1389ca -t woo-rag-ingest:demo-e1389ca chatbot
```

Entrambi i tag puntano a
`sha256:e6c9b42ac33c1f8babe5c39c4a469563a6d4818039d9069e25066175b789d6c2`.
Le immagini preesistenti restano conservate; nessun riutilizzo del tag demo vecchio.

## Knowledge base e stato attuale

- Endpoint `chromadb:8000`, tenant `default_tenant`, database `default_database`.
- Namespace e unica collection: **`woo_knowledge`**, 12 record, 1536 dimensioni.
  La lista restituisce una collection; nessuna collection versionata rilevata.
- Nessun manifest/owner/modello o `hnsw:space` dichiarato nei metadati legacy.
  Conteggio e dimensione non attestano qualità, citazioni o provenienza del modello.
- **`woo-chatbot_knowledge_state` resta assente**, così come `/state/knowledge`
  nel container API. Nessun puntatore active/previous registrato: fallback legacy.
- Namespace digest:
  `ac71fcb760ee03c081d5e8cb5e654d7659e45bab83959ca8b296e893ace1d4ac`.
- Target invariato: `text-embedding-3-small`, 1536 dimensioni, chunking 800/120,
  retrieval `semantic`, retry retrieval `0`. API e ingest nel Compose risolto
  condividono questi parametri e il futuro volume POSIX `knowledge_state`.
- Ambiente `development`, `DEMO_ENABLED=false`, confermato da `/session/config`.
  Non è stato abilitato il login demo. La generazione configurata resta
  `gpt-4.1-mini`, mai invocata in questa preparazione.

La lettura finale di tutti i record legacy, eseguita localmente senza stamparli,
ha confermato che testo, metadati, ID e vettori coincidono con la copia ripristinata.
Il digest canonico aggregato è
`36672d517d3eb8faf5dde9c92c796e8e6b6d268c2e31e6789dcc9171be35baaf`.

## Backup e ripristino verificati

Destinazione privata fuori Git:
`/home/emilianogastaldo/.local/share/woo-rag-assistant/backups/demo-migration-20260920/`.
Directory 0700, archivi/configurazione/documenti privati 0600. I sorgenti estratti
per la prova mantengono i propri permessi dentro questa directory protetta.

Preservati: configurazione effettiva e riferimenti dei container, `.env`, archivi
Git prima/target, immagini API precedente/target e Chroma, dati Chroma e attestazione
dell'assenza del registro. Nessuno di questi artefatti privati è nella PR.
L'archivio immagini occupa 612.648.448 byte; spazio libero verificato prima della copia.

Procedura realmente eseguita:

1. Verificati immagini, Git, writer/volumi e assenza di registro; salvate immagini e
   configurazione mentre la demo era ancora attiva.
2. Fermati **prima API, poi Chroma**, con uscita pulita. Copiato il volume Chroma
   fermo, preservando proprietari e permessi. Nessuna copia del DB attivo.
3. Riavviati gli stessi container Chroma/API. Heartbeat, `/health` e widget tornati
   HTTP 200. Durata complessiva stop/copia/riavvio/sonde: **7,86 secondi**.
   Conversazioni e contatori in memoria sono stati persi al riavvio, come previsto.
4. Ripristinati gli archivi in risorse nuove sulla rete interna
   `woo-demo-restore-a6da1247e6-network`, senza porte pubblicate o credenziali AI.
   Docker ha ricaricato e riconosciuto gli Image ID dall'archivio immagini.
5. Verificati hash, UID/GID e permessi di ogni file ripristinato **prima** dell'avvio.
   Il client target legge 12 record da 1536 dimensioni e la query con un vettore
   già memorizzato restituisce un ID esistente con distanza circa zero.
6. Avviata sulla copia la vecchia API con i sorgenti archiviati: `/health`,
   `/widget/`, `/widget/chat.js` e `/ready` HTTP 200. Woo readiness è **simulata**;
   credenziali provider/commerce rimosse per questa prova. Non sono provati recupero
   live di ordini, autenticazione Woo o comportamento del modello.
7. Confrontati record live/ripristinati, hash `.env`, stato Git e immagini: invariati.
   WordPress/DB conservano anche il loro timestamp di avvio precedente.

Archivio `chroma.tar`: **993.280 byte**, cinque file regolari, SHA-256
`0eecac973b08416ed4a3f69c3789d50c7836946db6aa5c6f5d8208f63967082c`.
La coppia di recupero è questo Chroma più **registro assente**, verificato prima
della copia. La sonda `/ready` ha creato un lock soltanto nell'API isolata di restore.

Le risorse di restore sono conservate: volume
`woo-demo-restore-a6da1247e6-chroma` e tre container omonimi con suffissi
`chroma`, `woo`, `api`, tutti fermati. Nessun cleanup della legacy o dei backup.
I report privati `preparation.json`, `snapshot.json`, `restart.json`,
`restore-results.json`, `restore-inventory.json` e `final-check.json` documentano
la prova. Non sono stati pubblicati payload né manifest.

## Test e controlli

| Controllo | Esito | Evidenza / limite |
| --- | --- | --- |
| Build target / wheel / lock | PASS | Build da sorgenti target con pin invariati; Image ID registrato |
| Ruff applicazione ed eval | PASS | Rete disabilitata; nessuna credenziale |
| Suite applicativa offline | PASS | **226 test**, un warning Starlette/AnyIO preesistente |
| Eval agente | PASS | **90/90**, confronto baseline #7 accettato senza regressioni funzionali |
| Servizi reali sintetici isolati | PASS | Run `woo-issue7-82f51a1904d6`, startup, fault injection, versioning, rollback, healthcheck |
| Query HTTP sintetiche | PASS | 107 query; nessuna chiamata provider esterna |
| Cleanup harness sintetico | PASS | Solo risorse del suo progetto dopo audit ownership |
| Backup coerente e recupero isolato | PASS | Hash/file/immagini, Chroma e startup API verificati come sopra |
| Woo key read-only | PASS | Solo SELECT del campo permissions per la chiave usata: `read` |
| Corpus / chunking / token | PASS | Conteggio locale, tokenizer offline, zero embedding |
| Runner candidate: lint e protezioni | PASS | 12 test offline su dati sintetici e `httpx.MockTransport` |
| Demo `/health` e widget statico prima/dopo | PASS | HTTP 200; nessuna prova browser |
| Demo `/ready` live | NON ESEGUITO | Creerebbe il registro assente; testata solo sull'API di restore e nell'harness sintetico |
| Candidate / promozione / deploy | NON ESEGUITO | Consensi separati ancora mancanti |
| Chat provider / browser | NON ESEGUITO | Nessuna affermazione di qualità live |

L'harness registra commit documentale `9095042` e digest applicativo uguale al target.
I suoi provider sono sintetici: 113 richieste embedding e 214 completamenti locali,
**zero chiamate AI esterne e costo API zero**. Le risorse demo non sono state usate
come fixture della suite; la loro copia è stata usata esclusivamente per il restore.

Comandi offline principali, nel worktree separato e dentro container senza rete:

```bash
ruff check . /evals --no-cache --config /app/pyproject.toml
pytest -q -p no:cacheprovider
python -m evals.run_agent_eval --repeats 3 \
  --baseline /evals/results/demo-migration-baseline.json \
  --output /evals/results/demo-migration-offline.json \
  --commit e1389ca0574bf33279d1fc1dcf11a0d415eb45b7
# Harness host: rete interna e volumi nuovi con ownership verificata.
python3 evals/run_issue7_integration.py
# Runner operativo: soltanto trasporti e corpus sintetici.
ruff check /scripts --no-cache --config /config/pyproject.toml \
  --config 'lint.isort.known-first-party=["app","evals"]'
pytest -q -p no:cacheprovider /scripts/test_demo_candidate.py
```

I tentativi preliminari hanno richiesto correzioni ai soli helper/test operativi:
filtro DB troppo ampio che includeva Chroma, ownership dei file generati come root,
nome del file di configurazione Ruff, ordinamento import e tipo di eccezione SDK
atteso dal test. Nessun difetto applicativo corretto o errore di migrazione ignorato;
le evidenze PASS si riferiscono alle verifiche finali riuscite.

## Corpus misurato e consenso provider richiesto

Il fetch ha effettuato due richieste locali GET: prodotti Woo pubblicati e tre
pagine WP `spedizioni`, `resi-e-rimborsi`, `domande-frequenti`. Il permesso della
chiave è stato verificato con una SELECT senza caricare WordPress o leggere ordini
/clienti. Pulizia HTML, metadati e chunking usano il codice corrente.

| Quantità | Misura |
| --- | ---: |
| Prodotti / pagine / documenti | 6 / 3 / 9 |
| Caratteri dei documenti | 5.324 |
| Chunk prodotto / pagina / totali | 6 / 6 / 12 |
| Caratteri / byte UTF-8 dei chunk | 5.385 / 5.455 |
| Token embedding stimati, `cl100k_base` | **1.605** |
| Token massimi per chunk | 230 |
| Richieste embedding eseguite | **0** |

Il dizionario pubblico del tokenizer è stato scaricato separatamente, verificato
contro il checksum del pacchetto, poi usato con rete disabilitata. Non è stato
inviato il corpus per il conteggio. Manifest e documenti sono conservati solo nella
directory privata `corpus-inventory` del backup.

Provider proposto: **OpenAI**, `https://api.openai.com/v1/embeddings`, modello
**`text-embedding-3-small`**, **1536 dimensioni**. Verranno inviati soltanto i testi
dei 12 chunk (nomi/descrizioni prodotti e testo delle tre pagine), non ordini,
clienti, history o manifest. Il CLI attuale non usa LlamaCloud.

Prezzo verificato sulla [pagina ufficiale del modello](https://developers.openai.com/api/docs/models/text-embedding-3-small):
**0,02 USD per milione di token**, quindi **0,0000321 USD stimati** per 1.605 token.
Proposta di budget autorizzato: **0,001 USD**, con limite operativo più restrittivo
di **una sola richiesta, massimo 2.000 token e 12 chunk**, senza retry. A quel prezzo,
2.000 token corrispondono a 0,00004 USD; non è un limite di spesa dell'intero account.
Una richiesta già ricevuta può essere fatturata anche se il client scade.

Il runner proposto (`scripts/demo_candidate.py`, SHA-256
`9ce30521960af8fe1172f476769f6c3d8cc43e126884854e0cb12b0a7dd7c1a6`)
rende concreti i limiti assenti nel CLI generico:

- `--allow-provider` obbligatorio; senza consenso il runner termina prima del registry.
- Digest del manifest atteso: stop se cambia corpus, metadato, modello o chunking.
- Controllo token/chunk prima di creare il client embedding.
- Hook HTTP: endpoint/modello/dimensioni/testi esatti, massimo un dispatch.
  Redirect e proxy d'ambiente disabilitati; retry SDK `0`.
- Timeout HTTP 15 s e deadline globale **120 s**; un errore interrompe la build,
  senza ripartenza automatica. Eventuali candidate parziali restano conservate.
- Lock amministrativo prima del fetch, `Registry.build(..., promote=False)`,
  validation completa del registry e verifica che active/previous non cambino.
- Nessuna generazione, promozione, rollback o cleanup nel runner.

Digest misurato del manifest:
`00ada154e603cbc48b0d62896d6bff6373fb544957920bde216992cfdfd4fa3c`.
Il nome candidate atteso è
`kb-ac71fcb760ee03c0-00ada154e603cbc48b0d62896d6bff6373fb544957920bde216992cfdfd4fa3c`.
È una **previsione dal corpus locale**, non una candidate già costruita o validata.

## Fase candidate da autorizzare

Serve ora consenso per **creare il volume `woo-chatbot_knowledge_state` e costruire
soltanto la candidate**, includendo il corpus/provider/costo/limiti sopra. Non serve
fermare la demo per la build; la legacy e il puntatore attivo devono restare invariati.

Configurazione privata predisposta e validata con `docker compose config`:
`<directory-backup>/candidate.compose.private.json`. Contiene solo il servizio
ingest, immagine target esatta, rete esterna `woo-chatbot_default`, volume esterno
`woo-chatbot_knowledge_state` → `/state/knowledge`, runner e tokenizer in sola
lettura. Nessuna porta, dipendenza avviata o immagine scaricata implicitamente.
Il comando predefinito **non** contiene `--allow-provider`, quindi non può avviare
involontariamente embedding. Questa configurazione non è stata eseguita.

Dopo consenso, ricontrollare revisioni, hash del runner, servizi, backup e corpus;
creare il solo volume previsto. Usare il file privato esplicito e `--no-deps`:

```bash
# Stato iniziale; crea directory/lock, quindi solo dopo consenso operativo.
docker compose --env-file /dev/null -f PERCORSO_PRIVATO run --rm --no-deps \
  ingest python -m app.ingest status
# Build con i limiti verificati; il digest va preso dall'inventario approvato.
docker compose --env-file /dev/null -f PERCORSO_PRIVATO run --rm --no-deps \
  ingest python /operations/demo_candidate.py --allow-provider \
  --expected-manifest DIGEST_APPROVATO
```

Non usare ingestion senza argomenti: il CLI ordinario costruisce **e promuove**.
Dopo la build presentare nome completo reale, digest, conteggio, dimensione,
metadati, ID/citazioni e tutte le validazioni del registry. Nessun manifest nella PR.
Chiedere quindi **go/no-go separato per promozione e deploy**.

## Promozione e recupero successivi

API e ingest dovranno condividere lo stesso volume POSIX locale e namespace.
Per il deploy preparare API standalone dal wheel verificato, widget fissato al
target, un solo worker, semantic-only e retry retrieval disabilitato. Ricreare
soltanto API; non applicare un `compose up` generale ai vecchi container WP/DB/Chroma.
Mantenere read-only Woo, identità server-side, ordini filtrati per proprietario,
history autorevole e demo abilitata solo su esplicita scelta in development.

Finestra proposta per promozione/deploy: fino a 5 minuti, da autorizzare dopo la
candidate. Fermare/drainare API, promuovere il nome esatto autorizzato con il CLI,
avviare solo API e verificare immagine/revisione, mount condiviso, `status`,
`/health`, **`/ready` HTTP 200**, widget statico e `/session/config`. Sessioni e
contatori in memoria si perdono al riavvio; nessuna promessa di zero downtime.
Non disabilitare controlli per ottenere readiness positiva. Non chiamare `/chat`.

**Prima promozione da legacy:** `previous` sarà `null`;
`rollback --target woo_knowledge` non recupera la legacy. In caso di fallimento:
fermare API/amministrazioni, conservare lo stato nuovo per diagnosi, ripristinare
in volumi separati il Chroma del backup verificato e l'assenza preesistente del
registro, poi ricreare l'app con immagine, configurazione e sorgenti precedenti.
Ricollegare soltanto la coppia recuperata verificata; nessuna modifica manuale
al puntatore o ai lock del volume migrato. La prova effettuata certifica startup,
lettura Chroma e widget, **non** autenticazione/ordini reali o qualità del modello.

Per versioni già registrate, `rollback --target NOME_PREVIOUS` richiede esatta
corrispondenza con `previous`, namespace corretto, manifest integro, modello e
dimensioni compatibili e validation completa. Verificato nel codice del CLI.

Condizioni di stop: writer/operatore concorrente; revisione/digest/mount cambiati;
backup non disponibile o incoerente; corpus non concordato; permessi Woo diversi
da read; budget superato; errore fetch/embedding/validation; modifica inattesa
all'attiva; readiness negativa dopo deploy. Nessun reset, seed, `down -v`, prune,
cleanup automatico di KB/backup o refactor fuori perimetro.

## Consegna al follow-up live

Verificati: target integrato, build, test offline e integrazione sintetica, backup
coerente, recupero isolato, persistenza della legacy, chiave read-only, corpus e
costo stimati, runner limitato. Restano **NON ESEGUITI** candidate, promozione,
deploy e readiness live finale. Active/previous registrati sono ancora assenti.
La migrazione non è completata e la PR resta bozza. Il follow-up live richiederà
consenso distinto per chiamate chat, modelli, corpus, budget e scenari browser.
