# Task per preparare WordPress e la repository pubblica

Ogni sezione può essere copiata in una issue e assegnata separatamente.
Questi task sono una preparazione interna della demo, non requisiti aggiuntivi
di Boolean. Non comprendono pubblicazione del sito o cambio di visibilità GitHub.

## 1. Verificare la repository prima di renderla pubblica

**Obiettivo:** individuare ciò che non deve essere pubblicato, anche nella
cronologia Git.

**Lavoro:**
- Controllare file tracciati e cronologia per credenziali, dati personali reali,
  dump, log e report contenenti informazioni riservate.
- Verificare `.gitignore`, `.env.example`, dati sintetici e diritti di utilizzo
  degli asset; distinguere le password dimostrative dai segreti reali.
- Correggere esclusioni ed esempi quando necessario. Riportare eventuali segreti
  solo tramite percorso e tipo, senza ricopiarli nel report.
- Se emergono segreti reali, indicare revoca/rotazione necessaria; concordare
  separatamente eventuale riscrittura della cronologia.

**Completato quando:** esiste un report con ambito controllato, metodo, risultati,
limiti e impedimenti alla pubblicazione. Non dichiarare la repository pronta se
restano esposizioni irrisolte. Non cambiare la visibilità GitHub in questo task.

**Dipendenze:** nessuna; ripetere il controllo sulle modifiche finali nel task 6.

## 2. Curare tema, homepage e navigazione del negozio demo

**Obiettivo:** dare al negozio un aspetto coerente e adatto alla presentazione.

**Lavoro:**
- Ispezionare prima il WordPress in esecuzione e il tema attivo.
- Definire un nome fittizio, una palette e una tipografia coerenti con il catalogo.
- Riutilizzare il tema e le funzioni WordPress/WooCommerce disponibili quando
  sufficienti; evitare page builder e dipendenze non necessarie.
- Preparare homepage con introduzione, prodotti in evidenza e invito a usare
  l'assistente; navigazione verso negozio, spedizioni, resi, FAQ e account.
- Rendere leggibili le pagine informative: il seed attuale salva direttamente
  testo Markdown nel contenuto WordPress. Preservarne significato e URL.
- Versionare asset e configurazione, rendendo l'allestimento ripetibile tramite
  il percorso di setup esistente, senza affidarsi a modifiche manuali nel database.

**Completato quando:** homepage, catalogo, scheda prodotto e pagine informative
sono leggibili su desktop e mobile, con contrasto adeguato, focus visibile e
navigazione da tastiera. Un secondo setup non duplica pagine o menu e non azzera
personalizzazioni estranee alla demo. Documentare il comando di applicazione.

**File di partenza:** `seed/setup.sh`, `seed/seed.php`, `seed/docs/`,
`docker-compose.yml`, eventuali nuovi asset del tema in `wordpress/`.

**Dipendenze:** nessuna; coordinare categorie e immagini con il task 3.

## 3. Aggiungere immagini e categorie ai prodotti del seed

**Obiettivo:** rendere il catalogo visivamente completo senza aumentarne
inutilmente il numero di prodotti.

**Lavoro:**
- Creare o reperire immagini coerenti con i prodotti esistenti, distribuibili
  nella repository; registrarne provenienza e condizioni d'uso.
- Salvare gli asset nel progetto, ottimizzarne dimensioni e peso e fornire
  testi alternativi appropriati.
- Assegnare categorie semplici e coerenti al catalogo.
- Estendere il seed per importare media e assegnazioni in modo idempotente.
  Preservare SKU, prezzi, disponibilità e descrizioni usati dagli scenari esistenti.
- Verificare gli effetti sull'ingestion: nuovi contenuti o metadati non devono
  cambiare silenziosamente le aspettative degli eval.

**Completato quando:** ogni prodotto ha un'immagine pertinente e una categoria;
due esecuzioni del seed non duplicano media, categorie o prodotti. Aggiungere
una verifica mirata di queste proprietà e controllare visivamente il catalogo.

**File di partenza:** `seed/products.csv`, `seed/seed.php`, nuovi asset in `seed/`.

**Dipendenze:** concordare la direzione visiva con il task 2; eseguire in sequenza
le modifiche condivise a `seed/seed.php`.

## 4. Integrare e rifinire la chat nel negozio

**Obiettivo:** permettere una demo dell'assistente direttamente da WordPress,
con un'esperienza coerente sulle pagine del negozio.

**Lavoro:**
- Verificare prima il widget e il ponte di autenticazione esistenti e riusarli.
- Rendere l'inclusione della chat riproducibile, senza incollare script a mano.
- Curare apertura, chiusura, messaggi, fonti, caricamento ed errori, mantenendo
  utilizzabili navigazione e contenuti del negozio anche su schermi piccoli.
- Verificare ospite, login, logout e cambio cliente senza alterare i controlli
  di accesso; mantenere i token sensibili fuori da localStorage.
- Verificare tastiera, focus e accessibilità dei controlli e dei messaggi di stato.

**Completato quando:** il widget funziona nel negozio su desktop e mobile;
ospiti e clienti vedono i comportamenti previsti, le fonti sono apribili e
logout/cambio cliente non espongono la conversazione precedente. Eseguire i test
pertinenti e una prova nel browser; indicare se il provider è reale o simulato.

**File di partenza:** `widget/chat.js`, `wordpress/woo-rag-auth.php`,
`wordpress/tests/`, `docker-compose.yml`.

**Dipendenze:** task 2 per la rifinitura visiva finale.

## 5. Preparare scenari di reso dimostrabili alla data della presentazione

**Obiettivo:** mostrare sia un reso entro i termini sia un reso fuori termine.
La consegna campione attuale è fissata al 22 giugno 2026.

**Lavoro:**
- Conservare gli ordini esistenti e le aspettative dei test che li utilizzano.
- Aggiungere il minimo scenario sintetico necessario, con data di consegna
  verificata e una data di riferimento esplicita per la demo.
- Rendere la preparazione idempotente: un nuovo avvio non deve spostare le date
  né creare ordini duplicati. Documentare come preparare una nuova prova se serve.
- Mantenere il caso senza consegna verificata: il bot deve astenersi dal
  determinare la scadenza usando soltanto la data di completamento dell'ordine.
- Aggiornare le istruzioni demo con ID effettivi, domande e risposte attese.

**Completato quando:** una verifica mirata copre entro termine, fuori termine,
confine della finestra e consegna assente. Il seed ripetuto conserva date e
numero di ordini. Le istruzioni specificano per quale data gli esempi sono validi.

**File di partenza:** `seed/seed.php`, test esistenti dei resi,
`README.md`, `docs/presentazione.md`.

**Dipendenze:** nessuna funzionale; evitare modifiche contemporanee al seed con
i task 2 e 3.

## 6. Verificare la demo completa e aggiornare la documentazione

**Obiettivo:** consentire a un docente di riprodurre il progetto dalla repository.

**Lavoro:**
- Provare il setup da checkout e volumi puliti in un ambiente isolato, senza
  cancellare o modificare la demo esistente.
- Ripetere il seed e verificare assenza di duplicati o perdita di dati.
- Eseguire i controlli pertinenti e provare nel browser catalogo, pagine,
  autenticazione, chat, citazioni e scenari di reso.
- Se cambiano i contenuti indicizzati, ricostruire la knowledge base della prova
  e verificare le risposte; rispettare le autorizzazioni per chiamate e costi esterni.
- Aggiornare README e traccia della presentazione con istruzioni e schermate
  effettive, indicando versione, data e limiti delle verifiche.
- Ricontrollare i nuovi asset e file per pubblicazione e licenze; distinguere
  credenziali locali dimostrative dalla configurazione di un sito esposto online.

**Completato quando:** il report documenta setup riproducibile, verifiche eseguite,
risultati e problemi residui. Le schermate usano soltanto dati sintetici; nessuna
prova simulata viene presentata come misura della qualità di un provider reale.

**Dipendenze:** task 1–5.

## Ordine suggerito

1. Audit iniziale (1).
2. Aspetto e catalogo (2, poi 3), coordinando le modifiche al seed.
3. Chat integrata (4) e scenari ordini (5).
4. Verifica completa e documentazione finale (6).

La pubblicazione della repository resta un'azione successiva, dopo la risoluzione
degli eventuali impedimenti emersi nell'audit.
