# Issue #5 — Robustezza agente ed error handling

Data: 20/09/2026. Base: `main` a `f01e8be`. Branch:
`fix/issue-5-tool-error-handling`.

## Perimetro e policy

Il loop ora classifica validazione, timeout, HTTP 4xx/5xx/429, risposte malformate,
indisponibilità Chroma/provider, tool sconosciuti e budget. I failure previsti sono
output tool redatti; errori di programmazione non sono catturati genericamente.
Il fallback HTTP non contiene stack trace o dettagli upstream.

Il budget per richiesta conta insieme retry tecnici e retry di retrieval della #4.
La configurazione locale di ciascuna operazione non moltiplica i tentativi: ogni
retry deve anche ottenere una quota dal limite globale. I retry SDK OpenAI sono
zero e solo letture vengono ripetute.

## Prove

- Baseline main: `issue-5-before.json`, schema agent v2, 30 casi × 3 ripetizioni,
  PASS (90/90). Il report è gitignored.
- Suite offline: lint, pytest e confronto agent sono eseguiti con `eval-offline`,
  rete disabilitata e credenziali vuote. Ruff PASS; pytest PASS (167 test, un warning
  di deprecazione Starlette/AnyIO). Dopo la correzione del risveglio anticipato del
  timer, i 19 test di robustezza sono nuovamente PASS.
- Confronto `issue-5-after.json --baseline issue-5-before.json`: PASS, 90/90,
  nessuna regressione rilevata dal comparatore. Schema 2, golden e hash fixture
  invariati; nessuna incompatibilità aggirata. Qualità/routing/citazioni restano 1,0.
- Integrazione locale: `python3 evals/run_issue5_integration.py`, progetto riuscito
  `woo-issue5-a147935014c0`, collection `issue5-a147935014c0`. Fasi `healthy`,
  `chroma-down`, `recovered`: PASS. Il timeout Woo con due tentativi è durato
  0,417 s. Retry-After 0,1 s: 0,118 s; Retry-After 10 s contro deadline 1,5 s:
  1,505 s complessivi, una sola richiesta. Cleanup verificato volume/rete/container: PASS.
- Il percorso attraversa HTTP FastAPI, client OpenAI-compatible/Woo reali e Chroma
  1.0.0 reale. Copre 429 con `Retry-After`, 4xx senza retry, 5xx, timeout, JSON
  malformato, retry modello, fonti, assenza risultati, guasto Chroma senza fonti
  obsolete e recupero dopo riavvio. Due richieste Woo normali hanno riusato una
  singola connessione client.
- Scoping HTTP PASS: ospite senza chiamate ordini, cliente autenticato vede il
  proprio ordine, ordine altrui restituisce lo stesso non-trovato. Dopo riavvio
  Chroma il corpus viene sostituito mantenendo il numero di record: soltanto il
  nuovo chunk è citato. Log JSON dell'API correlati e senza segreti: PASS.

Comandi di verifica:

```bash
docker compose run --rm --no-deps eval-offline ruff check . /evals --config /app/pyproject.toml
docker compose run --rm --no-deps eval-offline pytest -q
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --repeats 3 --baseline /evals/results/issue-5-before.json \
  --output /evals/results/issue-5-after.json
python3 evals/run_issue5_integration.py
```

La revisione ha corretto il percorso SDK sincrono che poteva continuare dopo il
timeout e un caso limite del timer Retry-After rilevato dall'harness (run
`82835f81e61a`, FAIL, risorse eliminate). I run precedenti PASS non sono usati come
prova della versione finale: l'inventario finale conserva hash app/fixture e digest
immagini. Il campo commit degli inventari indica la base prima dei commit; gli hash
identificano il codice effettivamente eseguito.

## Limiti della prova

Live OpenAI esterno: NON ESEGUITO, manca consenso e non serve a provocare failure
già riprodotti localmente. Browser: NON ESEGUITO (nessuna modifica widget). Mock e
adapter non certificano qualità di routing/generazione o fatturazione OpenAI.
Chiamate provider esterne, token provider reali e costo API del lavoro: zero.
I token riportati dal provider locale sono sintetici e non una misura economica.
Il limite operativo è di tentativi/tempo e 512 token output per generazione;
non è un limite monetario. Le richieste ricevute dal provider possono essere
fatturate anche dopo timeout del client. Il reader assume Chroma REST v2,
tenant/database predefiniti e collection coseno creata dall'ingestion.

I report dell'integrazione sono in `evals/results/woo-issue5-a147935014c0/` e sono
gitignored. Il live esterno non è necessario per i failure, che devono restare
simulati. Un eventuale smoke sintetico del percorso provider reale rimane separato
e richiede consenso esplicito, limite chiamate/costo e tariffe aggiornate.
