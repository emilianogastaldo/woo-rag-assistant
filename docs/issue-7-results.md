# Issue #7 — evidenze ingestion e deployment

## Provenienza

- Baseline: `main` pulita dopo merge #6, commit
  `58231c8ec27f778f90b0cb90d86fa01a6a834403`, pull fast-forward.
- Implementazione verificata: `18ff205b0b310e57cba852926553aa2e71a8b232`.
  Le successive modifiche riguardano questo report, riferimenti documentali e
  attesa esplicita del bootstrap in `seed/setup.sh` (verificata con `sh -n`).
- Docker Engine 29.8.0, contesto `default`, Linux amd64; contesto globale invariato.
- Nessuna modifica a `.env`, collection o volumi della demo; i quattro servizi
  `woo-chatbot` risultano ancora avviati da 22 ore al controllo conclusivo.
- Report JSON generati esclusivamente in `evals/results/`, gitignored.

## Esiti per livello

| Livello | Esito | Evidenza |
| --- | --- | --- |
| Lint offline | PASS | Ruff sull'app e tutti gli eval |
| Unit/integration in-process offline | PASS | 226 test, inclusa build wheel senza rete e import da installazione temporanea |
| Agente offline | PASS | 30 casi × 3 ripetizioni, confronto baseline schema 2 compatibile |
| Servizi Docker reali isolati | PASS | WordPress/Woo, Chroma, API standalone e API con sorgente montato |
| Readiness e fault injection locale | PASS | Startup ritardato, arresto/ripartenza WP e Chroma, healthcheck Docker |
| Live provider esterno | NON ESEGUITO | Consenso assente; nessuna chiamata o spesa API |
| Migrazione/reindicizzazione demo | NON ESEGUITO | Operazione separata, non autorizzata |
| Browser/UI | NON ESEGUITO | Nessuna modifica UI; prove HTTP e wheel non sono test browser |

Un warning di deprecazione Starlette/AnyIO rimane nella suite; nessun fallimento.
I test locali non certificano la qualità semantica di embedding reali né un rolling
update senza downtime del processo API: la continuità verificata riguarda gli switch
di knowledge base mentre il processo serve richieste.

## Comandi eseguiti

Prima delle modifiche, sull'immagine preesistente `1c6ad01a731e` e sorgente main:

```bash
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --repeats 3 --output /evals/results/issue-7-before.json
```

Il campo `commit` del report baseline è `null` perché il container non monta `.git`
e il comando non passava `--commit`; la provenienza è il commit main riportato
sopra, acquisito nella stessa sessione prima delle modifiche. Il report originale
non è stato riscritto. Dataset, fixture e digest implementazione restano nel JSON.

Dopo le modifiche:

```bash
docker build -t woo-rag-api:issue7 -t woo-rag-ingest:issue7 chatbot
docker compose run --rm --no-deps eval-offline ruff check . /evals --config /app/pyproject.toml
docker compose run --rm --no-deps eval-offline pytest -q
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --repeats 3 --baseline /evals/results/issue-7-before.json \
  --output /evals/results/issue-7-after.json \
  --commit 18ff205b0b310e57cba852926553aa2e71a8b232
python3 evals/run_issue7_integration.py
sh -n seed/setup.sh evals/issue7_seed.sh
git diff --check
```

Le run offline mantengono `network_mode: none`, credenziali vuote e blocco DNS/socket.
Build/download sono fasi separate e non invocano provider AI. La suite include
fallimenti di fetch, corpus vuoto, embedding, dimensione, scrittura, metadati/ID/testo,
smoke query, promozione, rollback, collisione, lock concorrenti, cleanup di candidate
e versioni obsolete, failure dello switch atomico e coerenza di ricerche concorrenti.

## Confronto offline

Schema 2, dataset, fixture e configurazione invariati. Il confronto `--baseline`
è stato accettato senza eccezioni o aggiramenti. Hash dataset:
`e5e68591c88685ca050dd2ae6b6f8bcc5eec8993afbeef872944760423c95b92`.
Hash fixture:
`d400270685948820bcdf9306c7e5f87556e380bede899646c3b1131405f80a34`.

| Metrica | Prima | Dopo |
| --- | ---: | ---: |
| Pass rate / routing / tool accuracy | 1.0 | 1.0 |
| Correttezza / astensione | 1.0 | 1.0 |
| Hit@k / MRR | 1.0 | 1.0 |
| Precisione / recall / validità citazioni | 1.0 | 1.0 |
| Chiamate modello medie (scripted) | 1.9 | 1.9 |
| Latenza media offline, ms | 1.049 | 1.615 |

Nessuna regressione **funzionale** segnalata nei 30 confronti per caso. La latenza
misurata è aumentata di circa 0.567 ms; esecuzioni su host condiviso con attività di
build, non un benchmark prestazionale controllato. Nessuna inferenza sulla latenza
live. Chiamate provider esterne e token fatturati: zero.

## Integrazione locale sul commit verificato

Run finale: `woo-issue7-97ca4dd5cd30`, dataset `issue7-synthetic-v1`, report schema 1.
Inventario: `evals/results/woo-issue7-97ca4dd5cd30/inventory.json`;
scenari: `scenarios.json` nella stessa directory.
Hash dei file applicativi:
`a461b4cdce9081b370cd1264ac9f49f04efcef2df6fb48fe4f34f52c505fdcf4`.

Immagini costruite (conservate localmente per ispezione):

| Ruolo | Tag | Image ID |
| --- | --- | --- |
| API | `woo-issue7-api:97ca4dd5cd30` | `sha256:22d7178e8452283932a4bb64deac462b1eef4a0e2a739bc8519c6c3460cb1ea6` |
| Ingest | `woo-issue7-ingest:97ca4dd5cd30` | stesso ID API |
| Runner/provider locale | `woo-issue7-runner:97ca4dd5cd30` | `sha256:2eee03b48f15f77a4faecf8ef8c2f035efeb00e4bd850c402d28edb53b374346` |
| WordPress/Woo | `woo-issue7-wp:97ca4dd5cd30` | `sha256:5d2160e4ee9bcba33d8c5ef294980e5762ae0b13eb6778da8ce5ff879e5e3917` |
| Seed CLI | `woo-issue7-cli:97ca4dd5cd30` | `sha256:4a0e67105af404c9fe3cd48433714d39b4db0d537525217773acbf351d0a310d` |

Chroma, MariaDB e basi WordPress/Python sono fissati a digest nei Dockerfile/Compose.
WooCommerce 10.0.4 è verificato contro SHA-256
`002b3cb8b1fcacf9836367a1ae617c87d6def0c33d16b8a79a4f81dad9894429`.
Anche i tag operativi `woo-rag-api:issue7` e `woo-rag-ingest:issue7` sono stati
ricostruiti dal medesimo sorgente senza riavviare la demo.

Il runner audita progetto, namespace, rete interna, assenza di porte pubblicate,
mount consentiti, volumi nuovi, endpoint locali e credenziali sintetiche. API e
ingest importano dal wheel in `site-packages`; nessun bind mount del codice. La
seconda API `dev` importa invece il sorgente montato. Il seed crea un prodotto e
una pagina, nessun cliente/ordine reale. Il provider si chiama `synthetic-embedding`
(8 dimensioni) / `synthetic-chat` e non contatta servizi esterni.

Scenari superati:

- Fetch dal Woo reale e manifest/metadati/chunk ID/dimensioni verificati in Chroma.
- Query su A durante costruzione di B, promozione A→B e rollback B→A, con controllo
  degli ID citati contro un solo manifest per risposta; BM25 e vettori reali.
- Fallimenti HTTP di fetch ed embedding; scrittura che fallisce dopo commit remoto;
  validation su testo/metadati corrotti; dimensione errata rifiutata dal server.
- Collisione fra due processi ingest: il secondo fallisce sul lock, senza modifiche.
- Rifiuto cleanup di attiva/precedente e in presenza di lettori; cleanup solo di
  candidate appartenenti all'inventario; retry ingestion idempotente.
- Import di tutti i moduli app dal wheel e query HTTP standalone e dev.
- `/health` 200 con dipendenze assenti, `/ready` 503→200 al bootstrap; WP e Chroma
  arrestati e riavviati singolarmente con 200→503→200. Healthcheck Docker PASS.

**95 query HTTP** con fonti non vuote e coerenti. Latenza media 46.15 ms,
minima 24.69 ms, massima 126.68 ms, esclusivamente su provider locale sintetico.
Contatori adapter: 101 richieste embedding riuscite, 190 completamenti, usage
sintetico dichiarato 1900 token input / 950 output. Il tentativo embedding HTTP
fallito sul path inesistente è aggiuntivo e non entra nel contatore delle richieste
riuscite. Il contatore token embedding non è aggregato dal fake; non si tratta di
misure di tokenizzazione o fatturazione reali. Chiamate esterne zero, costo API zero.

Cleanup PASS: eliminati solo i quattro volumi `woo-issue7-97ca4dd5cd30_{db,wp,chroma,state}`,
container e rete di questa run dopo verifica ownership. Controllo finale: nessun
container/volume di quel progetto residuo. Nessun prune o `down -v` sullo stack demo.

Durante la preparazione ci sono stati due fallimenti poi corretti: checksum calcolato
prima della fine del download Woo e campo `truncated_key` del seed sintetico troppo
lungo. Le run successive sono passate; non sono errori ignorati. La run finale
sopra sostituisce le evidenze preliminari per il codice applicativo.

## Limiti e operazioni successive

Il protocollo richiede un volume POSIX condiviso sul medesimo host e accesso
amministrativo esclusivamente tramite il registry. Cleanup può rendere brevemente
indisponibili nuove ricerche: eseguirlo separatamente dalla promozione. La validation
completa usa memoria proporzionale al corpus. Nessun test live del modello,
benchmark prestazionale controllato o aggiornamento reale della demo è stato svolto.
Il seed demo completo non è stato eseguito: l'harness usa un seed separato sintetico.

Per l'eventuale migrazione: verificare target e backup di Chroma+registro, stimare
costo del corpus autorizzato, preparare candidata e rollback, chiedere consenso.
Per uno smoke provider: concordare prima corpus sintetico, 4–6 query, modelli,
limiti di richieste/tempo/token e costo. Nessuna delle verifiche qui riportate
costituisce autorizzazione a eseguirli.

Procedure e vincoli: [guida operativa](ingestion-deployment.md).
