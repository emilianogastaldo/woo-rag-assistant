# Issue #22 — immagini e categorie del catalogo

Verifica del 4 novembre 2026, branch `feat/wordpress-demo-20-25`.

## Risultato

I sei SKU esistenti hanno un PNG originale, testo alternativo e categoria:
Abbigliamento (maglietta, felpa, cappellino), Scarpe (Aero X), Accessori
(zaino, borraccia). Asset e provenienza CC0 sono documentati in
`seed/assets/README.md`; `products.json` contiene le associazioni. Nessun asset
esterno, dipendenza aggiunta o abilitazione degli upload SVG.

Il percorso di setup resta `docker compose run --rm wpcli /seed/setup.sh`.
`seed.php` carica `catalog.php`, riusa gli attachment tramite metadato stabile
`_wrag_seed_asset` e i termini tramite slug. Importa solo i PNG locali con le
funzioni media native WordPress. Assegna immagine principale e alt; conserva le
categorie personalizzate e rimuove soltanto la categoria predefinita quando
assegna quella del catalogo. Non modifica galleria o immagini estranee.

## Verifica eseguita

Solo ambiente sintetico isolato `/tmp/woo-demo-21/compose.json`, progetto
`woo-demo-21`, WordPress su `http://127.0.0.1:18080`. Nessun accesso alla demo
originale o ai provider AI. WordPress/WooCommerce dalle immagini locali
`woo-issue19-wp:10.0.4` e `woo-issue19-cli:10.0.4`.

```bash
docker compose -f /tmp/woo-demo-21/compose.json -p woo-demo-21 run --rm cli \
  sh -c 'wp eval-file /seed/seed.php && wp eval-file /seed/tests/catalog.php && wp eval-file /seed/seed.php && wp eval-file /seed/tests/catalog.php'
```

Entrambe le esecuzioni hanno superato la verifica PHP reale. Le snapshot JSON
sono identiche: prodotti ID 10–15, rispettive immagini ID 28–33; categorie
Abbigliamento ID 16, Scarpe ID 17, Accessori ID 18. Totali invariati: 6 prodotti,
7 media (6 del catalogo e 1 preesistente), 4 categorie (3 del catalogo e la
categoria predefinita, non assegnata ai sei prodotti).

`seed/tests/catalog.php` verifica:

- SKU, nome, prezzo, descrizioni e stock coerenti con `products.csv`, stato
  esaurito compreso;
- associazione immagine, metadato di riconoscimento, testo alternativo, MIME PNG,
  dimensioni 800×800 e hash del file importato uguale all'originale locale;
- categoria attesa e assenza della categoria predefinita sui sei prodotti;
- conservazione di una categoria aggiuntiva dopo due applicazioni del helper,
  con ripristino e rimozione del solo termine temporaneo creato dal test;
- snapshot degli ID e dei conteggi da confrontare dopo i due seed.

Lint PHP di `seed.php`, `catalog.php` e del test superato. Mapping dei sei SKU,
intestazioni PNG, dimensioni e peso verificati localmente. Anteprima dei sei
asset esaminata visivamente prima dell'importazione (11–30 KiB per PNG).

## Ingestion e limiti

Lettura di `chatbot/app/ingest.py::fetch_product_docs`: indicizza nome e
short/long description, con permalink, titolo, tipo e SKU come metadati. Non
legge immagini o categorie. Il CSV resta invariato e il test conferma gli stessi
contenuti prodotto, quindi questa modifica non richiede variazioni alle
aspettative degli eval. Non eseguiti embedding, reingestion o chiamate esterne.

La verifica integrata successiva ha rieseguito il setup da volumi puliti:
stessi ID e conteggi già fra primo e secondo setup, con tutti gli invarianti
CSV preservati. Ha anche ricostruito la KB delle tre policy HTML e sei prodotti
con provider sintetici: 12 chunk, doppia ingestion idempotente e citazioni valide.
Comando riproducibile da un clone: `python3 evals/run_issue19_import.py --demo-final`;
prerequisiti ed esito nel [report finale #25](issue-25-results.md).

Il controllo browser del 5 novembre del catalogo WordPress e della scheda
prodotto, su desktop e mobile, è PASS ed è documentato nella [verifica del tema #21](issue-21-results.md).
L'anteprima locale degli asset descritta sopra resta una verifica distinta.
