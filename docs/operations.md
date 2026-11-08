# Consumi e retention della chat

Il backend resta a singolo worker. Il database SQLite configurato da
`CONVERSATION_DB_PATH` contiene conversazioni e contatori giornalieri aggregati.
Non vengono aggiunti servizi, dashboard o modifiche a ordini WooCommerce.

## Tetto aggregato

`PROVIDER_DAILY_UNIT_LIMIT=0` è il default: **il tetto è disabilitato**. Il backend
registra comunque le prenotazioni in `daily_usage(day, units)`. Impostare un intero
positivo per abilitare il tetto; giorno e reset sono in UTC. Un riavvio o un cambio
configurazione non azzera il totale dello stesso giorno. Ridurre la soglia sotto
quanto già prenotato blocca ulteriori chiamate fino al giorno successivo o a una
nuova soglia esplicita. I limiti per turno e per visitatore restano indipendenti.

Il conteggio è una prenotazione conservativa, fatta in transazione prima di ogni
tentativo provider della chat HTTP:

- Generazione: byte UTF-8 del contesto serializzato, overhead di messaggi/schema
  e massimo output configurato, come il budget già presente per turno.
- Embedding del retrieval: byte UTF-8 della query inviata, almeno un'unità.
- Ogni retry prenota nuovamente. Errori, timeout, cancellazioni o usage ignoto non
  restituiscono unità: il provider potrebbe avere eseguito la richiesta.

Se la riserva supererebbe il tetto, il provider non viene chiamato e la chat usa
il fallback esistente. Un errore nello storage interrompe la richiesta senza
procedere al provider. Le transazioni impediscono che richieste concorrenti
prenotino lo stesso residuo. Non cancellare il file/volume per resettare una quota:
contiene anche conversazioni e così si perderebbe il limite persistente.

Queste unità **non sono euro/dollari né token fatturati esatti**. La stima è pensata
per i modelli OpenAI byte-BPE attuali del progetto; cambi di provider/tokenizer
richiedono una verifica. Prezzi, sconti cache, conversioni e costi esterni non sono
inclusi. Ingestion, parsing documenti, eval e chiamate Python fuori dal lifecycle
HTTP non consumano questo tetto: restano soggetti ai loro budget e autorizzazioni.

## Metriche runtime

Gli eventi `usage` mantengono soltanto metadati allowlisted: ID di correlazione
casuali, durata, tentativi, `model_calls`, `embedding_calls`, `reserved_units`,
`input_tokens`, `output_tokens`, `missing_model_usage`, `missing_embedding_usage`.
Nessun prompt, risultato tool, indirizzo IP, owner, email o bearer viene registrato.

I token modello sono la somma dell'usage valido effettivamente ricevuto. Un valore
zero con contatori `missing_*` positivi non significa consumo nullo. Il wrapper
LangChain `aembed_query` restituisce solo vettori: l'usage embedding è quindi
sempre marcato mancante, mentre la prenotazione avviene regolarmente. Il numero
di tentativi include quelli falliti e non prova da solo una chiamata fatturata.

Gli esiti sono `answered`, `fallback`, `uncited`, `daily_limit` o `error`.
`fallback` e `uncited` riconoscono soltanto risposte deterministiche del backend;
non classificano tutte le astensioni naturali o la correttezza semantica dell'LLM.
SQLite conserva il solo aggregato di unità per giorno, non log individuali o PII.
La rotazione dei log del runtime/proxy resta configurazione dell'hosting.

## Scadenza e cancellazione

Il TTL assoluto resta **1800 secondi**. Le conversazioni scadute sono eliminate
all'avvio, all'acquisizione e ogni `CONVERSATION_PURGE_INTERVAL_SECONDS` (default
60 s), anche senza nuove chat. La disponibilità dei messaggi termina al TTL;
la pulizia su disco avviene entro il ciclo successivo se lo storage funziona.
Una conversazione occupata può mantenere il contesto in memoria fino al termine
del turno, entro i limiti della richiesta, ma non viene risalvata dopo il TTL.
Monitorare gli eventi `retention` con esito `error`: lo storage guasto può ritardare
la pulizia. Un processo fermo non può pulire il disco; lo farà alla ripartenza.

`DELETE /chat/{conversation_id}` usa lo stesso bearer o cookie guest della chat.
Da WordPress usare `DELETE /wp-json/woo-rag/v1/chat/{conversation_id}`, con cookie
nativo e `X-WP-Nonce` per utenti autenticati. La route applica gli stessi limiti
e controlli del bridge. Non inviare identità cliente o segreti nel body.
Il cookie guest ha già un path che copre la route di cancellazione.

204 indica operazione completata: la risposta è identica per ID inesistente o
altrui, che non vengono cancellati. Ripetere la cancellazione è idempotente.
401 indica sessione assente/invalida; 409 indica un turno ancora attivo della
propria conversazione. Attendere la fine del turno prima di riprovare. La
cancellazione non chiama il modello e non rimborsa consumo già prenotato.

## Backup e ripristino

Il file è creato con permessi 0600 e `secure_delete` attivo, ma non è cifrato.
Proteggere anche volume, host e copie. La pulizia SQLite non elimina copie già
esportate, snapshot del filesystem o log del provider.

Concordare con il titolare quali conversazioni, se necessarie, includere nei
backup e per quanto conservarle. Usare un backup SQLite consistente (API backup
SQLite o servizio fermo), con accesso ristretto; conservare separatamente la
conoscenza pubblica del negozio quando la chat non deve essere archiviata.
Le richieste di cancellazione devono essere gestite anche sulle copie secondo
la policy concordata. Non riaprire un restore con conversazioni già cancellate
ancora presenti: il purge automatico riconosce scadenze, non cancellazioni avvenute
dopo il backup. Analogamente, non ripristinare contatori giornalieri arretrati
senza riallinearli prima di riaprire la chat, altrimenti si riutilizza quota spesa.

Retention legale, informativa, fornitori e procedure sui backup richiedono ancora
validazione per il negozio pilota. Questi controlli tecnici non attestano conformità GDPR.
