# Issue #20 — audit preliminare della repository

Verifica del **4 novembre 2026**, baseline
`02c3907ad490e179255a46145ac34eef05b41b98`.

**Audit completato: nessun segreto reale o dato di clienti reali individuato
nel perimetro esaminato. Non è un via libera alla pubblicazione finale.**
Restano da riesaminare i contenuti interni indicati sotto, la scelta della licenza
e tutti gli asset/modifiche aggiunti nei task successivi. Non sono stati cambiati
visibilità GitHub, credenziali, cronologia o servizi della demo.

## Ambito e metodo

- **118 file tracciati** nella baseline e relative copie di lavoro, incluse le
  modifiche preesistenti a `README.md` e `docs/presentazione.md`.
- **48 commit, 279 blob distinti, 121 percorsi storici**, raggiungibili dalle
  **23 refs** disponibili all'inizio della verifica: branch locali e refs remote
  locali. Clone non shallow. Inclusi i file rimossi da main e quelli presenti
  soltanto in altri branch, fra cui `docs/demo-migration-results.md` e `scripts/`.
- Il reflog non aggiunge commit. `git fsck --full --unreachable --no-reflogs`
  individua altri **8 blob locali non raggiungibili**, controllati anch'essi.
- Esaminati separatamente i file ancora non tracciati `docs/consegna.md` e
  `docs/task-demo-wordpress.md`, preservandoli senza modifiche.
- Ricerca locale su contenuti e messaggi/metadati dei commit per chiavi
  OpenAI/LlamaCloud, WooCommerce, GitHub, AWS e Slack; chiavi private, JWT, URL
  con credenziali, assegnazioni di password/token e indirizzi email.
  Ricerca aggiuntiva di stringhe letterali ad alta entropia e inventario dei
  percorsi di dump, log, archivi, database, immagini, font e licenze.
- Confronto esatto, senza stamparne i valori, con le variabili sensibili presenti
  nel `.env` locale: `OPENAI_API_KEY`, `LLAMA_CLOUD_API_KEY`, `WC_CONSUMER_KEY`,
  `WC_CONSUMER_SECRET` e `SESSION_SECRET`. Nessun caricamento del file come shell
  script e nessuna chiamata ai provider.
- Revisione del contesto delle corrispondenze, del seed, delle fixture e dei
  report per distinguere dati sintetici, segreti e informazioni operative.

La scansione è stata eseguita con Python standard e comandi Git, con risultati
limitati a categoria, percorso, riga e identificatore del blob. Gitleaks e
TruffleHog non erano installati; non sono stati scaricati strumenti aggiuntivi.
Il controllo mirato non garantisce di riconoscere ogni formato di segreto o dato
personale, soprattutto se codificato, frammentato o privo di marcatori.

## Risultati

| Area | Esito ed evidenza |
| --- | --- |
| Credenziali provider e Woo | Nessun token compatibile con i pattern cercati e nessuna corrispondenza con le quattro chiavi configurate nel `.env` locale, nei file, nella cronologia o nei blob non raggiungibili. `.env` non risulta mai tracciato. |
| Sessione | Il `SESSION_SECRET` locale coincide con il placeholder pubblico di `.env.example` e `chatbot/app/config.py`. È un valore dimostrativo, non una nuova fuga di segreti; non costituisce una configurazione sicura per un sito esposto. La validazione `Settings.validate_security` lo rifiuta in production. Il file locale non è stato modificato. |
| Password demo | Credenziali fisse in `docker-compose.yml`, `seed/setup.sh`, `seed/seed.php`, Compose di integrazione e fixture. Servono a DB, amministratore e clienti sintetici della demo; non sono credenziali da riutilizzare su un negozio reale. |
| Falsi positivi | Gli URL con user/password appartengono ai test di redazione in `chatbot/tests/test_evals.py`; i segreti brevi/nominali nelle fixture sono sintetici. Nessuna chiave privata o JWT completo individuato. |
| Clienti e ordini | `seed/seed.php` costruisce due identità con dominio di esempio e tre ordini; indirizzo negozio e catalogo sono definiti dal seed. Fixture ed eval dichiarano dati sintetici. Nei contenuti Git gli indirizzi email rilevati usano soltanto `example.com`, `example.test` o `example.invalid`. Nessun dataset di clienti reali individuato. |
| Dump e log | Nessun dump SQL, database, archivio di backup, log applicativo o report JSON runtime versionato nei 121 percorsi storici. `evals/results/` e il DB conversazioni locale sono esclusi da Git. I report Markdown contengono risultati, identificatori tecnici e comandi, non payload di conversazioni o copie di `.env`. |
| Output del seed | `seed/seed.php` genera una vera chiave Woo read-only e la stampa al primo avvio tramite marker `__WC_KEYS__`. La generazione è codice, non una chiave inclusa nel repository. L'output di una nuova esecuzione va trattato come riservato e non copiato in report o issue. |
| Dati del manutentore | I metadati Git contengono tre identità email distinte, comprese identità personali; il report storico `docs/demo-migration-results.md` contiene anche un percorso assoluto di backup con username locale. Non sono dati cliente né segreti, ma diventano visibili distribuendo quelle refs. Valori non ricopiati qui. |
| Documento di consegna | `docs/consegna.md`, ancora non tracciato, dichiara come fonte un'email del corso e include informazioni organizzative e il nome di un terzo. Non è dato sintetico del negozio. Prima di includerlo in una repository pubblica, rivederne necessità e contenuto; nessuna autorizzazione alla diffusione viene dedotta da questo audit. |

Non emerge una credenziale reale esposta che richieda revoca o rotazione a causa
di questa cronologia. Prima di esporre online lo stack occorrono invece credenziali
nuove e configurazione appropriata: Compose pubblica porte host e il seed usa
password note. Pubblicare il sorgente ed esporre il negozio sono operazioni diverse.

## Asset e licenze

Nella baseline e nei percorsi storici non sono presenti immagini, font, video,
PDF, archivi di terze parti o WordPress core versionato. Il widget usa CSS e
font di sistema. `seed/products.csv` e `seed/docs/` contengono testi demo, senza
asset commerciali allegati; la titolarità dei testi non è certificabile dal solo
contenuto Git.

Il CSV campione WooCommerce citato in `docs/issue-19-results.md` viene letto dal
plugin installato nello stack isolato, non copiato nella repository. La prova
`evals/issue19_import.php` esclude immagini e file scaricabili remoti dal mapping.
Le provenienze e i checksum sono documentati nel report #19. Questo non concede
automaticamente diritti sulle immagini remote per gli asset del task successivo.

**Manca un file `LICENSE` del progetto**, anche nella cronologia esaminata;
`chatbot/pyproject.toml` non dichiara una licenza. Non ne è stata aggiunta una senza
una scelta del titolare. È una decisione ancora aperta per il riuso del codice,
non la prova di una violazione né un motivo per fermare il lavoro locale.
Le dipendenze sono elencate in `pyproject.toml`, `requirements.lock`, Dockerfile e
Compose; non sono vendorizzate. Non è stata eseguita una verifica completa delle
licenze transitive o delle immagini Docker. Per ogni nuovo asset distribuibile
occorre registrare autore/provenienza e condizioni d'uso e riesaminarlo nel task 6.

### Controllo aggiuntivo degli asset #22

Prima della chiusura dell'audit sono stati aggiunti `seed/assets/README.md`,
`products.json`, sei SVG sorgente e sei PNG. Il README dichiara illustrazioni
originali disegnate con forme vettoriali locali tramite Codex, nessun materiale
esterno e dedica CC0 1.0 limitata a questi asset; non assegna una licenza al resto
del progetto. Il mapping contiene soltanto SKU demo, nomi file, alt e categorie.

Controllo strutturale **PASS**: sei PNG da 800 × 800, complessivamente 124.359 byte,
CRC dei chunk validi e soli chunk `IHDR`, `pHYs`, `IDAT`, `IEND`; nessun chunk
testuale/EXIF. I sei SVG non contengono script, gestori di eventi, immagini
incorporate, riferimenti esterni, elementi di testo o metadata. Non è una
verifica legale della titolarità né una prova visiva della demo. Le successive
modifiche degli asset restano da ricontrollare nel task 6.

## Correzioni e verifiche

- `.gitignore`: aggiunte varianti `.env.*`/`*.env.*`, SQLite senza suffisso `3`,
  dump SQL semplici/compressi, dump generici, log e directory `backup/`/`backups/`.
  `.env.example` resta versionabile. Prima della modifica `.env.local`,
  `.env.production`, `secrets.env.bak`, dump e log non erano coperti.
- `.dockerignore`: esclusi gli stessi tipi sensibili dal contesto di build root,
  anche in sottodirectory. Il contesto backend ha già una allowlist separata in
  `chatbot/.dockerignore`.
- `.env.example`: chiarito che credenziali seed/Compose e placeholder di sessione
  sono pubblici e destinati alla demo locale; nessun valore operativo cambiato.
- Controllo assert-based tramite `git check-ignore --no-index`: **17 percorsi
  sensibili esclusi e 6 percorsi sorgente/esempio mantenuti**, compresi casi
  annidati, `.env.example`, CSV seed e lock dipendenze. **PASS**.
- `git diff --check`: **PASS**. Nessuna logica applicativa modificata; suite
  applicativa e build Docker non rieseguite per queste sole esclusioni/commenti.

Comandi di inventario riutilizzabili, senza stampare il contenuto dei segreti:

```bash
git rev-parse HEAD
git rev-parse --is-shallow-repository
git ls-files
git rev-list --all --count
git rev-list --objects --all
git rev-list --all --reflog --count
git fsck --full --unreachable --no-reflogs
git check-ignore -v .env.local secrets.env.bak backup.sql app.log
git diff --check
```

## Limiti e lavoro residuo prima della pubblicazione

Questo è l'audit iniziale della baseline, non delle modifiche concorrenti o
successive dei task 2–6. Ripeterlo sulla versione finale, inclusi immagini,
schermate, nuovi report e refs che si intende rendere accessibili.
Le refs remote sono le copie locali disponibili: non è stato effettuato un fetch
durante la scansione. Non coperti GitHub Actions/artifact remoti, issue/commenti,
release, fork, refs non presenti localmente, backup esterni e contenuti dei volumi
Docker. Il confronto privato con `.env` non è un audit di tutti i file ignorati.

Restano da valutare la diffusione del documento interno di consegna e dei
metadati identificativi già nella storia, e la licenza/provenienza degli asset
che verranno aggiunti. Nessuna riscrittura della cronologia è stata eseguita o
proposta come operazione automatica. Se un controllo successivo individua un
segreto reale, riportare solo percorso e tipo, revocare/ruotare la credenziale e
concordare separatamente l'eventuale bonifica della storia.
