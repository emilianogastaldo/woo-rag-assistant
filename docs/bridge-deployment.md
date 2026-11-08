# Bridge WordPress: rete e quote

Il Compose di sviluppo pubblica WordPress, API e Chroma soltanto su
`127.0.0.1:8080`, `127.0.0.1:8000` e `127.0.0.1:8001`. La comunicazione interna
tra container usa ancora i nomi dei servizi. La demo con utenti e password del
seed serve per prove locali; questi binding non sono un deployment pubblico.

## Preparazione del negozio pilota

1. Usare `APP_ENV=production`, `DEMO_ENABLED=false` e due segreti casuali distinti
   di almeno 32 caratteri: `SESSION_SECRET` e `WRAG_BRIDGE_SECRET`. Il secondo va
   configurato solo sul backend e su WordPress. Non esporlo in JS, HTML o log.
   Le guardie production esistenti rifiutano demo e secret di sessione predefiniti.
2. Conservare API e Chroma su rete privata o loopback, senza pubblicarle dal proxy
   del negozio. Esporre solo WordPress via HTTPS. Impostare `WRAG_BACKEND_URL`
   verso la destinazione privata; tra host distinti proteggere il trasporto con
   HTTPS o una rete privata fidata. Usare chiavi WooCommerce con soli permessi read.
3. Usare un solo worker backend, senza `--reload`; mantenere
   `--no-proxy-headers`. Se il proxy termina HTTPS per WP, configurare correttamente
   il rilevamento HTTPS nativo e i cookie Secure. Escludere dalla cache pagine
   autenticate e route `/wp-json/woo-rag/v1/`, che contengono nonce o dati privati.
4. Se WordPress è dietro un proxy, configurare il web server per ricavare
   `REMOTE_ADDR` soltanto da proxy esplicitamente fidati. Rimuovere/sovrascrivere
   gli header IP ricevuti dal pubblico al confine. Il plugin non interpreta
   `X-Forwarded-For`: senza questa configurazione tutti gli ospiti del proxy
   condividono una quota. Limitare inoltre dimensioni/tempo del body e traffico
   delle route REST al web server: gli errori rifiutati da WP prima del proxy
   non raggiungono il limiter FastAPI.
5. Dimensionare le quote dal traffico previsto. `RATE_LIMIT_REQUESTS=20` limita
   ogni account autenticato, ogni IP ospite o peer diretto;
   `RATE_LIMIT_GLOBAL_REQUESTS=200` limita l'intero backend. Entrambi usano
   `RATE_LIMIT_WINDOW_SECONDS=60`. Il tetto globale include anche richieste
   rifiutate e resta intenzionalmente condiviso. Non è un budget monetario.

Il bridge genera `X-WRAG-Visitor` lato server: contiene una chiave opaca HMAC
e scade dopo 30 secondi. Identità account e ospite sono separate. Il cookie
guest non seleziona la quota; cancellarlo non elude il limite per IP. L'attestazione
non autorizza ordini e non sostituisce le verifiche cookie/nonce/bearer esistenti.
Il backend accetta la quota individuale soltanto dopo verifica firma e scadenza.
Un header falsificato viene rifiutato e conta nella quota del peer diretto.

Gli ospiti dietro lo stesso NAT condividono la quota; gli account restano distinti.
Quote e contatori sono in memoria e si azzerano al riavvio. Prima di più worker
servirebbe uno store condiviso. Le finestre fisse possono ammettere due burst
vicini al cambio finestra. Il limite globale contiene comunque il traffico di
ciascuna finestra; non promette protezione completa da DDoS o consumo mensile.

## Verifiche prima dell'apertura

In ambiente non produttivo, con dipendenze sintetiche, verificare guest FAQ,
guest ordine, A ordine A e A ordine B; poi logout, nonce scaduto e riuso history
di un altro account. Esaurire la quota A: B deve poter continuare finché il tetto
globale non è raggiunto. Verificare `429` e `Retry-After`, compreso il passaggio
dal bridge. Gli header quota/IP scelti dal browser non devono cambiare identità.

Dal confine esterno verificare che API e Chroma non siano raggiungibili, che il
negozio usi HTTPS e che risposte private/nonce non siano serviti da cache condivise.
Le prove automatizzate in `test_wordpress_auth.py` e `wordpress/tests/bridge.php`
usano solo fake locali; non certificano firewall, proxy o cache del negozio pilota.
