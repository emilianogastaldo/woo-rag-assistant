# Consegna del progetto finale Boolean

Fonte: email del Team Boolean condivisa dal corsista. Le date sono riportate
come nell’email; questa pagina distingue le indicazioni del corso dalle verifiche
interne scelte per `woo-rag-assistant`.

## Indicazioni comunicate da Boolean

| Voce | Indicazione |
| --- | --- |
| Obbligatorietà | Il progetto è obbligatorio per accedere al Certificato Finale e al Career Center e costituisce l’esame finale. |
| Obiettivo | Dimostrare le competenze apprese nel Master; non è richiesta la perfezione. Il progetto può avere utilità professionale o interesse personale. |
| Modalità | Condividere il codice tramite repository GitHub. |
| Scadenza | Entro la mezzanotte del **18/12**. |
| Presentazione | **Facoltativa**, durante l’ultima lezione del **19/12**. |
| Dati aziendali | Se utilizzati, condividere su GitHub solo il codice, non i dati. |
| Esito e accessi | I docenti esamineranno i progetti; informazioni su Certificato e Career Center via email entro il **23/12**. |

Per i dettagli tecnici: lezione del **26/09**, circa dal minuto **57**, e lezioni
«lavoro sul progetto personale». Per dubbi sul contenuto o sulla consegna,
chiedere nelle lezioni dedicate oppure a Federico Rios su Discord.
L’inizio del quinto modulo è indicato per il **17/11**; il calendario completo
sarà comunicato dal corso.

L’email non specifica durata della presentazione, modalità di invio del link o
accessi necessari a una repository privata: sono aspetti da confermare con i docenti.
Non richiede un deployment pubblico né strumenti per generare/eseguire codice.

## Come il progetto dimostra le competenze

| Competenza | Evidenza nel repository |
| --- | --- |
| Problema concreto e architettura | [README](../README.md) e [decisioni architetturali](architecture.md): assistenza clienti WooCommerce. |
| Ingestion, embedding e retrieval | [Ingestion versionata](ingestion-deployment.md), ricerca semantica/ibrida e citazioni verificabili. |
| Tool calling e orchestrazione | Ricerca documentale, catalogo e ordini; scelta delle fonti, budget, retry e fallback. |
| Memoria e sicurezza | [Persistenza conversazioni](issue-16-results.md), [login e isolamento clienti](issue-18-results.md). |
| Valutazione e limiti | [Eval](../evals/README.md), test offline e integrazioni isolate; [valutazione live ancora da eseguire](issue-17-results.md). |
| Dati riproducibili | [Seed sintetico e CSV campione](issue-19-results.md), senza dati aziendali o clienti reali. |

Il chatbot espone strumenti di sola lettura sul negozio. Non modifica ordini,
non emette rimborsi e non genera o esegue codice. I calcoli necessari, come la
scadenza del reso, sono codice deterministico del backend. Il salvataggio di
conversazioni e indici RAG è una responsabilità dell’applicazione, non un tool
con cui il modello può scrivere liberamente. Questo perimetro è una scelta del
progetto, non una limitazione imposta dall’email.

## Checklist interna prima della consegna

Questi sono controlli di qualità del progetto, non requisiti aggiuntivi di Boolean.
La checklist è da verificare sulla versione effettivamente consegnata.

- [ ] Scegliere la versione da consegnare, integrare le modifiche approvate e
  annotare il commit; verificare che i docenti possano accedere alla repository.
- [ ] Controllare README, avvio, configurazione di esempio e seed da ambiente pulito.
- [ ] Verificare che file, cronologia Git e report condivisi non contengano segreti
  o dati aziendali; usare solo dati sintetici negli esempi pubblicati.
- [ ] Eseguire i controlli pertinenti e documentare risultati, versione e limiti;
  distinguere test offline, servizi reali isolati e provider AI reale.
- [ ] Provare il percorso demo nel browser e spiegare le scelte progettuali.
- [ ] Condividere il link GitHub con il canale indicato dai docenti entro il 18/12.

La valutazione live della #17 resta un miglioramento da completare con budget
approvato prima di dichiarare qualità, latenza o costi reali. Non è indicata
nell’email come condizione obbligatoria per la consegna. Anche la messa in
produzione su un negozio reale è distinta dalla consegna del project work.

Se si sceglie di presentare il 19/12, usare la [traccia](presentazione.md),
concordare durata e formato e preparare pochi scenari dimostrativi verificabili.
La scaletta da circa 10 minuti è una proposta interna, non una durata comunicata
nell’email.
