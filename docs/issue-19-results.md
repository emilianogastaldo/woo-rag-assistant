# Issue #19 — dati di test e CSV ufficiale WooCommerce

## Decisione

Mantenere `seed/products.csv` + `seed/seed.php` come dataset predefinito. Aggiungere
il CSV ufficiale solo in uno store di prova separato quando servono varianti,
sconti, prodotti raggruppati, esterni o scaricabili. Non sostituire il seed e non
importare il campione nello store demo già utilizzato dalle altre prove.

Il seed locale copre le domande italiane, lo stock numerico e l'esaurito, insieme
a clienti, ordini e policy coerenti. Il campione ufficiale amplia il catalogo, ma
non contiene quei dati operativi e non basta per testare ordini o resi.

| Aspetto | Seed locale | Campione ufficiale 10.0.4 |
|---|---|---|
| Formato | 6 colonne interne in minuscolo, lette da `seed.php` | 51 colonne dello schema nativo WooCommerce |
| Catalogo | 6 prodotti semplici, descrizioni italiane | 25 righe: 18 prodotti principali + 7 variazioni |
| Tipi principali | 6 simple | 12 simple, 2 simple virtual/downloadable, 2 variable, 1 grouped, 1 external |
| Prezzi | EUR, da 12,90 a 89,90; nessuno sconto | prezzi regolari e scontati; parent senza prezzo diretto nel CSV |
| Stock | gestione attiva, quantità da 0 a 100; `SHOES-RUN-X` esaurito | tutti `In stock?=1`, `Stock` vuoto; nessuna quantità numerica |
| Identità | SKU interni stabili (`TSHIRT-BIO`, ecc.) | 25 SKU distinti, parent collegati tramite SKU |
| Contenuti aggiuntivi | 3 pagine, 2 clienti, 3 ordini, consegna verificata | nessun cliente, ordine o pagina policy/FAQ |

Il CSV ufficiale **non va copiato sopra `seed/products.csv`**: il parser interno
si aspetta `sku,name,regular_price,stock_quantity,short_description,description`
e crea esclusivamente prodotti semplici. Usare l'importer nativo per il formato
ufficiale, evitando un secondo parser o un plugin aggiuntivo.

## Provenienza e versione

- Plugin fissato a **WooCommerce 10.0.4**, come `seed/setup.sh` e `evals/Dockerfile.issue7`.
- File distribuito nel plugin: `wp-content/plugins/woocommerce/sample-data/sample_products.csv`.
- [Sorgente versionata del CSV](https://github.com/woocommerce/woocommerce/blob/10.0.4/plugins/woocommerce/sample-data/sample_products.csv).
- SHA-256 del CSV: `1d6f48b6f33fdc04615a9722c59f8cb8a07ed62e94a1dc3237313983d1884721`.
- L'archivio plugin usato dal Dockerfile è verificato con SHA-256
  `002b3cb8b1fcacf9836367a1ae617c87d6def0c33d16b8a79a4f81dad9894429`.
- [Guida ufficiale ai dati campione](https://woocommerce.com/document/importing-woocommerce-sample-data/)
  e [schema/importer CSV](https://woocommerce.com/document/product-csv-importer-exporter/).

Le guide online possono descrivere versioni successive: questa verifica usa
l'importer realmente incluso in **10.0.4**, non il comportamento corrente di trunk.

## Procedura ripetibile senza toccare la demo

Prerequisiti: Docker con Compose, Python 3 e immagini locali. Dalla radice del
repository preparare una volta le immagini con il Dockerfile già esistente:

```bash
docker build -f evals/Dockerfile.issue7 --target wordpress -t woo-issue19-wp:10.0.4 .
docker build -f evals/Dockerfile.issue7 --target cli -t woo-issue19-cli:10.0.4 .
docker pull mariadb@sha256:efb4959ef2c835cd735dbc388eb9ad6aab0c78dd64febcd51bc17481111890c4
python3 evals/run_issue19_import.py
```

La preparazione può scaricare immagini e plugin; l'esecuzione usa solo immagini
locali. In questa analisi sono state riutilizzate le build locali della prova #7,
senza rebuild o download Docker. Lo script risolve i tag a ID immutabili e li
registra nel report.

Ogni esecuzione genera un progetto `woo-issue19-<uuid>`, rete `internal: true`,
due volumi nuovi (`db`, `wp`), nessuna porta pubblicata. Non legge `.env`, non usa
il compose demo, non avvia servizi AI, non monta volumi preesistenti. Monta in
sola lettura `seed/` e il test PHP. Verifica l'assenza dei nomi delle risorse prima
di avviare; prima del cleanup verifica le etichette di proprietà dei volumi.
Il `finally` rimuove solo il progetto appena creato, anche quando fallisce il test.

La prova:

1. Installa WordPress sintetico e **attiva il plugin locale** prima di richiamare
   `seed/setup.sh`: su uno store nuovo lo script seed altrimenti tenta il download
   di WooCommerce da WordPress.org. Non è stato modificato il percorso demo.
2. Esegue `setup.sh` e poi nuovamente `seed.php`, controllando 6 prodotti,
   stock ripristinato, 3 pagine, 2 clienti, 3 ordini e la consegna verificata.
3. Verifica versione e checksum del campione; usa il mapping del controller nativo.
4. Esclude dal mapping **ID**, **Images** e **Download 1/2 name/URL**. Gli ID sono
   dello store sorgente; immagini e file scaricabili dipendono da host esterni. Parent/variazioni restano collegati
   tramite SKU, con i parent presenti prima delle variazioni nel file originale.
5. Importa una volta in creazione, ripete in creazione, poi in aggiornamento;
   controlla conteggi, duplicati, parent/figli, prezzi regolari/scontati e stock.
6. Salva `evals/results/woo-issue19-<uuid>/report.json` e rimuove container/rete/volumi.

Per una prova manuale nella UI di uno **store usa e getta** con WooCommerce 10.0.4:
Prodotti → Importa → caricare il CSV del plugin; controllare la mappatura, impostare
ID, Images e Download 1/2 name/URL su “Non importare”, lasciare disattivato “Aggiorna prodotti esistenti”
al primo caricamento. Verificare 18 schede principali e 7 variazioni (3 V-Neck,
4 Hoodie), per esempio Beanie 20/18 e Hoodie Red 45/42. Il test automatizzato
esercita la stessa classe importer; l'interfaccia browser non è stata provata.

## SKU, ripetizioni e ripristino

- Il seed fa upsert per SKU e **riscrive** descrizioni, prezzo e quantità; non
  duplica prodotti. Pagine: slug; clienti: email. Gli ordini hanno un gate globale
  `wrag_seed_orders_done`: non vengono ricreati al secondo giro. Anche la chiave
  REST ha un gate; il primo giro genera una chiave sintetica nel DB temporaneo,
  il cui output viene scartato dal runner.
- L'importer ufficiale in creazione salta uno SKU già presente. In aggiornamento
  (`update_existing=true`) aggiorna i prodotti esistenti; non è un upsert dei nuovi
  SKU mancanti. Nel test, 25 righe saltate al secondo giro e 25 aggiornate al terzo.
- Non trattare SKU con maiuscole diverse come prodotti diversi: mantenere gli SKU
  originali, verificare unicità prima di importare e non mapparne arbitrariamente gli ID.
- Eseguire di nuovo il seed **non annulla** l'import ufficiale: non cancella SKU
  aggiuntivi. Il ripristino ripetibile è eliminare solo il progetto temporaneo e
  crearne uno nuovo. In un ambiente persistente servirebbe prima un backup di DB
  e uploads; questa analisi non ha effettuato import o ripristini della demo.
- Le 25 righe del campione contengono URL immagini su
  `woocommercecore.mystagingwebsite.com`. Nel test non vengono importate e nessuna
  chiamata HTTP è ammessa durante l'import. Non servono immagini per il RAG testuale.
  I campi Download 1/2 name/URL vengono esclusi: Album e Single restano virtuali
  e scaricabili, ma senza file associati. I link prodotto esterno restano semplici
  dati dimostrativi, non asset da scaricare o eseguire.

### Limite emerso sui download del campione

Una prova con CSV originale, escludendo solo ID e immagini, ha rifiutato **Album**
e **Single**: il file remoto su `demo.woothemes.com` non appartiene alle directory
approvate per i download nello store nuovo. L'importer ha restituito due errori
`woocommerce_product_importer_error`. Il CSV ufficiale non è quindi importabile
integralmente senza preparare anche gli asset e la relativa autorizzazione.

Per testare catalogo/prezzi senza dipendenze esterne, la procedura sopra esclude
quei campi. Non disabilita il controllo delle directory autorizzate. Per un test
specifico di vendita download occorrono file locali sintetici in una directory
approvata e una prova separata del download autenticato: fuori dallo scopo #19.

## Dati per ordini, consegna, FAQ e RAG

Clienti e ordini restano in `seed/seed.php`, separati dal CSV catalogo. Sono solo
identità sintetiche `example.com`: Mario ha un ordine completato e uno processing;
Luigi un ordine processing, utile per verificare il rifiuto di accesso all'ordine
altrui. Non usare ID ordine fissati: WooCommerce li assegna nello store creato.

Il completamento amministrativo non prova la consegna: l'ordine completato di Mario
ha `_wrag_delivery_date=2026-06-22T14:30:00Z`; gli altri non hanno conferma. La policy
prevede 30 giorni, con scadenza **22/07/2026**. Le date sono fisse: alla data della
prova il termine è scaduto. Per testare un reso ancora valido serve una fixture
con data di consegna recente o un clock controllato, non un'affermazione inventata.
Il seed non crea richieste RMA, rimborsi reali o un'integrazione corriere.

`seed/docs/{spedizioni,resi,faq}.md` crea le pagine pubblicate con slug
`spedizioni`, `resi-e-rimborsi`, `domande-frequenti`. L'ingestion in
`chatbot/app/ingest.py` legge solo prodotti pubblicati con descrizione e quelle
tre pagine; stock/prezzi e ordini sono dati da consultare con i tool live.
Clienti, email, ordini e metadati di consegna **non entrano nel corpus RAG**.

Il campione aggiunge 18 prodotti principali descritti; le 7 variazioni non sono
indicizzate singolarmente dall'attuale ingestion, che non percorre l'endpoint
`products/<id>/variations`. Anche il tool catalogo attuale consulta `products`:
l'import corretto non dimostra che il chatbot sappia selezionare una variazione
o riportarne il prezzo. La prova #19 non amplia questa funzionalità.

Dopo ogni modifica alle descrizioni/policy occorre una nuova ingestion nello
**stesso ambiente di test**, con Chroma e stato versioni dedicati; controllare
prima i documenti sorgenti, poi costruire una candidata e promuoverla dopo la
validazione secondo [deployment ingestion](ingestion-deployment.md).
Il seed da solo non aggiorna Chroma. Il comando applicativo è
`python -m app.ingest build --candidate-only`, seguito da status/promote della
collezione esatta. Richiede il relativo ambiente applicativo: non è eseguito
dal runner #19, che non fornisce provider né vector store. Per una prova senza
costi riusare l'upstream sintetico e l'isolamento del runner #7; non avviare
l'ingestion con configurazione demo o credenziali provider reali per questa verifica.

Domande e risultati verificabili dai dati (non un benchmark LLM eseguito):

| Domanda | Fonte e risultato atteso |
|---|---|
| «Le Scarpe Running Aero X sono disponibili?» | tool catalogo, `SHOES-RUN-X`: esaurite, 0 pezzi, 89,90 EUR |
| «Quanto costa la maglietta bio?» | tool catalogo, `TSHIRT-BIO`: 19,90 EUR; dopo il secondo seed 42 pezzi |
| «La borraccia mantiene le bevande calde?» | descrizione `BOTTLE-THERMO`: fino a 12 ore; conoscenza statica RAG |
| «Quanto costa Beanie?» nello store esteso | `woo-beanie`: prezzo corrente 18, regolare 20; quantità non dichiarata |
| «Quanto costa Hoodie Red?» | variazione `woo-hoodie-red`: 42, regolare 45; verifica importer/API variazioni, supporto chatbot non provato |
| «Quando consegnate e quando la spedizione è gratis?» | pagina spedizioni: 2–4 giorni lavorativi, gratuita da 49 EUR |
| «Posso rendere il mio ordine completato?» come Mario | tool ordini del cliente autenticato + policy: consegna 22/06/2026, scadenza 22/07/2026 |
| «Quando scade il reso dell'ordine processing?» | nessuna consegna verificata: non calcolare dalla data ordine/completamento |
| «Mostrami l'ordine di Luigi» come Mario | controllo proprietà ordine: rifiuto, nessuna divulgazione |

## Verifiche e limiti

Run finale `woo-issue19-dd1b53fdb6cf`: **PASS**, cleanup **PASS**.
Prima importazione: 18 prodotti e 7 variazioni; seconda: 25 righe saltate;
terza: 25 aggiornate. Totale finale: 24 prodotti principali (6 seed + 18 campione)
e 7 variazioni, zero tentativi HTTP esterni durante l'import.

Il report locale registra tre import nativi, due passaggi seed, immagini immutabili,
zero tentativi HTTP durante l'import e cleanup. I report sotto `evals/results/`
sono ignorati da Git: l'evidenza è rigenerabile con il comando sopra.

Nessuna modifica ai file seed, a `.env`, allo store demo o ai suoi volumi. Non sono
state inviate richieste a provider AI né eseguiti embedding/risposte LLM. Non sono
stati provati download immagini, checkout, UI browser, email o pagamenti reali.
