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

## Ripetere la prova MCP isolata

Prerequisiti: immagini e comandi del [report demo](issue-25-results.md#procedura-ripetibile-dal-sorgente).
Costruire inoltre il solo target opzionale:

```bash
docker build -f evals/Dockerfile.issue7 --target wordpress-mcp -t woo-mcp-wp:11.2.2-0.7.1 .
python3 evals/run_issue19_import.py --mcp
```

La build scarica MCP Adapter 0.7.1 verificando SHA-256
`719d81aa1250615acfd8256f0acc8c13f1712f1ae398c3d5883c8b166024fe9b`.
Il runner riusa la procedura demo su rete interna, senza porte pubblicate,
credenziali reali o volumi della demo. Attiva l'adapter solo nel database temporaneo,
crea un utente dedicato e usa il comando WP-CLI `mcp-adapter serve` come server
STDIO, con messaggi JSON-RPC MCP. Il client di prova usa la libreria standard Python:
non aggiunge dipendenze al backend. Il report non contiene password.

Il percorso è `initialize` (revisione `2025-11-25`), `tools/list`, discovery delle
abilities, lettura dello schema, `tools/call` tramite `mcp-adapter-execute-ability`.
Non è una chiamata PHP diretta all'ability né una simulazione del protocollo.
Il modello non partecipa alla prova: MCP collega un client agli strumenti, mentre
la scelta dello strumento da parte dell'LLM è un passaggio distinto.

La prova del 7 novembre 2026 è **PASS** nel progetto temporaneo
`woo-issue19-a6c1ec6e103b`; report locale:
`evals/results/woo-issue19-a6c1ec6e103b/report.json` (directory ignorata da Git).
Sono passati inizializzazione e lista dei tre meta-tool dell'adapter, discovery e
schema della query, confronto di ID/nome/prezzo/stock dei sei prodotti con
WooCommerce, filtro SKU, contenuto e metadati della seconda pagina. Il server ha
rifiutato modifica prodotto, lettura ordini e query catalogo da un utente privo
del permesso richiesto, restituendo `Permission denied`. Ha rifiutato inoltre
`per_page=101` con il limite esplicito 1–100. Il client verifica gli errori MCP
`isError` anche quando il contenuto è testo semplice, anziché JSON.
Il catalogo confrontato è rimasto invariato dopo i tentativi; isolamento e cleanup
sono passati. Anche seed ripetuto, storefront, ingestione con 12 chunk, import CSV
e resi del runner completo sono passati. Zero chiamate a provider esterni;
l'ingestione usa esclusivamente il provider sintetico nella rete interna.

Questa prova copre il trasporto STDIO e l'identità selezionata da WP-CLI.
Non verifica trasporto HTTP, OAuth/application password, connessione a ChatGPT,
scelta degli strumenti da parte di un modello o qualità delle sue risposte.

## Vincoli per un'eventuale integrazione nella chat

La query catalogo ufficiale controlla `read_private_products`. Il profilo di prova
ha soltanto questo permesso e `read`: non è amministratore e non può modificare
prodotti o leggere ordini. Il permesso consente comunque la lettura di prodotti
privati: nella prova si richiede esplicitamente `status=publish`, ma questo filtro
nel client **non costituisce un confine di autorizzazione** per un agente autonomo.
Prima di collegare la chat pubblica occorre un'ability/server che imponga sul
server i soli prodotti pubblicati e visibili, con un elenco esplicito di operazioni
consentite. Non esporre all'agente un esecutore generico con credenziali amministrative.

Per gli ordini il server deve ricavare il cliente dalla sessione autenticata e
applicare lo stesso isolamento del backend attuale. MCP non sostituisce questi
controlli, né il RAG delle policy o la validazione delle citazioni. La chat corrente
continua a usare i tool REST verificati; questo esperimento serve a decidere e
progettare una successiva integrazione circoscritta.
