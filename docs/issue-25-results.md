# Issue #25 — verifica finale della demo WordPress

Verifiche del **4–5 novembre 2026**, branch `feat/wordpress-demo-20-25`, baseline
`02c3907ad490e179255a46145ac34eef05b41b98` più le modifiche del branch.
Le verifiche documentate precedono il commit e la PR; durante le prove non è
stata modificata la visibilità della repository.

## Procedura ripetibile dal sorgente

Servono Python 3, Docker e Compose. Dalla radice di un clone che contenga queste
modifiche preparare una volta le immagini già definite nel progetto:

```bash
docker build -f evals/Dockerfile.issue7 --target wordpress -t woo-issue19-wp:11.2.2 .
docker build -f evals/Dockerfile.issue7 --target cli -t woo-issue19-cli:11.2.2 .
docker build -t woo-rag-api:issue7 chatbot
docker pull mariadb@sha256:efb4959ef2c835cd735dbc388eb9ad6aab0c78dd64febcd51bc17481111890c4
docker pull chromadb/chroma@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6
python3 evals/run_issue19_import.py --demo-final
```

La preparazione delle immagini può scaricare dipendenze; questa verifica ha
riusato immagini locali, senza build o download. Il runner risolve i tag a ID
immutabili e li registra nel JSON del run. Il flag aggiunge verifiche al runner
già usato dalla #19, mantenendone il comportamento ordinario senza flag.
Non occorrono file o script da vecchie directory `/tmp`.
I comandi sopra seguono la versione corrente (WooCommerce 11.2.2); i risultati
storici sotto riguardano la 10.0.4.

Ogni run crea un progetto `woo-issue19-<uuid>`, rete **internal**, quattro volumi
nuovi (`db`, `wp`, `chroma`, `state`), nessuna porta pubblicata. Verifica prima
l'assenza delle risorse e prima del cleanup l'appartenenza dei volumi al progetto.
Compose usa `--env-file /dev/null` e variabili esplicite; il runner non legge
`.env`, non usa il Compose demo e non monta database o KB preesistenti.
La chiave Woo read-only generata nel database sintetico passa soltanto in memoria
al controllo di ingestion; non compare nei report. Il `finally` rimuove soltanto
container, rete e volumi della singola prova, anche in caso di errore.

## Risultati del setup e del corpus

**PASS** nel progetto `woo-issue19-157382234687`, incluso audit di isolamento e
cleanup. Il report JSON locale è
`evals/results/woo-issue19-157382234687/report.json` (output runtime ignorato da Git).
I controlli effettivi sono:

- WordPress nuovo e WooCommerce **10.0.4** locale, poi **due setup completi**;
  stesso catalogo dopo il primo e il secondo setup: sei prodotti, sette media
  (sei illustrazioni e un'immagine preesistente dello stack), quattro categorie
  compresa quella predefinita, non assegnata ai sei prodotti.
- Test reale `seed/tests/catalog.php`: SKU, prezzi, stock, descrizioni, alt,
  categorie, PNG importati identici ai sorgenti; stessi ID e conteggi dopo il
  secondo setup; categorie personalizzate conservate.
- Test reale `wordpress/tests/storefront.php`: Trama attivo con parent nativo,
  homepage unica, navigazione verso cinque destinazioni, policy HTML con testo
  preservato e nessun Markdown grezzo; ripetizione che conserva titolo e opzioni
  estranee, pagine e menu.
- `evals/issue25_ingestion.py`: fetch HTTP reale da Woo/WordPress di **sei
  prodotti e tre policy HTML**, esclusa la homepage. Controlla SKU, titoli,
  URL delle fonti e testo estratto, inclusi costi/soglie di spedizione.
  Costruzione e validazione su **Chroma reale: 12 chunk**, con metadati e ID
  corrispondenti ai documenti; seconda ingestion nella stessa versione senza
  una seconda collection.
- Un giro reale dell'agente esegue retrieval e validazione delle citazioni:
  tutte le fonti restituite appartengono al corpus corrente. Provider OpenAI
  compatibile **sintetico locale**, con **2 chiamate embedding e 2 chat**;
  zero chiamate a provider esterni. La frase prodotta dal fake serve soltanto
  a verificare il percorso software e non misura correttezza o qualità del testo.
- Il test #19 conserva anche l'importer CSV nativo: 18 prodotti principali e
  sette variazioni importati una volta, 25 righe saltate al secondo tentativo
  create-only e 25 aggiornate al terzo. Nessuna immagine/file remoto scaricato.
  Questo catalogo ampliato viene creato **dopo** la prova dei nove documenti.
- `evals/issue24_returns.php`: una sola fixture resi aggiunta ai tre storici;
  tre applicazioni, incluso recupero dopo interruzione simulata, stessi ID/date,
  storico e stock invariati. Il confronto entro termine/confine/fuori termine/
  consegna assente è coperto dai sei nuovi test Python e dagli otto test ordini.

ID effettivi del run finale, diversi da quelli dello stack visuale #24:

| Ordine | Cliente | Domanda della prova | Dato atteso |
| --- | --- | --- | --- |
| **#58** | Mario (2) | «Alla data del 18 dicembre 2026 posso ancora rendere l'ordine 58?» | Consegna 19/11, termine 19/12: entro termine; il 19 è il confine incluso, il 20 è fuori. |
| **#26** | Mario (2) | «Alla data del 19 dicembre 2026 posso ancora rendere l'ordine 26?» | Tracking 22/06, termine 22/07: fuori termine. |
| **#27** | Mario (2) | «Quando scade il reso dell'ordine 27?» | Tracking assente: non determinare la scadenza. |
| **#28** | Luigi (3) | Mario chiede «Qual è lo stato dell'ordine 28?» | Ordine non trovato per Mario. |

Questi ID appartengono al database eliminato dal test: su un nuovo setup usare
sempre quelli stampati dal seed. La data di completamento dello storico può
essere quella di creazione del database; i calcoli dei resi usano esclusivamente
la consegna verificata nel tracking.

### Problema trovato partendo da volumi puliti

Il primo seed storico creava ordini `completed`/`processing` che attivavano la
riduzione stock WooCommerce: solo un seed successivo ripristinava i valori CSV.
Il controllo nuovo ha rilevato la differenza al primo avvio. Ora il filtro nativo
`woocommerce_can_reduce_order_stock` impedisce la riduzione soltanto durante il
salvataggio che crea gli ordini sintetici; viene subito rimosso. Lo stesso limite
è applicato alla fixture resi opt-in. Gli ordini già presenti non sono riscritti.
La verifica confronta direttamente primo e secondo setup e controlla anche lo
stock dopo la preparazione dei resi.

Alcuni tentativi preliminari hanno corretto problemi del runner (escaping shell
Compose e parsing dei messaggi di successo WP-CLI); i loro report FAIL restano
localmente disponibili e tutti hanno cleanup PASS. Non sono presentati come
esecuzioni finali riuscite.

## Suite e altre verifiche

```bash
docker compose run --rm --no-deps eval-offline ruff check . /evals --config /app/pyproject.toml
docker compose run --rm --no-deps eval-offline pytest -q
node wordpress/tests/widget.mjs
php wordpress/tests/bridge.php
node --check widget/chat.js
git diff --check
```

**254 pytest PASS**, Ruff completo PASS; un warning di deprecazione
Starlette/AnyIO già noto. Suite eseguita nel container locale `woo-rag-api:issue7`,
con sorgenti/test montati, rete disabilitata e chiave OpenAI vuota, equivalente
al servizio `eval-offline`. I 254 includono i sei nuovi casi resi: non vanno
sommati ai risultati mirati della #24. Test Node del widget e PHP del bridge,
sintassi JavaScript e PHP dei file modificati, `git diff --check`: PASS.

L'harness HTTP #6 era già passata dopo le modifiche del widget e non è stata
ripetuta senza nuove modifiche funzionali al widget; dettagli nel
[report #23](issue-23-results.md). Quel risultato copre anche persistenza e
isolamento e usa provider sintetici.

## Browser, asset e limiti

**Browser PASS il 5 novembre** su WordPress/WooCommerce reali nel progetto
`woo-demo-21-final-20261105`, con nuovi volumi e sola porta loopback 18080.
Chromium CDP, cache disabilitata, desktop 1440×1000 e mobile 390×844: homepage,
catalogo, prodotto, tre policy e account, nessuna eccedenza orizzontale nelle
14 combinazioni. PASS anche Tab/focus, apertura/chiusura chat, caricamento,
citazioni con policy reale in nuova scheda e recupero da 503. Login/logout
WordPress di Mario e poi Luigi reali, su entrambe le viewport, con cookie/nonce
e config reali. Soltanto le risposte `/chat` e il 503 erano sintetici tramite
fetch nel browser: questa prova non collega il widget al backend o a un LLM.
L'isolamento backend resta coperto dall'harness #6 già documentato.

Dettagli nei report [tema #21](issue-21-results.md) e [chat #23](issue-23-results.md);
script/risultato locali in `evals/results/browser-20261105/` (ignorati da Git).
Nuovo stack arrestato e soli volumi propri eliminati; volumi preesistenti
conservati. Nessuna suite completa rieseguita il 5 novembre: dopo i 254 PASS
non è cambiata logica applicativa.

Quattro schermate acquisite il **4 novembre** e riesaminate il **5 novembre**:
[homepage desktop](screenshots/trama-home-desktop.png),
[homepage mobile](screenshots/trama-home-mobile.png),
[catalogo desktop](screenshots/trama-catalog-desktop.png),
[chat mobile](screenshots/trama-chat-mobile.png). Solo dati sintetici;
la risposta nella chat è marcata come simulata. PNG senza metadati testuali/EXIF,
integrità verificata; sette scatti intermedi conservati fuori dalla repository.
Alcune stringhe native WooCommerce restano in inglese: limite noto della demo.

I sei PNG e i sei SVG sono originali locali, con dedica CC0 limitata agli asset:
[provenienza](../seed/assets/README.md), [controllo strutturale](issue-20-results.md).
Nessun font esterno o libreria UI aggiunta. Il riesame della pubblicazione resta
soggetto ai limiti dell'[audit #20](issue-20-results.md): licenza generale ancora
da scegliere, documento di consegna interno e metadati Git da valutare prima
di renderli pubblici. Non è stata modificata la visibilità della repository.

La prova non misura la qualità, latenza o costo di un LLM reale né gli embedding
reali; non esegue un confronto live del golden dataset. Il clock del backend
non viene cambiato: i resi di dicembre hanno date esplicite e le risposte naturali
restano attese finché non si esegue una demo live autorizzata. Non verificati
deployment pubblico HTTPS/proxy/cache, screen reader o tastiera mobile fisica.
La demo originale, la sua KB e i suoi volumi sono rimasti intatti.
