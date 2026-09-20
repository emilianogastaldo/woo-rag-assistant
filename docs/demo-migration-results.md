# Migrazione controllata della demo — inventario e piano

**Stato: piano pronto, migrazione non eseguita.**

Inventario del 20 settembre 2026, circa 21:40 UTC. Nessuna issue GitHub nuova:
il follow-up non assegna un numero. Questo report documenta la fase preliminare,
non certifica una migrazione completata.

## Revisione e autorizzazioni

- Worktree condiviso pulito, branch `feat/issue-7-ingestion-deployment`, HEAD
  `f6aaa755ae296e550c80c0ad7eb1b5572d9e1a25`; branch e sorgenti lasciati invariati.
- Dopo `git fetch origin`, target integrato `origin/main`:
  **`e1389ca0574bf33279d1fc1dcf11a0d415eb45b7`**, merge della PR #14.
  Il tree coincide con quello del worktree condiviso (`git diff HEAD origin/main` vuoto).
- Report preparato nel worktree separato `/tmp/woo-demo-migration-report`, branch
  `docs/demo-migration-plan`; nessuna merge automatica.
- Letti `CLAUDE.md`, README, guida ingestion/deployment, report #7, Dockerfile,
  Compose, CLI ingestion, registry, readiness, chunking e configurazione.
  Nessun `AGENTS.md` trovato nel percorso applicabile.
- Autorizzati dal task: letture/inventario, piano e report/PR separati. Gli accessi
  Docker in sola lettura e la creazione del worktree hanno superato i permessi
  dell'ambiente. Questi permessi **non** autorizzano manutenzione o provider.
- **NON ESEGUITO / consenso operativo ancora da ottenere:** backup, stop/start,
  build/test in container, creazione di volumi, deploy, ingestion e promozione.
- **NON ESEGUITO / consenso provider assente:** invio corpus e chiamate OpenAI,
  LlamaCloud o chat. Nessuna modifica a `.env`; nessun seed o cleanup.

## Inventario effettivo

Contesto Docker `default`, endpoint `unix:///var/run/docker.sock`, Engine 29.8.0.
Progetto Compose `woo-chatbot`; file nel worktree condiviso. Esiste anche il progetto
`databases`, fuori perimetro. Quattro container demo running dall'avvio del
19 settembre; nessun container ingest rilevato. Nel namespace processi accessibile
si vede una sessione Codex; non è prova dell'assenza di operatori/sessioni sull'host.
Prima della manutenzione serve esclusività operativa su demo e ingestion.

| Servizio / container `woo-chatbot-…-1` | Riferimento in uso | Image ID (SHA-256) | Porte host |
| --- | --- | --- | --- |
| `chatbot-api` | `woo-chatbot-chatbot-api:latest` | `1c6ad01a731ecbfbaba94c1b4ad7993100adfdece57b7c33edde58c9ae2b71c6` | 8000 |
| `wordpress` | `wordpress:php8.3-apache` | `cc795f5862b2f3891a805106917089558eef28a56755bd8ac8308d1ab57b28d7` | 8080 |
| `db` | `mariadb:11` | `efb4959ef2c835cd735dbc388eb9ad6aab0c78dd64febcd51bc17481111890c4` | nessuna; 3306 interna |
| `chromadb` | `chromadb/chroma:latest` | `1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6` | 8001 → 8000 |

Le porte pubblicate sono su IPv4 `0.0.0.0` e IPv6 `::`.
MariaDB ha healthcheck healthy; gli altri container attuali non hanno healthcheck.

Mount osservati:

- API: `chatbot` → `/app` e `evals` → `/evals` in lettura/scrittura;
  `widget` → `/widget` in sola lettura, tutti dal worktree condiviso.
  Comando Uvicorn con `--reload`, senza numero esplicito di worker.
- `woo-chatbot_db_data` → `/var/lib/mysql`;
  `woo-chatbot_wp_data` → `/var/www/html`;
  `woo-chatbot_chroma_data` → `/data`. Volumi Docker locali persistenti.
- **`woo-chatbot_knowledge_state` non esiste**, e l'API non monta `/state/knowledge`.
  Anche la directory del namespace nel filesystem del container è assente.

L'API combina una vecchia immagine con i sorgenti attuali montati. La revisione del
processo caricato non è attestata dall'Image ID: `/openapi.json` espone già `/ready`,
ma manca la nuova configurazione di persistenza. Non basta riutilizzare il tag
vecchio per descrivere o recuperare questo stato: vanno preservati anche i sorgenti.

### Compatibilità immagini

I digest target Compose per **WordPress, MariaDB e Chroma coincidono esattamente**
con gli Image ID e RepoDigest in esecuzione. Non è previsto un cambio di binari
su quei volumi. Chroma risponde `1.0.0` all'endpoint versione; il client del lock
Python è `chromadb==1.5.9`. Il comportamento del client target sulla copia va
comunque verificato: l'uguaglianza dell'immagine server non dimostra la migrazione.

I tag locali `woo-rag-api:issue7` e `woo-rag-ingest:issue7` puntano entrambi a
`sha256:20790280c4d27bcb73e50f4c42694ecca77e6e090bc0344275c9c57d5d8e20d5`.
La presenza dei tag non attesta da sola la loro provenienza. Il piano prevede
una build dalla revisione esatta target, tag dedicati e registrazione degli ID,
senza sovrascrivere immagini di recupero. Se cambiano i digest delle dipendenze,
stop: revisione del piano e prova su copia prima di collegarle ai volumi.

## Knowledge base e configurazione

| Campo | Osservato / target |
| --- | --- |
| Endpoint | `chromadb:8000`, tenant `default_tenant`, database `default_database` |
| Namespace / legacy | `woo_knowledge` |
| Collection rilevate | una: `woo_knowledge`, 12 record, dimensione 1536 |
| Metadati collection legacy | nessun campo modello, owner, manifest o `hnsw:space` disponibile |
| Collection versionate | nessuna rilevata nel database (lista con limite 1000, un risultato) |
| Registro persistente / manifest | assenti |
| Active / previous registrati | assenti; reader previsto in fallback legacy |
| Modello embedding configurato | `text-embedding-3-small`, endpoint OpenAI predefinito |
| Target chunking / dimensioni | 800 caratteri, overlap 120, 1536 dimensioni |
| Target retrieval | `semantic`, retry retrieval `0` |
| Generazione configurata | `gpt-4.1-mini`; nessuna chiamata eseguita |
| Ambiente / demo | `development`, `DEMO_ENABLED=false` nel Compose risolto |

Il digest del namespace è
`ac71fcb760ee03c081d5e8cb5e654d7659e45bab83959ca8b296e893ace1d4ac`.
Il registro target è sotto `/state/knowledge/<digest>`; API e ingest, verificati
anche con il profilo `ingest`, dichiarano lo stesso `knowledge_state`, namespace,
modello e dimensioni. Il chunking 800/120 è esplicito per API; ingest non riceve
queste due variabili dal Compose e usa i medesimi default nel codice. Questo volume condiviso è soltanto **previsto**,
non già applicato ai container. Non è stato eseguito neppure `ingest status`:
il suo lock inizializza directory e file.

I 12 record legacy non provano provenienza del modello, correttezza degli ID o
citazioni, metrica dell'indice né dimensione del nuovo corpus. Non sono stati letti
documenti, embedding o manifest completi durante l'inventario.
Il login demo risulta disabilitato anche da `/session/config`: il piano mantiene
questa scelta. L'eventuale attivazione richiede una scelta esplicita, solo development.

## Verifiche prima della migrazione

| Controllo | Esito | Evidenza / limite |
| --- | --- | --- |
| Stato Git / target integrato | PASS | Worktree pulito; target remoto acquisito, tree coincidente |
| Confronto server e pin | PASS | Image ID / RepoDigest identici per DB, WP e Chroma |
| Inventario Chroma e registro | PASS | 12 record legacy, 1536 dimensioni; nessun registro/versione |
| `/health` | PASS | HTTP 200: liveness soltanto |
| `/openapi.json` | PASS | HTTP 200, route `/ready` presente |
| `/session/config` | PASS | HTTP 200, `demo_enabled=false` |
| `/widget/`, `/widget/chat.js` | PASS | Entrambi HTTP 200; verifica statica, nessun browser |
| `/ready` | NON ESEGUITO | Il codice entra in `Registry.snapshot()` e creerebbe `readers.lock` nella directory assente |
| Backup e ripristino | NON ESEGUITO | Richiedono autorizzazione e manutenzione concordata |
| Test/eval sulla revisione target in questa sessione | NON ESEGUITO | Rinviati alla preparazione autorizzata |
| Candidate / promozione / controlli post-deploy | NON ESEGUITO | Consensi mancanti |
| Chat provider / browser | NON ESEGUITO | Fuori dalla verifica preliminare |

La baseline storica #7 è Ruff PASS, 226 test e 90/90 eval agente, più integrazione
isolata. Non viene riclassificata come un test attuale o live della demo.
La persistenza richiesta dal target manca: è una precondizione da realizzare,
non un errore da aggirare disabilitando readiness.

## Piano locale da autorizzare

**Perimetro della prima autorizzazione:** preparazione, build e test sintetici
isolati, backup coerente e prova di ripristino, inventario locale del corpus per
stimare l'ingestion. Non comprende ingestion, promozione o deploy finale.

1. Ricontrollare HEAD, container, volumi e operatori prima delle modifiche.
   Preparare tutto nel worktree separato dalla revisione
   `e1389ca0574bf33279d1fc1dcf11a0d415eb45b7`. Il worktree montato resta invariato.
   Costruire API e ingest con tag dedicati `woo-rag-api:demo-e1389ca` e
   `woo-rag-ingest:demo-e1389ca`; registrare gli Image ID risultanti.
   Eseguire Ruff, pytest, eval agente 3 ripetizioni con provider finti e rete
   disabilitata. L'integrazione sintetica usa solo risorse isolate e nuovi volumi;
   i dati demo non diventano fixture di test.
2. Preparare una directory privata fuori Git:
   `/home/emilianogastaldo/.local/share/woo-rag-assistant/backups/demo-migration-20260920/`,
   con permessi directory 0700/file 0600, senza sovrascrivere backup preesistenti.
   Verificare spazio per archivio immagini, dati e copie di ripristino; riportare
   dimensioni e hash nel registro privato, senza esportare contenuti nella PR.
   Conservare `.env`, configurazione effettiva, riferimenti/archivi delle immagini,
   sorgenti Git e inventario dei mount necessari a ricreare l'API precedente.
3. Concordare una finestra di manutenzione della chat: **budget proposto 15 minuti**
   per stop, copia coerente e restart, da confermare dopo aver misurato i volumi.
   Interdire amministrazioni/ingestion e accessi concorrenti; fermare prima
   `woo-chatbot-chatbot-api-1`, poi `woo-chatbot-chromadb-1`. Non copiare il DB attivo.
   Copiare il volume Chroma fermo con ownership e permessi preservati; includere
   registro e manifest se nel frattempo presenti, altrimenti registrare la loro
   assenza verificata. Conservare questo abbinamento Chroma/stato come una singola
   generazione di backup. Riavviare gli stessi container senza ricrearli dopo la
   copia; non lasciare la demo ferma per tutta la prova di ripristino.
4. Ripristinare in volumi **nuovi e isolati** usando lo stesso digest Chroma,
   senza porte pubblicate né provider. Verificare hash dell'archivio, lettura dei
   dati, collection/count/dimensione, metadati e ID, e una query con un vettore già
   memorizzato. Verificare la coppia registro/Chroma e la configurazione di recupero
   dell'app precedente; non confondere un semplice `tar -t` con il restore riuscito.
   Documentare separatamente ciò che non è possibile provare sul recupero API.
5. Leggere in locale il corpus effettivo previsto dal CLI, senza embedding, ordini
   o clienti; contare prodotti, pagine, caratteri, chunk e token. Verificare i
   permessi read-only Woo senza pubblicare chiavi. Preparare la stima e il consenso
   separato indicati sotto. Arrestarsi se il corpus cambia rispetto all'inventario
   approvato o se la dimensione supera i limiti concordati.

WordPress, MariaDB e relativi volumi restano sui container attuali: non sono oggetto
di stop, deploy o ripristino di questa proposta. Nessun `compose up` generale.
Qualsiasi necessità di ricrearli estende il perimetro e richiede un nuovo piano
che includa backup coerenti e verifica di ripristino **anche di WP e DB**.

## Consenso separato per corpus e provider

Da presentare **dopo il conteggio locale e prima di qualsiasi embedding**:

- Corpus: nomi e descrizioni brevi/complete dei prodotti pubblicati, pagine
  `spedizioni`, `resi-e-rimborsi`, `domande-frequenti`; pulizia HTML e chunking
  previsti dal codice corrente. Nessun ordine, cliente o history. Manifest e
  metadati restano locali; a OpenAI vanno i testi dei chunk.
- Provider proposto: OpenAI, endpoint predefinito, `text-embedding-3-small`,
  1536 dimensioni. LlamaCloud non viene chiamato dal CLI attuale.
- Volume e costo: **ancora da calcolare**, non deducibili dai 12 record legacy.
  Riportare numero di chunk, token stimati, richieste previste e prezzo ufficiale
  verificato al momento; esplicitare margine e tetto di costo autorizzato.
- Limiti da fissare con il consenso: singola build candidate-only, massimo corpus/
  token/richieste, timeout totale e per richiesta, nessun retry automatico dell'SDK
  embedding (`max_retries=0` nel codice), nessuna ripartenza dopo errore senza
  diagnosi. Il CLI non impone un tetto monetario o un timeout globale: richiedere
  limiti effettivamente applicabili prima di partire, non promettere un cap inesistente.
- Nessuna generazione chat o judge. Lo smoke live resta separato.

Disponibilità delle chiavi e approvazioni del sandbox non sono consenso al provider.

## Candidate, promozione e deploy successivi

Anche le seguenti operazioni restano **NON ESEGUITE**; verranno incluse nel consenso
operativo per la fase successiva. Prima predisporre una configurazione Compose
privata verificata, con progetto `woo-chatbot`, endpoint/volumi espliciti, immagini
immutabili e sorgenti/widget fissati dal worktree separato. Per l'API usare il
wheel senza hot reload e un solo worker. Non applicare automaticamente le modifiche
ai servizi dipendenti del Compose corrente: i loro container sono ancora privi dei
nuovi healthcheck. Usare `--no-deps` dopo verifica esplicita delle dipendenze.

Creare `woo-chatbot_knowledge_state` soltanto dopo autorizzazione; API e ingest devono
usarlo entrambi a `/state/knowledge`. Il namespace resta `woo_knowledge`; semantic,
retry 0, modello e chunking restano invariati. Ogni comando sotto va eseguito
singolarmente con **la configurazione operativa esplicita verificata**, non dal
worktree condiviso alla cieca:

```bash
# Prima sola lettura logica del registry, ma crea directory/lock: richiede consenso.
docker compose run --rm --no-deps ingest python -m app.ingest status
# --no-deps evita la ricreazione involontaria di WP/Chroma.
docker compose run --rm --no-deps ingest python -m app.ingest build --candidate-only
# SOLO dopo il successivo go/no-go sul risultato e nome completo:
docker compose run --rm --no-deps ingest python -m app.ingest promote --target NOME_COMPLETO
```

Non eseguire il comando ingest senza argomenti: costruisce **e promuove**.
Il nome completo deterministico inizia con `kb-ac71fcb760ee03c0-` e verrà ricavato
dal manifest; non è noto prima di acquisire il corpus. Mostrare nome completo,
conteggio, modello/dimensione, digest e risultato delle validazioni del CLI:
uguaglianza di testo/metadati/ID, identità citabile `chunk-v1-*`, vettori finiti,
conteggio e query strutturale a distanza circa zero. Nessun manifest nella PR.
Verificare che build candidate-only non abbia modificato il puntatore attivo.

Dopo tale evidenza chiedere un **go/no-go esplicito per promozione e deploy API**.
Prevedere una seconda finestra di chat indisponibile, budget proposto 5 minuti:
fermare/drainare la vecchia API, promuovere il nome autorizzato e ricreare solo API
con immagine verificata e stato condiviso; controllare dipendenze senza bypass.
Il riavvio perde conversazioni, sessioni applicabili e contatori in memoria;
non promettere zero downtime e non aumentare i worker.

Dopo deploy: verificare Image ID/revisione, mount condiviso, `status`, attiva/precedente,
`/health`, `/ready` HTTP 200, widget HTML/JS e `/session/config`. Registrare l'esito
senza chiamare `/chat` o simulare un browser. Non disabilitare auth, owner filtering,
history server-side, Woo read-only o controlli readiness per ottenere PASS.

## Recupero e condizioni di stop

**Prima promozione da legacy:** `previous` sarà `null`; il comando ordinario
`rollback --target woo_knowledge` non riattiva la legacy e non va utilizzato.

Conservare sempre legacy, candidate, eventuale precedente e backup. In caso di
fallimento dopo la prima promozione: fermare API e amministrazioni, preservare il
nuovo stato per diagnosi, quindi ripristinare in volumi distinti la coppia
Chroma/registro del backup verificato e ricreare l'app con immagine, configurazione
e sorgenti pre-migrazione. Il backup iniziale attesta registro assente: recuperare
quel preciso stato insieme alla legacy, senza cancellare a mano `active.json` o
lock nel volume migrato. Ricollegare soltanto i volumi recuperati verificati.
Controllare la legacy e l'app rispetto alla baseline precedente; non attribuire
alla baseline garanzie di readiness o qualità che qui non sono state misurate.

Per le promozioni future già registrate, `rollback --target NOME_PREVIOUS` è ammesso
solo se il nome coincide con `previous`, appartiene al namespace, ha manifest integro
e passa validation con modello/dimensioni compatibili. Verificato nel codice CLI.

Fermarsi e mantenere/recuperare il precedente stato in presenza di: operatore o
writer concorrente; revisione/digest/mount diversi dal piano; backup o restore non
verificati; permessi Woo non read-only; corpus non concordato; limiti provider non
applicabili; errore fetch/embedding/validation; stato attivo cambiato inaspettatamente;
readiness negativa dopo deploy; immagini diverse sui volumi non ancora provate su
copia. Nessun refactor, seed, reset, `down -v`, prune o cleanup automatico.

## Consegna al follow-up live

Prerequisiti verificati: revisione integrata disponibile, digest server coincidenti,
legacy presente, CLI versionato e target Compose coerenti a livello dichiarativo,
liveness e widget statico raggiungibili. Restano da autorizzare ed eseguire backup/
restore, prove offline attuali, ingestion e deploy; serve poi il go/no-go sulla
candidate. Attiva/precedente finali non disponibili: migrazione non completata.
Nessuna evidenza di qualità semantica o browser è stata prodotta. Il follow-up live
richiederà un proprio consenso preciso per chiamate a pagamento e scenari di chat.
