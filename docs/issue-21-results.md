# Issue #21 — tema, homepage e navigazione Trama

Verifiche del **4–5 novembre 2026**, branch `feat/wordpress-demo-20-25`.
Tema e schermate preparati il 4 novembre; nuova prova browser e revisione delle
quattro schermate finali il 5 novembre. Solo dati sintetici e ambienti isolati.

## Risultato e applicazione

Trama è un child theme locale di Twenty Twenty-Five, senza page builder o
librerie aggiuntive. Palette carta/inchiostro/bosco/terracotta, caratteri di
sistema e Georgia: nessun font remoto. Homepage statica con introduzione,
selezione di tre prodotti e invito alla chat; navigazione verso catalogo,
spedizioni, resi, FAQ e account WooCommerce nativo. Il catalogo conserva i sei
prodotti del seed e le relative immagini originali.

Il percorso di applicazione resta quello esistente:

```bash
docker compose run --rm wpcli /seed/setup.sh
```

`seed/storefront.php` configura tema e homepage una volta. Il marker impedisce
che una seconda applicazione sovrascriva titolo, homepage o personalizzazioni
estranee; WooCommerce crea soltanto le proprie pagine mancanti. La navigazione
usa gli URL delle pagine esistenti, senza aggiungere menu duplicati.
`seed/markdown.php` trasforma le tre policy in HTML leggibile, conservando testo,
significato e slug; il contenuto HTML in ingresso viene escapato.

Il tema è montato da Compose in `wp-content/themes/trama`. Widget e bridge
restano quelli esistenti; la [verifica della chat](issue-23-results.md) distingue
le risposte sintetiche dalle sessioni native WordPress.

## Verifiche eseguite

- `wordpress/tests/storefront.php` su WordPress/WooCommerce reali: **PASS**.
  Tema/parent, homepage unica, cinque destinazioni, semantica Markdown, escape
  HTML e testo delle policy preservato. Una seconda applicazione conserva
  titolo modificato e opzione estranea, senza duplicare pagine o menu.
- Due setup completi da volumi puliti, con verifiche catalogo e tema: **PASS**
  nel runner `python3 evals/run_issue19_import.py --demo-final` del 4 novembre;
  dettagli e prerequisiti nel [report #25](issue-25-results.md).
- Nuovo setup e test PHP reale del tema il **5 novembre**, nel solo progetto
  `woo-demo-21-final-20261105`, con volumi nuovi: **PASS**. Immagini locali
  `woo-issue19-wp:10.0.4`, `woo-issue19-cli:10.0.4` e MariaDB già disponibili;
  nessun download, lettura di `.env` o accesso alla demo originale.
- Chromium headless via CDP, cache disabilitata: **PASS** su desktop
  **1440×1000** e mobile **390×844**. Homepage, catalogo, singola scheda prodotto,
  spedizioni, resi, FAQ e account raggiungibili; nessuna eccedenza orizzontale
  nelle 14 combinazioni pagina/viewport, peso del testo calcolato `400`.
- Navigazione con Tab e focus visibile; apertura chat con focus nell'input,
  pannello entro la viewport, Escape e ritorno al pulsante: **PASS** su entrambe
  le viewport. La chat non intrappola il focus né impedisce lo scorrimento pagina.
- Login/logout WordPress **reali** di Mario e poi Luigi tramite form WooCommerce:
  **PASS** su entrambe le viewport, con config di sessione reale via cookie/nonce,
  etichetta ospite/account coerente, localStorage vuoto e assenza della vecchia
  risposta sintetica dopo le navigazioni. Nessuna risposta LLM reale richiesta.

I rapporti calcolati dai colori CSS sono 13,74:1 per testo inchiostro su carta,
6,87:1 per link verdi su carta, 7,62:1 per testo bianco sui pulsanti verdi e
6,95:1 per gli errori della chat. È un controllo della palette; non una
certificazione completa di accessibilità o di ogni possibile stato del tema.

Il controllo browser ad hoc è stato eseguito con
`node /tmp/woo-demo-21/browser.mjs`; script, Compose e risultato sono conservati
localmente in `evals/results/browser-20261105/`, esclusi da Git. Il risultato
registra 14 pagine/viewport e quattro gruppi di controlli PASS. Il backend della
chat non era collegato: soltanto `fetch` verso `/chat` forniva risposte e 503
sintetici; pagine, fonti, login/logout e `/session/config` erano reali.

## Schermate e limiti

Quattro PNG del **4 novembre**, riesaminati il **5 novembre**: homepage
[desktop](screenshots/trama-home-desktop.png) e
[mobile](screenshots/trama-home-mobile.png),
[catalogo desktop](screenshots/trama-catalog-desktop.png),
[chat mobile](screenshots/trama-chat-mobile.png). Le schermate sono a pagina
intera; la chat dichiara nel messaggio che la risposta è simulata. La nuova
verifica browser del 5 novembre non viene presentata come data di acquisizione
di questi PNG. Gli altri sette scatti intermedi restano soltanto in `/tmp`.

Le immagini e i contenuti sono leggibili nelle schermate riviste; su mobile
le schede della homepage sono in una colonna e l'header mantiene margine laterale.
Alcune stringhe native WooCommerce sono in inglese (`Shop`, `Add to cart`,
`Read more`): traduzione completa fuori da questa rifinitura.
Non verificati screen reader, tastiera mobile fisica, ogni browser, checkout o
un deployment pubblico. Lo stack creato per il controllo è stato arrestato e i
suoi soli volumi eliminati; i volumi preesistenti sono conservati.
