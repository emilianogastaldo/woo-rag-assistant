# Plugin WordPress installabile

Il pacchetto contiene lo stesso bridge `wordpress/woo-rag-auth.php` usato dalla demo
MU e il widget canonico `widget/chat.js`. Richiede WordPress 6.8+, PHP 8.2+ e un
backend Woo RAG configurato separatamente. Le prove native usano WordPress 7.1.4,
PHP 8.5 e immagini fissate per digest; non attestano tutte le versioni precedenti.

## Build e controlli offline

Dalla root:

```bash
python3 scripts/build_wordpress_plugin.py
python3 -m unittest discover -s scripts -p 'test_build_wordpress_plugin.py'
php wordpress/tests/plugin.php
node wordpress/tests/widget.mjs
bash scripts/test_wordpress_plugin.sh
```

Il file `dist/woo-rag-assistant.zip` ha layout `woo-rag-assistant/`, timestamp e
permessi ZIP fissi e contiene soltanto bridge, pannello admin, widget e readme.
Il test verifica due build identiche e il contenuto rispetto ai sorgenti canonici;
la ripetibilità byte per byte presuppone la stessa implementazione Python/zlib.
La CI pubblica lo ZIP come artifact dopo i controlli PHP, DOM e packaging.

Il runner Docker crea un WordPress e un database effimeri senza porte host,
credenziali o seed del negozio, installa lo ZIP e verifica attivazione, login nativo,
route, asset, capability, URL, disattivazione, riattivazione e uninstall. Intercetta
l'HTTP in WordPress con risposte sintetiche: nessuna richiesta al provider o al
negozio reale. Rimuove soltanto container, rete e volume del proprio progetto.

## Installare su un negozio esistente

1. Su staging eseguire backup di database WordPress, plugin attuale e configurazione
   server; conservare versione precedente e ZIP candidato. Effettuare separatamente
   backup protetto dei dati backend e applicare la policy di retention ai backup.
   Non eseguire `seed/setup.sh` né sostituire contenuti, utenti o catalogo reali.
2. Preparare backend production, credenziali WooCommerce read-only, budget,
   retention e indice documenti secondo [bridge-deployment.md](bridge-deployment.md),
   [operations.md](operations.md) e [ingestion-deployment.md](ingestion-deployment.md).
   Il plugin non installa il backend e non avvia ingestion o chiamate al modello.
3. In **Plugin → Aggiungi plugin → Carica plugin**, caricare lo ZIP e attivarlo.
   Se esiste il vecchio MU bridge, rimuoverlo durante il passaggio insieme al vecchio
   tag widget manuale: finché il MU è presente, prevale e la copia regolare non
   registra route o widget aggiuntivi. Il vecchio MU demo e il suo asset separato
   continuano a funzionare senza migrazione automatica.
4. Aprire **Impostazioni → Woo RAG** con un amministratore. Salvare URL backend e
   secret condiviso di almeno 32 caratteri. Il campo password è sempre vuoto:
   lasciarlo vuoto conserva il valore precedente. Il secret è solo lato server,
   conservato nelle opzioni WP se inserito qui: proteggere database e backup.
   Non è una chiave API del modello; quelle rimangono sul backend.
5. Un URL salvato deve essere HTTPS pubblico senza credenziali, query o frammenti;
   WordPress lo verifica anche al momento della richiesta e non segue redirect.
   Per backend locale/privato configurare `WRAG_BACKEND_URL` nell'ambiente **PHP**,
   insieme a `WRAG_BRIDGE_SECRET`: prevalgono sui valori salvati, senza essere
   copiati nel modulo. Solo questa configurazione server fidata consente HTTP e
   reti private. Fra host distinti usare HTTPS o una rete privata fidata.
6. Scegliere titolo, colore esadecimale e posizione sinistra/destra. Il widget
   conserva navigazione da tastiera, focus e dimensioni responsive; usa testo
   nero/bianco per mantenere contrasto sul colore scelto. Il titolo rimane testo.
7. **Verifica backend** esegue soltanto `GET /ready`, con timeout 5 secondi e risposta
   limitata. Non invia secret, credenziali o domande e non mostra payload upstream.
   «Pronto» indica readiness del backend, non qualità del modello o correttezza
   delle policy del negozio. Salvataggio e diagnostica richiedono capability admin
   e nonce WordPress. Le opzioni non sono esposte nella REST API pubblica.
8. Servire il negozio esclusivamente via HTTPS. Configurare correttamente TLS
   terminato al proxy, cookie Secure e IP client da proxy fidati. Escludere dalla
   cache le pagine con nonce e `/wp-json/woo-rag/v1/`; invalidare la cache del widget
   dopo un aggiornamento. Tenere backend/Chroma privati. Verificare regole cache,
   firewall, cookie e redirect dal confine esterno prima del pilota.

Su staging verificare ospite FAQ/ordine negato, account A ordine A/ordine B negato,
logout e sessione scaduta, quote separate, schede prodotto e errori rete. I test
DOM coprono tastiera, focus, fonti e schede sicure; screen reader, dispositivi reali,
proxy/cache e qualità delle risposte reali richiedono prove dedicate autorizzate.

## Disattivazione, aggiornamento e rollback

Attivazione e disattivazione non creano cron, non cambiano dati WooCommerce e non
contattano il backend. La disattivazione elimina widget e route alla richiesta
successiva; un MU bridge ancora presente resta attivo finché viene rimosso.
Configurazione e conversazioni backend restano conservate anche eliminando il
plugin. Per rimuovere esplicitamente la sola configurazione, dopo backup:
`wp option delete wrag_options`. La cancellazione delle conversazioni è separata
e segue ownership e retention del backend.

Per aggiornare, provare prima lo ZIP su staging e conservare il pacchetto precedente.
Per rollback disattivare e sostituire la directory plugin con la copia precedente,
riattivare e svuotare la cache asset/pagine; ripristinare i valori server precedenti
se cambiati. Non servono migrazioni del database WP. Non ripristinare automaticamente
vecchi backup contenenti conversazioni già cancellate; usare la policy concordata.

Prima del pilota definire hosting/proxy, branding, informativa e ruoli trattamento,
retention e backup, budget operativo, valuta/timezone, pagine autorizzate, corrieri,
metadata tracking, resi e numerazione ordini. Queste sono decisioni del negozio;
il pacchetto e i test sintetici non costituiscono una validazione legale o del
modello e non autorizzano un deploy sul negozio reale.
