# Aggiornamento WooCommerce e prova MCP

## Versioni verificate il 7 novembre 2026

Il registro ufficiale WordPress.org restituisce **WooCommerce 11.2.2** e
**MCP Adapter 0.7.1** come versioni stabili. La documentazione WooCommerce descrive
anche la transizione della 11.3: non è stata usata una versione anticipata per
inseguire la documentazione.

- [WooCommerce](https://wordpress.org/plugins/woocommerce/)
- [MCP Adapter](https://wordpress.org/plugins/mcp-adapter/)
- [Integrazione ufficiale](https://developer.woocommerce.com/docs/features/mcp/)
- [Transizione prevista in WooCommerce 11.3](https://developer.woocommerce.com/2026/10/21/woocommerce-11-3-mcp/)

Il seed installa WooCommerce 11.2.2; l'immagine di integrazione verifica il checksum
SHA-256 `a4746183efd951de5837396aad119f7cf508f06cb699ccb590a01cada4c44932`.
Il ponte `wordpress/woo-rag-auth.php` è codice del progetto, non un plugin da
aggiornare dal registro. Non sono richiesti altri plugin esterni per la demo base.
MCP è una prova opzionale, non una dipendenza della chat REST corrente.

## Verifica dell'aggiornamento

`python3 evals/run_issue19_import.py --demo-final` è passato nel progetto isolato
`woo-issue19-b07fd905b76e`: seed ripetibile, sei prodotti e tre policy, tema Trama,
12 chunk, importazione CSV, resi e cleanup. Il provider era simulato; nessuna
chiamata OpenAI. La correzione dell'elenco catalogo ha superato 259 test Python,
lint e una domanda reale nella chat prima dell'aggiornamento WooCommerce.

Per aggiornare una demo già popolata non rieseguire il seed (riscrive stock e
contenuti sintetici). Conservare prima una copia coerente di database e file,
aggiornare il plugin alla versione fissata ed eseguire `wp wc update` tramite
WP-CLI; confrontare i dati prima/dopo. Un rollback deve ripristinare insieme i
file del plugin e il database precedenti, non soltanto il plugin.

La demo locale è stata aggiornata il 7 novembre: tutte le 30 migrazioni database
WooCommerce completate, versione database 11.2.2. Inventari prima/dopo identici
per prodotti, stock, immagini associate, ordini, utenti, pagine, tema e permessi
API. Configurazione precedente conservata in
`env/upgrade-woo1122/demo-local.before.yml`, ignorata da Git, insieme ai volumi
originali scollegati. Le copie aggiornate hanno suffisso `-woo1122`.
