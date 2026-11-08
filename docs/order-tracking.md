# Tracking e policy resi del singolo negozio (#33)

L'adapter legge soltanto `meta_data` degli ordini già autorizzati dal servizio.
Non chiama corrieri, non modifica ordini e non presume che un plugin sia installato.
Il negozio pilota non ha ancora scelto plugin/corriere o concordato il mapping:
nessuna integrazione reale è certificata da questi test.

Il default mantiene la demo: `_wrag_delivery_date` è la data sintetica di consegna,
la scadenza è 30 giorni dopo. `completed` e `date_completed` rimangono dati
amministrativi e non certificano consegna, spedizione o anomalie.

| Variabile | Contratto |
| --- | --- |
| `TRACKING_DELIVERY_DATE_META_KEY` | Chiave della data di consegna confermata dell'intero ordine; default demo `_wrag_delivery_date`, vuoto la disabilita. |
| `TRACKING_STATUS_META_KEY` | Chiave dello stato spedizione, vuota per default. |
| `TRACKING_STATUS_MAP` | Oggetto JSON da valori esatti del metadata a `created`, `accepted`, `in_transit`, `delivered`, `exception`; default `{}`. Nessun valore è interpretato automaticamente. |
| `TRACKING_URL_META_KEY` | Chiave del link tracking effettivamente disponibile, vuota per default. Non si costruiscono link da un numero di tracking. |
| `ORDER_RETURN_WINDOW_DAYS` | Intero 0–3650; default demo 30. **0 disabilita** il calcolo della scadenza. |
| `WC_ORDER_TIMEZONE` | Calendario IANA del negozio, default demo `Europe/Rome`; usato anche per date di consegna e scadenze. |

Le chiavi corrispondono esattamente a metadata con valori stringa piatti. Array,
oggetti nidificati, timestamp numerici o strutture multi-collo di plugin non scelti
non sono supportati automaticamente. Il mapping non è un sistema di trasformazione
di payload arbitrari: quando si sceglierà il plugin si verificherà la struttura
reale e, se necessario, si aggiungerà un normalizzatore mirato con fixture anonimizzate.

Sul pilota, prima di concordare fonti e policy, partire con:

```dotenv
TRACKING_DELIVERY_DATE_META_KEY=
TRACKING_STATUS_META_KEY=
TRACKING_URL_META_KEY=
TRACKING_STATUS_MAP={}
ORDER_RETURN_WINDOW_DAYS=0
```

Esempio **esclusivamente sintetico**, non mapping di un vendor:

```dotenv
TRACKING_DELIVERY_DATE_META_KEY=_fixture_delivered
TRACKING_STATUS_META_KEY=_fixture_state
TRACKING_URL_META_KEY=_fixture_url
TRACKING_STATUS_MAP={"label":"created","collected":"accepted","moving":"in_transit","confirmed":"delivered","incident":"exception"}
ORDER_RETURN_WINDOW_DAYS=14
```

Gli stati significano spedizione creata, presa in carico, transito, consegnata e
anomalia attestata dai metadata configurati. Il tool non diagnostica il motivo
dell'anomalia e non interpreta uno stato sconosciuto come ritardo o problema.
Una data verificata può certificare la consegna senza metadata di stato; uno stato
`delivered` senza data non permette di calcolare il reso. Un link senza stato è
segnalato come tracking incompleto. Duplicati, valori non leggibili o stato
contraddittorio rendono esplicita l'incompletezza; una data in conflitto con lo
stato non viene usata per la scadenza. Gli stati e le date sono quelli dei metadata
letti: il tool non verifica aggiornamento o veridicità presso il corriere.

I link devono essere HTTPS sulla porta standard, senza credenziali, spazi,
controlli, backslash o hostname malformati. IP privati/locali e nomi locali sono
rifiutati. Il tool non risolve DNS e non certifica l'affiliazione del dominio al
corriere: il titolare deve verificare la fonte del link nel mapping pilota.
Un link respinto non viene mostrato e non implica un'anomalia di spedizione.

Le date ISO con offset sono convertite al calendario del negozio; quelle senza
offset sono interpretate nello stesso calendario. La durata configurata è in
giorni di calendario dalla consegna confermata. Il titolare deve allinearla alla
policy indicizzata: giorni lavorativi, eccezioni, resi parziali e date di singoli
colli richiedono una regola concordata separatamente. Se il calcolo è disabilitato,
il tool e il prompt vietano di derivare una scadenza personalizzata dalla sola data.

Prima di abilitare il pilota occorre verificare quali campi il plugin restituisce
via REST con chiave read-only, il loro significato (soprattutto consegna completa
e anomalia), la timezone, i link e la policy con il titolare. Provare dati presenti,
assenti, incompleti, sconosciuti e contraddittori e verificare nuovamente l'ownership
con due clienti. Queste decisioni e la validazione del plugin reale restano esterne
alla prova sintetica; nessuna retention è stata decisa qui.

Verifica nel worktree: 337 test Python offline passati, inclusi fallback,
anomalie esplicite, stato sconosciuto, dati contraddittori, URL pericolosi, policy
diversa/disabilitata e isolamento clienti. Ruff 0.16.8 e configurazione Compose
(default e mapping/opt-out sintetici, senza `.env`) passati. La valutazione
`python -m evals.run_agent_eval --extra-golden /evals/issue17.jsonl` ha passato
34 casi deterministici, conservando lookup legacy e follow-up; non misura la
qualità di risposte di un modello reale. Tutte le prove Docker usavano rete
disabilitata e sorgenti montati in sola lettura.
