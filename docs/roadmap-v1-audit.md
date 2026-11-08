# Audit roadmap v1 single-store — 7 novembre 2026

Fonte: `CODEX_ROADMAP_WOO_RAG_ASSISTANT.md`, handoff fornito dall'utente.
Baseline applicativa `dbeab28`; esperimento MCP completato separatamente in `71f6f59`.
L'utente ha autorizzato apertura e implementazione delle issue con subagenti,
ma ha escluso nuove prove con il modello ChatGPT. Tutte le verifiche di questa
fase usano test offline o servizi locali e provider simulati.

## Matrice dei gap alla baseline

I riferimenti di riga sono quelli della baseline, non necessariamente del codice
successivo alle correzioni. «Implementato» non equivale a certificazione del pilota.

| Requisito | Stato ed evidenza | Rischio / priorità | Test presenti e prove mancanti | Issue |
| --- | --- | --- | --- | --- |
| Login WP, sessioni, ownership ordini/history | Implementato: `wordpress/woo-rag-auth.php:13,51`, `auth/session.py:91,173`, `orders.py:127,134`, `main.py:253` | P0: conservare; nessun bypass anonimo dimostrato in production corretta | `test_wordpress_auth`, `test_orders`, `test_security`, bridge PHP; resta smoke HTTPS/proxy pilota | #29 regressioni |
| Quote per visitatore dietro bridge | Parziale: `main.py:163` usa socket peer, `woo-rag-auth.php:77` inoltra tutti dal server WP | P0: quota unica condivisa blocca il negozio | Limite IP e XFF testati; mancano A/B dietro bridge, attestazione falsificata, cap globale | #29 |
| Esposizione locale / produzione | Parziale: guardie `config.py:131` già presenti, porte Compose pubblicate su tutte le interfacce | P0: development con secret pubblico non va esposto; non è un bypass production | Startup/demo testati; aggiungere loopback e runbook proxy | #29 |
| Budget e telemetria runtime | Parziale: `agent.py:314,395` budget per turno; trace usage non passato da `main.py:271` | P0/P2: manca guardia aggregata persistente | Test budget/retry per turno presenti; aggiungere riavvio, più turni, esaurimento, usage mancante e log senza PII | #34 |
| Retention e cancellazione | Parziale: `conversations.py:84,99,121` SQLite, TTL e secure-delete; purge solo startup/acquire | P0 prima del pilota: scaduti restano se sito inattivo | Persistenza/TTL testati; mancano purge periodico e cancellazione autorizzata | #34 |
| Minimizzazione dati e read-only | Implementato in parte sostanziale: `privacy.py:29`, `orders.py:78`, `observability.py:27`, GET in `woo_client.py:99` | P0: redazione non significa anonimizzazione di ogni testo libero | Test log/secret/ordini presenti; informativa, backup e policy da titolare | #34, #35 |
| Ricerca catalogo | Parziale: `catalog.py:46,60`, primi 10 + SKU/nome | P1: no budget/categoria/pagina, valuta EUR fissa | Test elenco, vuoto, malformato; aggiungere filtri, zero/prezzi mancanti, varianti, nascosti, valuta | #30 |
| Consigli regalo e schede | Assente come flusso strutturato: `agent.py:150`, `main.py:114`, `widget/chat.js:331` | P1: risposta testuale senza prodotti verificati strutturati | DOM fonti sicure già testato; aggiungere cards/XSS/turni e eval regalo sintetica | #31 |
| Ordini per data/numero pubblico | Parziale: `orders.py:121,138`, output number ma lookup id; schema int in `agent.py:129` | P1: numerazione custom e ordini vecchi non trovati | Ownership già testata; aggiungere date inclusive, bounds, number≠id, alfanumerici/ambiguità | #32 |
| Tracking e giorni reso | Parziale: `orders.py:30,60,95`, metadata demo e 30 giorni fissi | P1: non rappresenta un plugin reale e policy diversa | Completed≠delivered già testato; aggiungere mapping, assenza, anomalia, URL e policy configurata | #33 |
| Plugin distribuibile / widget configurabile | Parziale: MU bind mount e asset esterni (`docker-compose.yml:52`); `woo-rag-auth.php:8,128` usa env/percorso fisso | P2: installazione richiede asset/config manuali | Bridge/sessione/widget testati; manca ZIP, settings admin/nonce, diagnostica, lifecycle, branding | #35 |
| Sync documenti | Parziale: `ingest.py:31,65` tre slug fissi e comando manuale | P2: contenuti obsoleti o non selezionabili | Ingestion/versioning coperti; aggiungere selezione, modifica/eliminazione e job disabilitato di default | #36 |
| Versioning indice e rollback | Implementato: `rag/versions.py:218`, `ingest.py:106`, runbook deployment | P0/P2: preservare atomicità | `test_versions`, `test_deployment`; estendere senza nuova coda/datastore | #36 regressioni |
| Accessibilità widget | Parziale avanzato: focus, Escape, ARIA, loading, login, fonti | P2: mantenere durante cards/config | Test DOM presenti; screen reader/hardware reale restano da verificare | #31, #35 |
| Qualità modello reale | Non dimostrata da test fake | Non duplicare o chiamare il provider senza nuova autorizzazione | #17 esistente, fuori dalle run autorizzate ora | #17 |

## Top 5 e dipendenze

1. **#29 — Quote affidabili e rete locale sicura (M)**: elimina un blocco operativo
   condiviso senza modificare l'autorizzazione ordini. GPT-6 Astra, high.
2. **#30 — Ricerca catalogo filtrata (M)**: fondamento per budget/stock/varianti.
   GPT-6.1 Sol, high.
3. **#31 — Schede e consigli fondati (M)**: dipende da #30; contratto additivo e
   dati live del turno. GPT-6.1 Sol, high.
4. **#32 — Ordini per date e numero pubblico (M)**: indipendente dal catalogo;
   poi #33 tracking configurabile (M). GPT-6.1 Sol, high.
5. **#34 — Budget aggregato, telemetria e retention (L)**: dopo #29, separando i
   commit per responsabilità. GPT-6 Astra, high.

Completano il percorso #35 plugin/runbook (L, GPT-6.1 Sol high, review sicurezza
Astra high) dopo bridge/cards, e #36 selezione pagine/sync (M, GPT-6.1 Sol high).
Si usano worktree distinti; le modifiche condivise a schemi, config e agente
richiedono integrazione e regressioni prima del merge. Nessun SaaS, nuovo database,
operazione di scrittura LLM o sostituzione automatica REST con MCP.

## Prima issue implementabile: #29

**Scope:** attestazione server-side della quota visitatore; separazione quota
individuale e tetto globale, accesso diretto conservato; porte demo loopback.
File: bridge PHP, `main.py`, helper auth/rate limit, config/env/Compose, test e docs.

**Accettazione:** A esaurisce la propria quota senza bloccare B sotto tetto globale;
header/cookie falsificati e XFF non scelgono identità; richiesta invalida limitata;
429 e Retry-After coerenti. Regressioni su guest, A, B, token, logout e history.
Non aggiungere datastore o cambiare il contratto pubblico della chat.

## Decisioni aperte del pilota

L'utente ha confermato che **nessuna scelta è ancora stata fatta**. Le issue
implementano configurazioni e fixture, non fingono una validazione del negozio reale:

- plugin/corriere e significato dei metadata tracking;
- retention conversazioni e backup, informativa e responsabilità trattamento;
- budget operativo, valuta/timezone, policy resi e pagine autorizzate;
- categorie/varianti/catalogo rappresentativo, numerazione custom e volume ordini;
- hosting HTTPS, proxy/cache, pianificazione sync, branding.

I default demo restano compatibili. Prima del pilota validare queste decisioni e
la configurazione effettiva; una prova software non attesta conformità legale.

## Esito dell'implementazione — 9 novembre 2026

La matrice sopra conserva i gap della baseline. Gli interventi successivi coprono:

- #29: quote individuali firmate dal bridge, tetto globale e porte locali su loopback.
- #30–31: ricerca catalogo filtrata, varianti e schede provenienti dai dati del turno;
  prodotti protetti da password esclusi anche dalle risposte legacy.
- #32–33: date e numero pubblico degli ordini, tracking esplicito e resi configurabili.
- #34: riserve giornaliere persistenti, metriche senza contenuti, purge periodico e
  cancellazione autorizzata. Il cap predefinito è disabilitato; le unità non sono dollari.
- #35: ZIP del bridge con widget incluso, impostazioni admin, diagnostica senza LLM
  e [runbook di installazione](wordpress-plugin.md).
- #36: corpus selezionabile, preview senza provider, snapshot completi e timer opt-in.
  Nessun job è stato attivato e nessun indice della demo è stato rigenerato in questa fase.

Le prove di integrazione del 9 novembre usano provider sintetici e risorse Docker
separate dalla demo. Il progetto `woo-issue6-182d072c5c66` verifica auth, ordini,
isolamento delle sessioni, limiti, privacy, persistenza dopo restart/recreate e
widget DOM con HTTP reale. Il progetto `woo-issue7-ac3972eab2f9` verifica 16 casi
con 43 query, promozione/rollback, errori di ingestion, disponibilità e recupero
WordPress/Chroma. Entrambi hanno esito e cleanup PASS, senza chiamate esterne.
I report locali sono sotto `evals/results/` nel checkout delle rispettive prove;
sono generati, non dati necessari per installare il progetto.

Le prove fake non attestano pertinenza o qualità del modello reale: #17 rimane
separata e richiede nuova autorizzazione alle chiamate provider. Restano inoltre
da validare tutte le decisioni del pilota elencate sopra, il confine HTTPS/proxy
effettivo e l'accessibilità con dispositivi e screen reader reali.
