# Issue #23 — Chat nel negozio WordPress

Verifiche del 4–5 novembre 2026, branch `feat/wordpress-demo-20-25`.

## Modifiche

Il widget esistente usa la palette Trama (`#F6F3EC`, `#182922`, `#315C49`,
`#AD593F`) e mantiene il caricamento dal footer del bridge WordPress già
montato dal Compose. Non occorre incollare script o configurare un secondo
sistema di autenticazione.

La chat ha un pulsante di chiusura, supporta Escape e restituisce il focus al
lanciatore. Apertura e completamento delle richieste gestiscono il focus senza
riaprire o rifocalizzare una chat chiusa. Il pannello non è modale: la pagina
resta navigabile da tastiera, senza overlay o focus intrappolato. Messaggi e
caricamento hanno regioni accessibili; input e controlli hanno nomi e focus
visibili. Il layout limita il pannello alla viewport, usa controlli da almeno
44 px e lascia scorrere la cronologia.

Le citazioni continuano a usare collegamenti HTTP(S) con `noopener noreferrer`,
indicazione della nuova scheda e titolo leggibile dagli screen reader. Testo
del modello e fonti restano nodi di testo. Errori temporanei, limiti di richieste,
sessioni e conversazioni scadute liberano il pulsante di invio.

Le guardie sulle risposte tardive e sui cambi di sessione restano operative.
Il bridge non è stato modificato: nessun bearer WordPress raggiunge il browser,
nessun token è salvato in localStorage.

## Verifiche

- `node wordpress/tests/widget.mjs`: PASS; controlli tastiera/focus, regioni live,
  stato attesa, doppio invio, fonti/citazioni, markup non eseguito, URL pericolosi,
  errori rete/503/429/404/409/401, login/logout, cambio cliente e login dello stesso
  account, nonce scaduto, risposta tardiva e rifocalizzazione della scheda.
- `php wordpress/tests/bridge.php`: PASS; confini di fiducia, cookie/nonce,
  identità, isolamento, scadenza, proxy e assenza di token nel browser.
- `node --check widget/chat.js` e `git diff --check`: PASS.
- `python3 evals/run_issue6_integration.py`: PASS nel progetto isolato
  `woo-issue6-0de3a0b6aed2`. `evals/widget_security.mjs` esegue 11 richieste
  attraverso l'API HTTP reale, con WooCommerce e provider sintetici. PASS anche
  persistenza dopo restart/ricreazione, isolamento, scadenza e cleanup di rete,
  container e volumi propri. Report in
  `evals/results/woo-issue6-0de3a0b6aed2/{inventory,widget}.json` (non versionati).

Il test Node usa un DOM sintetico: non costituisce una prova visuale né una
misura della qualità delle risposte di un provider reale.

## Verifica finale e limiti

Il **5 novembre 2026**, Chromium headless via CDP ha completato la prova su
WordPress/WooCommerce reali nel progetto isolato `woo-demo-21-final-20261105`,
con volumi nuovi e viewport 1440×1000 e 390×844. **PASS**: apertura e focus
nell'input, pannello nella viewport, caricamento con invio disabilitato,
citazioni HTTP(S), apertura della policy reale in una nuova scheda, recupero
da 503, Escape e ritorno al lanciatore. Le risposte `/chat` e il 503 erano
**sintetici tramite fetch nel browser**: il backend e un provider LLM non erano
collegati a questo stack. Le chiamate `/session/config` restavano reali.

Login/logout nativi WordPress di Mario e poi Luigi eseguiti tramite form
WooCommerce su entrambe le viewport: **PASS**, etichetta ospite/account coerente,
cookie/nonce reali, localStorage vuoto e nessuna vecchia risposta sintetica dopo
le navigazioni. Questo controllo non sostituisce la prova backend di isolamento
ordini dell'harness #6 o i test dei cambi di sessione senza navigazione.

Script e risultato locali: `evals/results/browser-20261105/{browser.mjs,browser-results.json}`
(ignorati da Git). La [schermata mobile](screenshots/trama-chat-mobile.png),
acquisita il 4 novembre e riesaminata il 5, dichiara la risposta simulata.
Ulteriori dettagli e pagine controllate nel [report del tema #21](issue-21-results.md).
I container e i soli volumi della nuova prova sono stati rimossi.

Nessuna chiamata a provider a pagamento è autorizzata o eseguita per questa
issue. Non sono provati screen reader, tastiera mobile fisica o qualità delle
risposte di un modello reale. La demo preesistente non viene modificata.
