# Issue #24 — scenari di reso ripetibili

Verifica del 4 novembre 2026, WordPress/WooCommerce 10.0.4 reale nel solo
progetto isolato `woo-demo-21` (`/tmp/woo-demo-21/compose.json`). Il negozio demo
preesistente non è stato usato. Nessuna API provider, modifica backend o chiave
letta/stampata; le email della fixture sono bloccate con `pre_wp_mail`.

## Preparazione opt-in

Il seed ordinario conserva i tre ordini storici. Il comando separato aggiunge
un solo ordine di Mario, con data di riferimento obbligatoria:

```bash
docker compose run --rm wpcli wp eval-file /seed/demo-returns.php 2026-12-18
```

L'ordine viene creato il 17 novembre 2026, completato e consegnato il 19 novembre
alle 14:30 UTC. La scadenza restituita dal backend è **19 dicembre 2026**.
Il riferimento del 18 dicembre è la data per cui si prepara lo scenario: non
cambia il clock del backend. Anche il 19 dicembre la stessa fixture è valida,
al confine della finestra. In una prova anticipata indicare la data nella domanda.
Al 4 novembre questa consegna è ancora futura: la fixture serve alla
presentazione di dicembre. Per una demo valida oggi preparare **un altro
ambiente isolato** con riferimento `2026-11-04`: consegna 06/10 e termine 05/11.
Il backend continua sempre a usare la data reale; una domanda con data futura
esplicita è soltanto una simulazione, non prova un cambio del clock applicativo.

Il comando stampa l'ID effettivo: gli ID dipendono dal database, non vanno assunti.
Lo stesso comando conserva ID, date e numero ordini. Riferimento diverso,
data impossibile o argomento mancante vengono rifiutati prima delle scritture.
Un marker nell'ordine permette il recupero anche se manca l'option finale;
un secondo marker permette di completare articoli/totali dopo un'interruzione.

Per una nuova prova in altra data usare **un nuovo ambiente demo con volumi
propri**, eseguire il seed ordinario e passare la nuova data al comando separato.
Non eliminare gli ordini o il gate del negozio esistente e non spostare le date.
Il comando è un preparatore manuale seriale; non è previsto avviarlo in parallelo.

## Domande e risultati attesi

ID reali rilevati nel progetto isolato (Mario cliente 2, Luigi cliente 3):

| Data della domanda | Ordine | Domanda da Mario autenticato | Risultato atteso |
| --- | --- | --- | --- |
| 18/12/2026 | **#27**, sintetico | «Alla data del 18 dicembre 2026 posso ancora rendere l'ordine 27?» | Consegna verificata 19/11; termine 19/12; entro termine, con policy citata. |
| 19/12/2026 | **#27** | «Alla data del 19 dicembre 2026 posso ancora rendere l'ordine 27?» | Ultimo giorno della finestra, scadenza 19/12. |
| 20/12/2026 | **#27** | «Alla data del 20 dicembre 2026 posso ancora rendere l'ordine 27?» | Finestra trascorsa dal giorno successivo. |
| 18 o 19/12/2026 | **#19**, storico | «Alla data del 18 dicembre 2026 posso ancora rendere l'ordine 19?» | Consegna verificata 22/06; termine 22/07; fuori termine. |
| 18 o 19/12/2026 | **#20**, storico | «Quando scade il reso dell'ordine 20?» | Consegna non verificata; scadenza non calcolabile; contattare assistenza. |
| qualsiasi | **#21**, storico di Luigi | «Qual è lo stato dell'ordine 21?» | Ordine non trovato per Mario; nessuna esposizione dei dati altrui. |

Le risposte naturali con citazioni restano attese per la demo con provider:
qui sono stati verificati i dati e il formatter/calcolo reale, senza interrogare
un modello. Il backend restituisce la scadenza, non un verdetto automatico di
ammissibilità; il confronto con le date esplicite è verificato nei test offline.

## Verifiche eseguite

- **PHP reale PASS**, `evals/issue24_returns.php`: tre esecuzioni dello scenario,
  inclusa la rimozione dell'option finale per simulare una run interrotta;
  sempre gli stessi quattro ordini e dati/date identici; tutti i dati dei tre
  storici conservati. Date sintetiche di creazione e completamento verificate.
- CLI reale: riferimento mancante, `2026-02-30` e cambio a `2026-12-19`
  rifiutati con exit code 1. Nessun ordine aggiuntivo.
- **14 pytest PASS**: 6 nuovi casi in `chatbot/tests/test_demo_returns.py`
  (entro termine, confine incluso, giorno successivo escluso, storico scaduto
  il 18 e il 19, completamento senza tracking), più gli 8 esistenti in
  `chatbot/tests/test_orders.py`. Usano `format_order` esistente, nessun calcolo
  alternativo nel backend.
- Lint Ruff del nuovo test e sintassi PHP dei due file nuovi.

Comando della prova PHP (richiede esattamente i tre storici iniziali e lascia
la fixture sintetica nel progetto isolato):

```bash
docker compose --env-file /dev/null -f /tmp/woo-demo-21/compose.json -p woo-demo-21 \
  run --rm --no-deps -T -v "$PWD/evals:/evals:ro" cli \
  wp eval-file /evals/issue24_returns.php
```

Nessuna modifica a seed ordinario, setup, Compose, README o presentazione:
l'integrazione delle istruzioni comuni viene gestita separatamente.

Aggiornamento della verifica integrata #25: il preparatore resi impedisce la
riduzione stock durante la creazione della sola fixture sintetica. Il test PHP
controlla anche lo stock invariato. Il runner riproducibile
`python3 evals/run_issue19_import.py --demo-final` prepara un database nuovo ed
esegue questo stesso test dopo il seed ordinario; risultato e nuovi ID nel
[report finale](issue-25-results.md). Non occorre recuperare il vecchio `/tmp`.
