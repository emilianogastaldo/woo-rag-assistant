# Knowledge base del singolo negozio

La selezione del corpus è esplicita in `.env`:

```dotenv
KNOWLEDGE_PAGE_SLUGS=chi-siamo,pagamenti,spedizioni,resi-e-rimborsi,domande-frequenti
KNOWLEDGE_INCLUDE_PRODUCTS=true
KNOWLEDGE_MAX_PAGES=20
```

Solo slug di pagine pubblicate e senza password; duplicati eliminati. I prodotti
pubblicati con visibilità `visible` o `catalog` sono inclusi se abilitati. Non si
indicizzano ordini/clienti. Prezzi e stock restano fonte live dei tool, non campi
aggiunti ai documenti; anche le descrizioni vanno curate per non incorporare dati
personali o valori dinamici obsoleti. Nessuna selezione automatica di tutte le
pagine. Slug vuoto significa solo prodotti; entrambi disabilitati è errore.

`KNOWLEDGE_MAX_PAGES` limita separatamente prodotti e pagine a blocchi di 100.
Se il corpus supera il limite, la run fallisce senza promuovere uno snapshot
troncato. Verificare il dimensionamento prima di pianificare; aumentare il limite
esplicitamente (massimo 100). Una pagina selezionata ma eliminata/non pubblicata
scompare dal nuovo snapshot. Anche uno slug inesistente non produce documenti:
controllare la preview per evitare errori di configurazione. Un corpus interamente
vuoto fallisce preservando l'attiva, richiedendo intervento dell'operatore.

## Anteprima e aggiornamento manuale

```bash
docker compose build ingest
docker compose run --rm ingest preview
docker compose run --rm ingest build
```

`preview` legge WooCommerce/WordPress e mostra conteggi e URL pubblici, senza
chiamare embedding o modello, scrivere Chroma o promuovere versioni. `build` invia
il corpus al provider embedding configurato: richiede autorizzazione a corpus e
costi. Eseguire su un sito autorizzato, non usare il seed demo su un negozio reale.
Modifiche/eliminazioni producono uno snapshot nuovo, validato prima della promozione.
Il lock admin copre fetch, build e promozione: una seconda run concorrente fallisce
esplicitamente; non avvia una seconda indicizzazione. Le run identiche riusano la
versione. Errori fetch/embedding/validation lasciano l'attiva invariata.

## Pianificazione opzionale su Linux/systemd

I file in `deploy/systemd/` **non vengono installati né attivati automaticamente**.
Dopo aver autorizzato corpus e provider, un amministratore adatta `WorkingDirectory`
e il percorso di Docker alla propria installazione (esempio `/opt/woo-rag-assistant`),
verifica che database, WP e Chroma siano avviati e che `.env` sia protetto, quindi
installa le due unità in `/etc/systemd/system/` e abilita il timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now woo-rag-sync.timer
systemctl list-timers woo-rag-sync.timer
journalctl -u woo-rag-sync.service
```

La cadenza di esempio è oraria, senza recupero delle esecuzioni saltate. Cambiarla
in base al negozio e al budget; nessun webhook o worker aggiuntivo è necessario.
Monitorare gli exit code e `/ready`: un job fallito può lasciare una versione
precedente ancora pronta ma non aggiornata. I log del servizio vanno protetti e
redatti prima di condividerli; non inoltrare eccezioni grezze/credenziali in report.

Per sospendere: `sudo systemctl disable --now woo-rag-sync.timer` (attendere anche
l'eventuale run in corso). Per recupero usare `status`, `rollback --target NOME`
e la [procedura esistente](ingestion-deployment.md), preservando insieme Chroma e
`knowledge_state`. Nessuna collection attiva va cancellata per preparare una sync.

Le prove automatiche usano provider fake e HTTP simulato: non avviano il timer e
non inviano il corpus a OpenAI. Hosting, cadenza e corpus del pilota restano da validare.
