# Aggiornamento WordPress 7.1.4 / PHP 8.5

Le immagini in `docker-compose.yml` e `evals/Dockerfile.issue7` sono fissate a
WordPress **7.1.4**, PHP **8.5.12** (Apache e WP-CLI), tramite digest immutabili.
WooCommerce resta **10.0.4**: non è stato necessario aggiornarlo per gli scenari
della demo verificati. Non è una certificazione per qualsiasi estensione WooCommerce.

## Installazione nuova

Seguire l'[avvio nel README](../README.md#avvio). Il volume vuoto riceve il core
della nuova immagine. Non servono immagini personalizzate dell'autore.

## Installazione esistente

Il core WordPress è persistito in `wp_data`: cambiare l'immagine aggiorna PHP,
ma non sostituisce automaticamente i file del sito già presenti nel volume.
Prima di migrare:

1. Registrare versioni e inventario di prodotti, ordini, utenti, media e tema.
2. Fermare backend, WordPress e database; copiare insieme i volumi `wp_data` e
   `db_data` a servizi fermi. Conservare anche la configurazione precedente.
3. Applicare l'aggiornamento del core sulle copie, preservando `wp-config.php` e
   `wp-content` (plugin, temi e upload). Aggiornare anche eventuali override locali
   delle immagini: altrimenti possono prevalere sul Compose del repository.
4. Avviare database e WordPress sulle copie con le nuove immagini, poi eseguire
   `docker compose run --rm wpcli wp core update-db`.
5. Confrontare gli inventari, verificare pagine, login e API, poi avviare il backend.

Non rieseguire il seed per migrare: riscriverebbe stock e descrizioni dei prodotti
demo. Non eliminare i volumi originali. Per il rollback fermare i servizi e
ripristinare **insieme** immagini, configurazione e coppia originale di volumi;
le modifiche apportate al sito dopo la migrazione non saranno presenti negli originali.

## Verifiche

Il 6 novembre 2026 sono passati:

- build dei target `wordpress` e `cli` di `evals/Dockerfile.issue7`;
- `python3 evals/run_issue19_import.py --demo-final`, progetto isolato
  `woo-issue19-8ec65333a4cd`, inclusa rimozione delle sole risorse del test;
- catalogo e seed ripetibile, tema Trama, importazione CSV, fixture resi,
  ingestion di sei prodotti e tre policy in 12 chunk, con provider simulato;
- `wordpress/tests/bridge.php` eseguito con PHP 8.5: permessi e isolamento del ponte.

I comandi per ricostruire le immagini del runner sono nel
[report demo](issue-25-results.md#procedura-ripetibile-dal-sorgente).
Queste prove non richiedono credito OpenAI e non misurano la qualità del modello reale.

Il 7 novembre 2026 la demo locale è stata migrata sulle copie dei volumi:
versioni effettive **WordPress 7.1.4 / PHP 8.5.12**; inventari prima/dopo identici
per prodotti, stock, immagini associate, ordini, numero utenti, pagine, tema e
permessi delle chiavi API. Verificati via HTTP homepage, sei prodotti, tre policy,
configurazione ospite, login nativo di Mario e `/health` del backend. Porte ancora
limitate a `127.0.0.1`. I volumi originali sono conservati; la configurazione locale
precedente è in `env/upgrade-wp714/demo-local.before.yml` (ignorata da Git).

Alla verifica iniziale l’indicizzazione era bloccata dal credito API esaurito.
Il 7 novembre, dopo la sostituzione della chiave, è stata completata l’ingestion
dei sei prodotti e delle tre policy. `/ready` è passato a `ready`; una domanda
reale tramite il ponte WordPress sul costo della spedizione ha restituito 4,90 €
sotto 49 €, gratuita da 49 €, con citazione della pagina Spedizioni.
È uno smoke test, non la valutazione live completa. La chiave non è pubblicata.
