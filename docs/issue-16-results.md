# Issue #16 — persistenza dopo riavvio Docker

Verifica del 3 novembre 2026: **PASS**.

## Provenienza e riproduzione

Base `6eca6c1c3d6ddbe08708d706bf41a71102f94b17`, con modifiche locali
all’harness (working tree dirty), nessuna modifica al codice applicativo.
Run `woo-issue6-09737724c95e`; report JSON locali in
`evals/results/woo-issue6-09737724c95e/` (gitignored).

- SHA-256 harness: `6c5423136dc8fa9cdf26e555e42aad1044348a7a3930c3403248ae12414918f3`.
- SHA-256 applicazione: `259b1ba8482ac4af522347f7d3ad3187d9fa0d4ced2f819215d6923290a0aa20`.
- Immagine API: `sha256:20790280c4d27bcb73e50f4c42694ecca77e6e090bc0344275c9c57d5d8e20d5`.

Comando: `python3 evals/run_issue6_integration.py`.
L’harness riusa immagini locali, monta il codice corrente in sola lettura e crea
un volume SQLite dedicato con un database distinto per ciascuna API. Un file
`compose.env` contiene solo le quattro variabili sintetiche del run: la versione
Compose locale non riceveva le variabili ereditate con `--env-file /dev/null`.
Nessuna lettura del `.env` applicativo da parte dell’harness.

## Esiti

| Verifica | Esito |
| --- | --- |
| Controlli HTTP preesistenti: auth, ordini, privacy, cache, TTL, capacità, rate limit | PASS |
| History cliente e ospite dopo restart e force-recreate con stesso volume | PASS |
| Rifiuto di altro cliente, altra sessione dello stesso cliente e ospite estraneo | PASS |
| Conversazione scaduta rifiutata dopo restart e force-recreate | PASS |
| Database invariato allo switch; owner e scadenza assoluta invariati anche dopo follow-up | PASS |
| Limite di quattro turni conservato attraverso entrambi gli switch; quinto turno rifiutato | PASS |
| ID container conservato al restart e cambiato alla ricreazione | PASS |
| Widget in DOM minimale Node con HTTP reale, 11 richieste chat | PASS |
| Log prima e dopo ricreazione privi dei valori sensibili sintetici cercati | PASS |
| Cleanup di container, rete e due volumi appartenenti solo al run | PASS |

Lint dei due script e `git diff --check`: PASS. I cinque test offline di
`chatbot/tests/test_conversation_persistence.py` erano passati nella stessa
attività (10,30 s, ambiente Python locale; rete bloccata dalla suite).

La prima run Docker era fallita sul rate limit: la finestra di tre secondi
rendeva il test dipendente dalla velocità di esecuzione. La fixture ora usa
30 secondi con la stessa quota e attende il `Retry-After` restituito dall’API.
Anche la pulizia della run fallita `woo-issue6-9dce83ec385d` è passata.

## Limiti

Zero chiamate a provider esterni e zero costi API. Provider Woo/OpenAI sintetici,
Chroma e HTTP reali su rete interna senza porte pubblicate; nessun dato o volume
della demo modificato. Non è una prova browser, di login WooCommerce reale,
di qualità LLM o di deployment multi-worker. La prova usa sorgente montato,
non una nuova build standalone. La suite completa non è stata rieseguita.

## Regressione sul lavoro integrato #16–19

Run `woo-issue6-1b2076c13426`: **PASS** anche dopo l'integrazione del ponte WP.
Controlli healthy/restarted/recreated, widget, redazione log e cleanup **PASS**.
Applicazione SHA-256: `97f7c5a6316ec1a6df56f77cb45bdc78783d8342b204a8662e61220dfa562bd1`.
Harness invariato rispetto alla run sopra. Suite completa offline: **248 test PASS**,
lint completo PASS. Restano esclusi provider reali e browser visuale.
