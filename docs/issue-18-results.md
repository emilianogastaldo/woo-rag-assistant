# Issue #18 — login WooCommerce reale e isolamento ordini

Il widget usa il login WordPress/WooCommerce nativo, tramite My Account (fallback
`wp-login.php`). Il mu-plugin `wordpress/woo-rag-auth.php` espone il ponte
same-origin `/wp-json/woo-rag/v1/session/config` e `/wp-json/woo-rag/v1/chat`.
Ogni richiesta autenticata richiede cookie WP attuale, nonce REST valido e verifica
della sessione nativa: il logout/revoca invalida anche il replay del vecchio cookie.
Le credenziali del negozio vengono inserite solo nelle pagine native WordPress/Woo.
Il controllo segue la [cookie authentication REST nativa WordPress](https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/)
e la [verifica cookie/nonce del core](https://developer.wordpress.org/reference/functions/rest_cookie_check_errors/).

Il ponte crea un bearer `wp.` solo server-side, valido 30 secondi, con HMAC-SHA256
e `WRAG_BRIDGE_SECRET` distinto da `SESSION_SECRET`. Il backend riusa verifica
firma/scadenza e risoluzione email→customer ID WooCommerce; richiede inoltre che
l'ID risolto coincida con l'utente WP firmato. Una cache email obsoleta fallisce
quindi con 401, senza autorizzare ordini del vecchio account. Identità o ID liberamente
inviati dal browser non autorizzano nulla e sono rifiutati dal body schema.

Il proprietario della conversazione combina sessione WP firmata e customer ID.
Due login dello stesso cliente sono isolati; rinnovare l'asserzione breve nella
stessa sessione conserva invece la conversazione. Demo e ospiti mantengono i
confini preesistenti. Gli ospiti non ricevono bearer né tool ordini; il ponte
inoltra solo il cookie `wrag_guest`, riscrivendone il Path per la REST API e
impostando HttpOnly, SameSite=Lax e Secure quando WordPress è in HTTPS.

Il widget usa `X-WP-Nonce` e cookie nativi, senza token ordini in JavaScript,
localStorage o sessionStorage. Link login/logout restano nativi. Il controllo
sessione prima e dopo ogni turno, al focus e al ripristino pagina azzera la
conversazione quando cambia l'identità o scade il nonce, e scarta risposte tardive.
Cookie/nonce non più validi richiedono di ricaricare la pagina e accedere nuovamente.

## Configurazione

Il ponte è disabilitato finché `WRAG_BRIDGE_SECRET` è vuoto. Per abilitarlo:

1. Impostare un segreto casuale di almeno 32 caratteri, diverso da `SESSION_SECRET`.
   Compose lo passa solo a WordPress e backend; non viene restituito al widget.
2. Riavviare i servizi interessati. Compose monta mu-plugin e widget in WordPress;
   fuori da Compose servono gli stessi file e `WRAG_BACKEND_URL` server-side.
3. Usare utenti WordPress/WooCommerce reali e chiavi Woo REST **read-only**.
   Production richiede anche un `SESSION_SECRET` valido e rifiuta `DEMO_ENABLED=true`.

Il proxy usa una sola destinazione configurata dal server e non segue redirect.
Rifiuta body oltre 24 KB, messaggi oltre 4 KB e campi extra; limita la risposta
upstream a 64 KB e inoltra solo JSON, Retry-After numerico e il cookie ospite previsto.
Il segreto del ponte è incluso nella redazione dei dati inviati al modello.
Le firme/token restano nel traffico server→server: in produzione usare rete privata
o HTTPS e tenere il backend dietro il confine di rete previsto dal deployment.
Escludere dal page cache le pagine autenticate che contengono il nonce WP.

Il limite richieste backend continua a usare il peer IP reale: dietro questo ponte
il budget è condiviso dal processo WordPress, quindi va dimensionato per il volume
del negozio. Non vengono fidati header IP liberamente inviati dal browser.

Aggiornamento #29: questa limitazione del risultato originale è superata dalle
quote visitatore attestate e da un tetto globale distinto; vedere il
[runbook corrente](bridge-deployment.md).

## Verifica locale, 2026-11-03

Test ripetibili nel repository, senza rete/provider:

```bash
PYTHONPATH=chatbot:. OPENAI_API_KEY= ANONYMIZED_TELEMETRY=false \
  python -m pytest -q -p no:cacheprovider \
  chatbot/tests/test_wordpress_auth.py chatbot/tests/test_session.py \
  chatbot/tests/test_security.py chatbot/tests/test_api.py chatbot/tests/test_orders.py
php wordpress/tests/bridge.php
node wordpress/tests/widget.mjs
```

Il test PHP verifica i confini con funzioni WP sintetiche; il test DOM usa risposte
WP sintetiche. Non sono presentati come prove del runtime WordPress reale.
Esito: **58 test Python PASS**, test PHP e DOM **PASS**, Ruff e controlli sintassi
Python/JavaScript/PHP **PASS**.

È stato eseguito anche un test HTTP nativo in uno stack Docker temporaneo dedicato:
WordPress con WooCommerce 10.0.4, MariaDB e backend corrente, due soli utenti e due
ordini sintetici, chiave Woo read-only. La rete era `internal:true`, senza porte
pubblicate e con volumi nuovi. Nessun `.env` o dato del negozio esistente importato.
L'answer deterministico sostituiva il provider e chiamava davvero `OrderService`
e WooCommerce REST. Il driver audita l'isolamento e verifica l'ownership prima
di eliminare esclusivamente container, rete e volumi del proprio progetto.

Esiti HTTP nativi: login A/B, proprio ordine, ordine altrui non trovato, isolamento
conversazioni tra clienti e tra due login dello stesso cliente, nonce assente e
scaduto, replay cookie dopo logout, continuità guest, rifiuto email/ID browser,
demo disabilitata in production: **PASS**. Nessuna chiamata a provider esterni.

Harness e inventario del run sono conservati localmente in
`/tmp/woo-issue18-auth/`; non sono infrastruttura di deploy. Il report
`result.json` registra anche cleanup delle sole risorse create dal test.
Run finale: `woo-issue18-dd69d00b3cec`, isolamento **PASS**, cleanup **PASS**.

Non verificati: layout in browser reale e deployment pubblico HTTPS/proxy/cache.
Il test nativo usa HTTP interno; Secure del cookie è verificato dal test PHP.

## Revisione prima del push

Corretto il fallback login quando WooCommerce è attivo ma la pagina My Account
non è configurata: il link apre `wp-login.php`, invece della homepage. Il test
PHP copre sia pagina configurata sia assente; PHP e DOM sono passati nuovamente.
La suite Python completa sul lavoro integrato passa: **248 test**, con il solo
warning di deprecazione Starlette/AnyIO già noto. Lint completo passato.
