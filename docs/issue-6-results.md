# Issue #6 — evidenze di verifica

Data: 2026-09-20. Implementazione verificata: `9b0f1900e821842cee035c7edeac716b77b3c74b`.
Baseline: `main` pulita `618ac9781ca8514686d64fc6d56cb89cc5701eef`, dopo merge #5.
Il commit successivo aggiunge soltanto questo report.

## Esiti per livello

| Livello | Esito | Evidenza / limite |
| --- | --- | --- |
| Ruff offline | PASS | `All checks passed` |
| Pytest offline | PASS | 195 test, 9,17 s; un warning di deprecazione Starlette/AnyIO |
| Eval agente offline | PASS | 30 casi × 3 ripetizioni, 90/90, confronto schema v2 compatibile |
| API reali Docker | PASS | Guest/A/B, history, auth, scadenze, capienza, rate limit, ordini e privacy |
| Processi demo/production | PASS | Login assente quando disabilitato; startup fallito con secret vuoto/predefinito |
| Riavvio / processi separati | PASS | Stesso token + ID non recupera history su altro processo o dopo restart |
| Widget DOM + HTTP reale | PASS | 11 richieste chat; contratto, login/logout, scadenze, isolamento e risposta tardiva |
| Browser / verifica visuale | NON ESEGUITO | DOM minimale Node; non prova layout né policy cookie/CORS applicate da un browser |
| Modello/provider esterno | NON ESEGUITO | Nessun consenso live; nessuna API a pagamento chiamata |
| Cleanup risorse test | PASS | Assenza verificata di container, rete e volume del progetto dedicato |

L'autorizzazione è provata nel codice e via HTTP; nessun criterio di sicurezza
usa il rifiuto di un LLM come prova. La delimitazione di contenuti malevoli è
verificata al confine HTTP del provider sintetico, non come robustezza semantica
di un modello reale. Non viene dichiarata una verifica browser end-to-end.

## Comandi eseguiti

Docker disponibile nel contesto `default`, server 29.8.0. Verificati
`docker context show`, `docker info`, `docker compose ls -a`; nessun cambio contesto.
Il socket inizialmente bloccato dal sandbox è stato autorizzato. Le immagini
necessarie erano già disponibili: nessun download di dipendenze.

```bash
# Prima delle modifiche, su main aggiornata (report con commit=null: provenienza sopra)
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --repeats 3 --output /evals/results/issue-6-before.json

# Sul commit di implementazione
docker compose run --rm --no-deps eval-offline ruff check . /evals --config /app/pyproject.toml
docker compose run --rm --no-deps eval-offline pytest -q
docker compose run --rm --no-deps eval-offline python -m evals.run_agent_eval \
  --repeats 3 --commit 9b0f190 --output /evals/results/issue-6-after.json \
  --baseline /evals/results/issue-6-before.json
python3 evals/run_issue6_integration.py
```

Il servizio offline usa `network_mode: none`, nessuna credenziale e nessun servizio
dipendente; pytest mantiene il blocco DNS/socket. Gli altri report sono gitignored.

## Confronto eval

Schema **2**, dataset e fixture dell'agente invariati. Il report finale aggiunge
soltanto i parametri del budget modello nei metadati di configurazione: non cambia
schema, casi o scoring e `--baseline` passa senza aggirare controlli.
Default: semantic, k=4, distanza 0,6, nessuna riformulazione; 4 passi, 12 tentativi,
2 retry, deadline 30 s. Contesto 32000 byte, budget 100000 unità conservative,
output 512 token, output tool 12000 byte.

| Metrica | Prima | Dopo |
| --- | --- | --- |
| Routing/tool/risposta/pass rate | 1,0 | 1,0 |
| Astensione corretta (21) | 1,0 | 1,0 |
| Hit@k, MRR, precisione/recall citazioni (66) | 1,0 | 1,0 |
| Validità citazioni (90) | 1,0 | 1,0 |
| Chiamate modello simulate | 171 | 171 |
| Dispatch tool / retrieval / Woo simulati | 87 / 69 / 15 | 87 / 69 / 15 |
| Latenza media offline | 1,1225 ms | 1,8194 ms |

Zero regressioni funzionali nei 30 confronti per caso. La latenza media aumenta
circa 0,697 ms (+62%): include nuove verifiche/serializzazioni ed è una misura
locale breve, con le verifiche finali eseguite in parallelo; non prova prestazioni
production. Token input/output ed embedding esterni: zero, perché modello/script
locali; nessun costo API. Questi risultati non misurano la qualità di un LLM reale.

Digest dataset: `e5e68591c88685ca050dd2ae6b6f8bcc5eec8993afbeef872944760423c95b92`.
Digest fixture agente: `d400270685948820bcdf9306c7e5f87556e380bede899646c3b1131405f80a34`.
Digest implementazione eval prima/dopo:
`f1befa2fe505556583d532e54b149ab7d3cc61f4f2d1786995a86e2d7746e243` /
`5e3aab1ebcecad94996d5ba71128ad37177be99ba6c178d311a5c6452197b301`.

## Integrazione isolata

Run finale: `woo-issue6-709c6dca138d`; collection `issue6-709c6dca138d`.
Report: `evals/results/woo-issue6-709c6dca138d/{inventory,healthy,restarted,widget}.json`.
Rete interna, nessuna porta pubblicata, volume nuovo e mount controllati; `.env`
non ereditato, solo credenziali/dati sintetici. Nessun comando di arresto, restart,
cleanup o reindicizzazione indirizzato al progetto condiviso `woo-chatbot`.

API e Chroma reali; Woo/OpenAI sono adapter HTTP deterministici. Modelli nominati
`synthetic-chat`/`synthetic-embedding`. Il provider verifica che identità, email e
credenziali sintetiche non entrino nei prompt; tre output malevoli (due ordini e un
documento Chroma) devono arrivare come JSON `untrusted_data`. Gli ordini restituiti
intenzionalmente dal provider con owner diverso sono scartati dal codice.

Fase healthy: **6,064 s**. Restart: **0,145 s**. Widget DOM/HTTP: **265 ms**.
Conteggi finali dell'intero run: 37 chiamate chat, 1 embedding, 14 lookup clienti,
4 letture ordini. Il provider riporta 370/185 token convenzionali (10/5 per chat):
sono contatori sintetici, non tokenizzazione reale o costo misurato. Provider
esterni: **0**, costo API **0 USD**.

Inventario: startup production invalido PASS, logging redatto PASS, cleanup PASS.
Hash app: `c0680a5ec8552ec6167e974d3acc96c5c23ca96f3f011c64b2d21cde22768da7`.
I primi run hanno rilevato due difetti del nuovo harness, poi corretti: nome del
campo OpenAI `max_completion_tokens` e proprietà `style` nel DOM minimale.
Ogni run ha rimosso e verificato soltanto le proprie risorse.

Limiti v1: store/cache/quote per processo, un solo worker; riavvio perde history;
logout locale senza revoca di token copiati; login reale Woo/SSO da integrare;
redazione difensiva, non DLP per segreti arbitrari offuscati. README e DEC-014/015
descrivono limiti, status, modello di fiducia e configurazione deployment.
