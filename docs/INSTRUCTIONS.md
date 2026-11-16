Analizza integralmente e visivamente tutte le pagine renderizzate e numerate del PDF. L'analisi e il ragionamento
sul contenuto sono liberi e integrali. La pipeline non esegue OCR preventivo; il risultato richiesto e' il JSON
strutturato, non una fase OCR separata.

REGOLA DI ISOLAMENTO: le presenti istruzioni definiscono soltanto il metodo e non sono una fonte documentale.
Non copiare nei campi nomi, luoghi, numeri, date, indirizzi, esiti o testi presenti nelle istruzioni. Un valore
può essere restituito esclusivamente se è materialmente visibile nelle immagini del fascicolo ricevuto.
Tutto ciò che è marcato come ESEMPIO serve esclusivamente a mostrare il ragionamento: i suoi valori sono dati
fittizi vietati nell'output. Prima di emettere il JSON, verifica per ogni valore che la sua origine sia una
specifica immagine `PAGINA N`, mai un esempio o una frase di queste istruzioni. Se non puoi indicare quella
pagina e la relativa area visiva, non usare il valore dell'esempio.

La separazione e la classificazione documentale sono temporaneamente isolate e non fanno parte di questa
analisi. Non dividere il fascicolo, non classificare le pagine e non restituire liste di pagine per documento
principale o allegati. Usa invece tutte le pagine come unico contesto documentale per estrarre e verificare
i quattordici campi specialistici richiesti.

Per questo test geolocalizzazione e separazione sono temporaneamente isolate, mentre il rank è attivo.
Per ciascuno dei quattordici campi restituisci `value` e `rank`. Non restituire numeri pagina e non stimare
coordinate o rettangoli. Questa semplificazione riguarda esclusivamente l'output: devi comunque usare tutte
le pagine per verificare globalmente ogni valore.

Il `rank` è un intero da 1 a 10 e misura la solidità documentale del valore: 10 indica un valore esplicito,
leggibile, semanticamente corretto e confermato nel fascicolo; valori progressivamente inferiori indicano
evidenza più debole o ambigua. Il rank valuta ogni campo autonomamente e non deve essere aumentato o ridotto
in base ai valori degli altri campi, salvo una verifica diretta dello stesso dato in più punti del fascicolo.
Quando `value` è `""`, usa sempre rank 3. Il rank non sostituisce le regole di validità: un candidato non
valido o ambiguo deve restare vuoto con rank 3, non essere restituito con un rank basso.

Leggi esclusivamente il contenuto del documento allegato.
Il documento può essere una scansione archivistica con timbri, annotazioni manoscritte, allegati tecnici, planimetrie, relazioni, notifiche, visure o pagine accessorie.

Restituisci solo un JSON valido conforme alle chiavi e alla struttura richieste, senza testo aggiuntivo, senza markdown, senza commenti e senza spiegazioni.

Estrai i campi:
protocollo, data_protocollo, richiedente, comune, odonimo, civico, foglio, particella, subalterno, categoria_catastale, data_valutazione, esito_valutazione, testo_valutazione, sintesi.

=== REGOLE GENERALI (valgono per tutti i campi) ===

1. Usa "" per qualsiasi campo mancante, non leggibile, non esplicito o ambiguo. Non inventare, non dedurre, non completare dati mancanti. Usa solo informazioni effettivamente presenti nel documento.

2. Non usare il nome del file per compilare alcun campo. Non aggiungere etichette come "Protocollo:", "Via:": restituisci solo il valore.

3. Se il fascicolo contiene più documenti (modulo principale, allegati, planimetrie, visure, note di trasmissione, richieste di accesso agli atti, richieste di copia), privilegia sempre il modulo o atto principale della pratica edilizia (permesso o licenza a costruire, SCIA, DIA, CILA, condono o altro titolo edilizio). Non usare mai dati provenienti da documenti accessori.

4. Se lo stesso campo compare più volte, scegli il valore più direttamente associato alla pratica principale; se resta ambiguità, usa "".

5. In presenza di testo stampato e manoscritto per lo stesso campo, scegli la fonte che svolge realmente la
funzione amministrativa richiesta dal campo. Non privilegiare automaticamente lo stampato: per protocollo e
data_protocollo un timbro di protocollo o un'annotazione manoscritta dell'ufficio prevalgono su codici
archivistici prestampati del frontespizio.

6. TESTO E NUMERI MANOSCRITTI (vale per TUTTI i campi). Procedura:
   a) Osserva la forma grafica del segno.
   b) Elenca mentalmente le interpretazioni plausibili sulla base della forma (non della plausibilità semantica o storica).
   c) Se UNA interpretazione è chiaramente prevalente in base alla forma → trascrivila.
   d) Se DUE O PIÙ interpretazioni sono ugualmente plausibili → restituisci "".
   La soglia è "equiplausibilità", non "piena certezza".

7. RIFERIMENTO PER CIFRE MANOSCRITTE CONFONDIBILI (osserva la FORMA, scegli la cifra la cui descrizione corrisponde meglio al segno; restituisci "" solo se il segno è compatibile con due descrizioni in modo equivalente):
   - 2 vs 7: il 2 ha curva superiore chiusa o ad asola e base orizzontale; il 7 ha tratto superiore orizzontale (talvolta con svolazzo) e discesa diagonale senza base.
   - 1 vs 7: l'1 ha tratto verticale (eventualmente con piccolo uncino in alto); il 7 ha tratto orizzontale netto in alto.
   - 0 vs 6: lo 0 è chiuso simmetrico; il 6 ha occhiello in basso e tratto che scende da sopra.
   - 3 vs 8: il 3 ha lato sinistro aperto; l'8 ha due occhielli chiusi.
   - 4 vs 9: il 4 ha angolo aperto in alto a sinistra; il 9 ha occhiello chiuso in alto.
   - 3 vs 5: il 3 ha due curve aperte a sinistra; il 5 ha tratto orizzontale superiore e curva inferiore.

CROSS-CHECK CON FONTI PIÙ LEGGIBILI:
Prima di concludere la lettura di una cifra manoscritta dubbia,
verifica se la STESSA cifra/data compare in una fonte più leggibile
nel fascicolo (timbro dattiloscritto, intestazione stampata, atto
formale). Se sì:
  • la lettura della fonte dattiloscritta PREVALE sulla lettura
    manoscritta, anche quando il segno manoscritto sembrerebbe
    suggerire una cifra diversa
  • non "votare per maggioranza" tra fonti: una sola fonte
    dattiloscritta chiara vale più di qualunque numero di
    annotazioni manoscritte concordanti tra loro

[ESEMPIO NON DOCUMENTALE — NON COPIARE I VALORI]
Un timbro dattiloscritto con data 3.3.1951 prevale su un'annotazione manoscritta dubbia letta come 5-3-951:
il valore metodologicamente corretto è 03/03/1951, perché proviene dalla fonte più leggibile.
[FINE ESEMPIO]

8. Non confondere il richiedente con tecnico, progettista, impresa, direttore lavori, collaudatore, funzionario, sindaco, commissione o altro soggetto.

9. Valori multipli: se foglio o categoria_catastale hanno più valori chiaramente riferiti alla stessa
   pratica, separali con `; `. Per particella e subalterno applica sempre la regola specialistica delle
   liste parallele descritta sotto: stesso separatore `; `, stesso numero di posizioni e associazione
   particella-subalterno conservata riga per riga.

10. ORIENTAMENTO DEL TESTO. Timbri, annotazioni e contenuti possono
    apparire ruotati rispetto all'orientamento principale della pagina
    (90° orari, 90° antiorari, 180°, o angoli intermedi). Il contenuto
    ruotato è valido a tutti gli effetti e va letto come qualunque
    altro contenuto:
    
    - NON scartare un timbro/annotazione solo perché ruotato.
    - Mentalmente "raddrizza" il segmento per leggerlo nel suo
      orientamento naturale, poi applica le regole standard di
      interpretazione.
    - L'autorevolezza della fonte (dattiloscritto vs manoscritto,
      atto sostanziale vs firma formale) NON dipende dall'orientamento:
      un timbro dattiloscritto ruotato di 90° resta una fonte
      dattiloscritta autorevole, con la stessa priorità che avrebbe
      se fosse orizzontale.
    - La rotazione non giustifica la restituzione di "" se
      l'interpretazione resta chiara dopo la rotazione mentale.

=== CAMPI ===

protocollo:
Numero assegnato dall'ufficio al momento della protocollazione della pratica. Deve essere materialmente
collegato a una segnatura amministrativa di protocollo, normalmente un timbro, un riquadro di registrazione
o un'annotazione manoscritta con etichette come "Protocollo", "Prot.", "N. prot.", "Registro" o "Arrivo".
La sola presenza sul frontespizio non dimostra che un numero sia il protocollo.
Il protocollo non deve contenere barre "/", punti "." o virgole ",".
NON usare codici di busta, fascicolo, sottofascicolo, serie, classificazione, segnatura archivistica o
collocazione riportati sul frontespizio. In particolare `05/D114` e varianti grafiche o di maiuscole/minuscole
sono codici di fascicolatura, non numeri di protocollo. Non trasformarli né rimuovere la barra per farli
sembrare protocolli.
Non usare numeri di deliberazione, licenza, tavola, elaborato, mappale, foglio, particella, riferimento
archivistico o numeri presenti in planimetrie.
Non usare valori manoscritti nella forma numero/barra/anno breve: possono indicare tavole o elaborati grafici.
Prima di compilare il campo individua l'etichetta o il timbro di protocollo e verifica che il numero sia
dentro o immediatamente accanto a tale area. Se esiste soltanto un codice di fascicolatura, restituisci "".
[ESEMPIO NON DOCUMENTALE — NON COPIARE I VALORI]
Forme come "1/50'", "2/50'", "60/51'" e "61/51'" rappresentano tavole o elaborati e non protocolli.
[FINE ESEMPIO]

data_protocollo:
È esclusivamente la data in cui l'ufficio ha protocollato o registrato in arrivo la pratica. Deve appartenere
alla stessa segnatura amministrativa del protocollo scelto: stesso timbro/riquadro oppure immediata vicinanza
visiva con relazione inequivocabile. `data_protocollo` e `protocollo` devono descrivere lo stesso evento di
registrazione, anche quando si trovano in due rettangoli distinti della stessa area.
NON usare la data di presentazione o compilazione della domanda, la data dichiarata dal richiedente, la data
di nascita, firma, deposito non protocollato, progetto, valutazione, parere, commissione, approvazione,
rigetto, visto, licenza, deliberazione, rilascio o provvedimento. Le formule "presentata il", "domanda del",
"data di presentazione", "nato/a il", "lì" o "addì" non identificano la data di protocollo, salvo che la
stessa area riporti esplicitamente anche la registrazione di protocollo/arrivo.
Non usare mai date vicine a formule come "Visto: Approvato con deliberazione", "Si approva", "Si respinge", "licenza rilasciata", "provvedimento del Podestà".
Prima di compilare il campo confronta tutte le date candidate e scarta quelle riferite agli eventi sopra
elencati. Formato GG/MM/AAAA. Se non è visivamente e semanticamente associata al protocollo, restituisci "".

richiedente:
Persona, persone o ragione sociale che presenta formalmente la pratica.
Ricerca il nominativo in tutto il fascicolo e confronta modulo principale, firme, titolo di proprietà,
documenti di identità, deleghe e altri atti riferiti alla stessa pratica. Usa le altre pagine per confermare
ortografia, completezza e presenza di più richiedenti; non limitarti al primo frammento incontrato.
Nel valore inserisci soltanto il nome completo della persona, i nomi completi di tutti i richiedenti oppure
la ragione sociale completa. Se i richiedenti sono più di uno, riportali tutti separati da `, `, purché siano
effettivamente indicati come richiedenti o proprietari che presentano la pratica.
NON includere Comune, luogo o data di nascita, anno, indirizzo, codice fiscale, parole come "nato/a",
"residente", "Comune di", né porzioni di altre righe. Questi elementi possono aiutare a confermare
l'identità, ma non fanno parte del valore `richiedente`.
Non confondere il richiedente con l'ente destinatario o protocollante: un Comune non è il richiedente solo
perché compare nell'intestazione o nel timbro.
Conserva formule genealogiche come "fu", "di", "figlio di", "ved.", "coniugi", "e" se fanno parte del nominativo. Non separare, semplificare o rimuovere.
[ESEMPIO NON DOCUMENTALE — NON COPIARE I NOMI]
"Chiriatti Giovanni fu Annunziato e Paglialunga Consolata fu Antonio" mostra soltanto come conservare una
formula genealogica completa.
[FINE ESEMPIO]

comune:
Comune amministrativo a cui si riferisce la pratica edilizia, normalmente il Comune che riceve/protocolla la domanda, rilascia il titolo o nel cui territorio si trova l'immobile oggetto dell'intervento.
Privilegia la denominazione esplicita presente nell'intestazione dell'atto principale o nel timbro di protocollo. Non confondere il Comune con la Provincia, una frazione, una contrada, il luogo di nascita/residenza del richiedente o comuni citati in allegati accessori.
Non dedurre il Comune dal nome del file, dall'odonimo o da conoscenze geografiche esterne. Se più comuni restano equiplausibili, restituisci "".

odonimo:
Denominazione toponomastica dell'immobile oggetto della pratica, senza numero civico.
Ricercala obbligatoriamente nei campi o riquadri etichettati `Ubicazione`, `Ubicazione dell'immobile`,
`Estremi dell'immobile`, `Localizzazione dell'intervento` o formule semanticamente equivalenti riferite al
bene oggetto dei lavori. Riferiscila all'immobile oggetto dell'intervento, non all'indirizzo di residenza,
domicilio, recapito o sede del richiedente, del tecnico, dell'impresa o dell'esecutore di un pagamento.
Se sono presenti più indirizzi, confronta anche il civico: privilegia la coppia odonimo+civico ripetuta
coerentemente nelle sezioni dedicate all'immobile. Non scegliere un indirizzo soltanto perché compare più
volte se le sue etichette indicano residenza, domicilio, studio, sede o versante.
Conserva prefissi (via, viale, piazza, strada, contrada, località) e specificazioni (parentesi, contrade, denominazioni particolari) solo se esplicitamente presenti nel documento; non aggiungerli, non normalizzarli, non completare abbreviazioni.
Prima di scrivere l'output, separa sempre l'indirizzo selezionato nei due componenti: `odonimo` contiene
soltanto la denominazione stradale e non deve contenere il numero civico finale, perché quel numero appartiene
esclusivamente al campo `civico`.

civico:
Numero civico dell'immobile oggetto della pratica, senza nome della via.
Riferito all'immobile oggetto dell'intervento, non al recapito del richiedente.
È valido soltanto se appare nella stessa riga, nello stesso riquadro o immediatamente accanto all'odonimo
scelto, formando con esso l'indirizzo dell'immobile. Verifica congiuntamente odonimo e civico prima di
compilare entrambi.
Il civico deve provenire dalla medesima occorrenza di `Ubicazione dell'immobile` usata per l'odonimo. Se una
residenza e un'ubicazione dell'immobile hanno lo stesso odonimo ma civici diversi, scegli esclusivamente il
civico dell'immobile.
Questa è una regola vincolante: dopo avere scelto l'ubicazione, estrai da quella stessa stringa sia odonimo
sia civico e ignora qualsiasi candidato civico proveniente da altre sezioni, anche se più leggibile, ripetuto
o riferito alla stessa persona. Non restituire mai nel campo `civico` il numero della residenza quando è
presente il numero dell'ubicazione dell'immobile.
NON usare date o loro frammenti: sequenze nel formato giorno/mese/anno, con punti, trattini o barre, e numeri
vicini a "nato/a", "data", "anno", "lì" o "addì" non sono civici. Non usare numeri catastali, di protocollo,
pagina, fascicolo, interno o telefono come civico.
Conserva lettere, barre e suffissi soltanto quando appartengono chiaramente al civico vicino all'odonimo.
Se l'odonimo è individuato ma nessun numero civico è collegato visivamente a esso, restituisci "".

foglio:
Solo il foglio catastale. Diciture equivalenti: "Fg.", "F.", "Fog.", "Foglio", "foglio catastale".
Non confondere con numero di pagina, fascicolo, busta, protocollo o altri numeri amministrativi.

particella:
Solo la particella catastale o mappale. Diciture equivalenti: "Part.", "P.lla", "Plla", "Partic.", "Particella", "Mapp.", "Mappale", "n. particella".
Non confondere con civico, protocollo, foglio o subalterno.
Possono esistere più particelle: estrai tutte quelle riferite all'immobile della pratica, nell'ordine delle
rispettive righe catastali, separandole esclusivamente con punto e virgola seguito da spazio (`; `).
Non fermarti alla prima particella leggibile: cerca sistematicamente in tutte le pagine ogni tabella, visura,
riquadro o riga catastale riferita allo stesso immobile e inserisci ogni coppia valida anche quando compare
in un punto diverso del fascicolo.

subalterno:
Solo il subalterno catastale. Diciture equivalenti: "Sub.", "Sub", "Subalt.", "Subalterno", "S.".
Non confondere con foglio, particella, civico, interno, piano o altri numeri non catastali.
Ogni subalterno valido contiene esclusivamente una o due cifre numeriche (`0`-`99`). Valori con punti,
barre, lettere o più di due cifre non sono subalterni e devono produrre `""`.
Possono esistere più subalterni. Mantieni obbligatoriamente la correlazione posizionale con `particella`:
il primo subalterno appartiene alla prima particella, il secondo alla seconda e così via. Usa lo stesso
separatore `; ` e restituisci lo stesso numero di posizioni nei due campi. Se una particella ha più subalterni,
ripeti la particella in `particella` per ogni coppia e inserisci i relativi subalterni nello stesso ordine.
Non raggruppare, ordinare numericamente o deduplicare valori se ciò rompe l'associazione riga-per-riga.
Compila inoltre `cadastral_pairs` con una voce distinta per ogni coppia trovata. Ogni voce ha rank autonomi:
`particella_rank` valuta soltanto quella particella e `subalterno_rank` soltanto il subalterno associato.
Le stringhe aggregate dei campi `particella` e `subalterno` devono contenere esattamente gli stessi elementi,
nello stesso ordine, della lista `cadastral_pairs`.

categoria_catastale:
Categoria catastale esplicitamente presente nel documento. Diciture equivalenti: "Cat.", "Categ.", "Categoria", "Categoria catastale".
Il valore è valido esclusivamente se ha la forma `LETTERA/DUE_CIFRE`: una sola lettera, una barra `/` e
esattamente due cifre dopo la barra. Elimina soltanto eventuali spazi tipografici interni e restituisci la lettera
maiuscola. Se manca la barra o mancano le cifre dopo la barra, restituisci `""`.
[ESEMPIO NON DOCUMENTALE — NON COPIARE I VALORI]
Formati quali "A/3", "C/6" e "D/7" mostrano soltanto la forma possibile di una categoria catastale.
[FINE ESEMPIO]
Non confondere con destinazioni d'uso, classi, zone urbanistiche o tipologie di intervento. Valori come
`Residenziale`, sigle senza barra come `B1`, numeri decimali, rapporti o scale come `1.1000` non sono
categorie catastali e devono produrre `""`.

=== VALUTAZIONE (data_valutazione, esito_valutazione, testo_valutazione) ===

Estrai i dati dell'ULTIMO parere in senso CRONOLOGICO (data di calendario più recente, NON ultimo incontrato leggendo il documento), riferito chiaramente alla pratica principale.
Per "valutazione" si intende esclusivamente una decisione, un parere o un provvedimento amministrativo sulla
pratica edilizia. NON costituiscono valutazione la comunicazione o dichiarazione di inizio attività/lavori,
la data prevista o effettiva di inizio attività/lavori, la presentazione di DIA/SCIA/CILA, una ricevuta di
deposito, una protocollazione, una trasmissione, una notifica o una semplice presa d'atto priva di giudizio.
Non ricavare esito, data o testo di valutazione da tali eventi. Se il fascicolo contiene soltanto informazioni
sull'inizio dell'attività e nessun vero parere/decisione edilizia, restituisci "" per tutti e tre i campi.
L'esito può trovarsi su fogli con planimetrie o elaborati grafici, spesso vicino a un timbro, una nota manoscritta o formule come "Visto: Approvato con deliberazione".
Cerca soprattutto: lato destro del foglio, margini laterali, timbri di approvazione, planimetrie, note manoscritte a margine, righe vicino a formule di approvazione, rigetto, visto, deliberazione o parere.

data_valutazione:
PROCEDURA OBBLIGATORIA per data_valutazione, esito_valutazione, testo_valutazione:

STEP 1 - Individua TUTTI i timbri e le annotazioni di valutazione
presenti nel fascicolo (qualunque pagina: planimetrie, margini,
retro, accanto a disegni).

STEP 2 - Per OGNI timbro/annotazione, classifica le date presenti
in due categorie semantiche:

  CATEGORIA A - DATA DELL'ATTO SOSTANZIALE
  (= quando la decisione amministrativa è stata presa).
  Riconoscibile perché la data è legata a un atto con valore
  decisorio. Indicatori (non esaustivi, valgono varianti e forme
  equivalenti in qualunque epoca):
    • "deliberazione/delibera ... del [DATA]"
    • "parere [favorevole/contrario/n.X] ... del/in data [DATA]"
    • "Commissione Edilizia ... del/in data/seduta del [DATA]"
    • "determinazione/determina ... del [DATA]"
    • "decreto/ordinanza/provvedimento ... del [DATA]"
    • "verbale ... del [DATA]" / "seduta del [DATA]"
    • "licenza/concessione/permesso di costruire/autorizzazione/
       nulla osta ... del [DATA]"
    • "approvato/respinto/rilasciato con atto n.X del [DATA]"
    • qualunque preposizione "del [DATA]" / "in data [DATA]"
       agganciata a un sostantivo che indica una DECISIONE

  CATEGORIA B - DATA FORMALE / FIRMA / TRASMISSIONE / RILASCIO
  (= quando l'atto è stato firmato, comunicato, consegnato).
  NON rappresenta la decisione, solo la sua veste formale.
  Indicatori:
    • "[Luogo], lì [DATA]" / "[Luogo], addì [DATA]"
    • data immediatamente prima/dopo una firma di:
        IL SINDACO, IL PODESTÀ, IL COMMISSARIO PREFETTIZIO,
        IL DIRIGENTE, IL RESPONSABILE [DEL SERVIZIO/PROCEDIMENTO],
        IL FUNZIONARIO, IL SEGRETARIO COMUNALE, IL CAPO UFFICIO,
        IL TECNICO COMUNALE, IL PROGETTISTA, IL DIRETTORE DEI LAVORI
    • "rilasciato/emesso/spedito/trasmesso/comunicato/notificato/
       ricevuto/protocollato in data [DATA]" (quando segue un atto
       già datato altrove)
    • "visto il [DATA]" quando "visto" è isolato e non accompagnato
       da una formula deliberativa autonoma

  REGOLA DI PRIORITÀ (universale, qualunque epoca):

  a) Se nel timbro/annotazione compaiono date di entrambe le
     categorie → "data dell'atto" = data di CATEGORIA A.
     IGNORA tutte le date di CATEGORIA B.

  b) Se compaiono SOLO date di CATEGORIA A (anche più di una,
     es. parere CE + delibera Consiglio) → "data dell'atto" =
     la più recente tra quelle di CATEGORIA A (rappresenta
     l'ultima decisione sostanziale all'interno dello stesso atto).

  c) Se compaiono SOLO date di CATEGORIA B (nessuna sostanziale
     individuabile) → "data dell'atto" = la più recente di
     CATEGORIA B. È un fallback: in assenza di data sostanziale,
     la firma formale è l'unico riferimento disponibile.

  d) Annotazione con sola firma e data accanto a un disegno,
     senza altra formula → quella è la "data dell'atto"
     (visto silenzioso, vale come decisione).

STEP 3 - Costruisci la sequenza cronologica di tutte le
"date dell'atto" individuate al STEP 2 nelle varie pagine.

STEP 4 - Scegli l'annotazione/timbro con la data CRONOLOGICAMENTE
PIÙ RECENTE (più avanti nel calendario, NON la prima incontrata
leggendo, NON la più visibile, NON la più grande).

STEP 4b - CONSOLIDAMENTO FONTI MULTIPLE PER LO STESSO EVENTO:
Se la data scelta al STEP 4 compare in PIÙ punti del fascicolo
(es. un timbro dattiloscritto E un'annotazione manoscritta che
descrivono la stessa decisione, con stessa data e stesso esito),
considera queste fonti come UN UNICO evento di valutazione e usa
come FONTE AUTOREVOLE PRIMARIA:

  Priorità (alta → bassa):
    1) timbro dattiloscritto/stampato leggibile
    2) annotazione manoscritta con formula esplicita
       ("Si approva", "Si respinge", deliberazione)
    3) firma manoscritta con data accanto al disegno

  La fonte primaria detta:
    • il VALORE di data_valutazione (anche se la fonte secondaria
      sembra suggerire una cifra diversa: la cifra del timbro
      dattiloscritto vince su quella manoscritta dubbia)
    • il VALORE di esito_valutazione
    • usa il valore della fonte primaria, non quello della fonte accessoria

  Le altre fonti dello stesso evento sono repliche accessorie
  e non condizionano il valore scelto.

[ESEMPIO NON DOCUMENTALE — NON COPIARE I VALORI]
Pag. A: timbro dattiloscritto "Approvato con deliberazione n.1 del 3.3.1951".
Pag. B: annotazione manoscritta "3-3-951 / Si approva", con cifre incerte.
La fonte primaria è il timbro di pag. A: data_valutazione è 03/03/1951 ed esito_valutazione è "Approvata".
[FINE ESEMPIO]

STEP 5 - Compila:
  → data_valutazione = data scelta al STEP 4 (formato GG/MM/AAAA;
    anno a 3 cifre che inizia con 9 = 19xx; zero iniziale a
    giorni/mesi a una cifra)
  → esito_valutazione = esito contenuto in QUEL timbro/annotazione
    (vedi Classificazione: formule positive → "Approvata",
    negative → "Respinta", ecc.)
  → testo_valutazione = trascrizione breve di QUEL timbro/annotazione

Le annotazioni precedenti sono SUPERATE e non influenzano l'esito,
anche se contengono rigetti o approvazioni di segno opposto.

[ESEMPI APPLICATIVI NON DOCUMENTALI — NON COPIARE ALCUN VALORE]
- Un visto con deliberazione del 3.3.1951 e firma formale del 6.3.1951 usa 03/03/1951 come data dell'atto.
- Una licenza del 12/04/1975 rilasciata e firmata il 20/04/1975 usa 12/04/1975 come data sostanziale.
- Un permesso del 15/06/2008, fondato su parere del 02/06/2008 e firmato il 20/06/2008, usa 15/06/2008.
- Tra un rigetto del 19/12/1950 e un'approvazione del 03/03/1951 riferiti alla stessa pratica, prevale
  cronologicamente l'approvazione del 03/03/1951.
[FINE ESEMPI]

REGOLA GENERALE:
Data dell'ultimo esito chiaro riferito alla pratica, associata
all'esito_valutazione scelto e normalmente nello stesso timbro/nota.
Non usare date di protocollo, domanda, firma del progetto, tavola,
relazione tecnica, visura, notifica o documenti accessori.

Formato GG/MM/AAAA. Se l'anno ha tre cifre e inizia con nove, anteponi la cifra uno.
Aggiungi zero iniziale a giorni/mesi a
una cifra.
Se non chiaramente associata all'esito scelto, restituisci "".

esito_valutazione:
REGOLA FONDAMENTALE: l'esito DEVE corrispondere alla STESSA
annotazione/timbro da cui hai estratto data_valutazione. L'esito
"segue la data": una volta scelta la data cronologicamente più recente
(come da regole prioritarie nella sezione data_valutazione), l'esito
si determina ESCLUSIVAMENTE dalle formule contenute in quella
specifica annotazione, ignorando ogni annotazione precedente.

Classificazione (basata sull'annotazione di data_valutazione):
- formule positive ("Si approva", "approvata", "favorevole",
  "visto approvato", "Visto: Approvato con deliberazione") → "Approvata"
- formule negative ("Si respinge", "respinta", "rigetto", "diniego",
  "non si approva", "parere contrario", "non conforme", "manca",
  "per mancanza", "non accolta", "sfavorevole") → "Respinta"
- "sospesa", "rinviata", "in attesa di integrazione" → "Sospesa"
- "archiviata" → "Archiviata"
- annotazione con sola data e firma, senza formula esplicita ma
  associata a un disegno/progetto senza note negative → "Approvata"
  (il visto silenzioso del Sindaco vale come approvazione)
- ambiguo o non esplicito → ""

CASI PARTICOLARI:

1) RIGETTI PRECEDENTI SUPERATI - un rigetto trovato in un'annotazione
   PRECEDENTE rispetto a data_valutazione NON influenza l'esito.
   È considerato superato dall'esito successivo.

   [ESEMPIO NON DOCUMENTALE — NON COPIARE I VALORI]
   Un rigetto del 19/12/1950 seguito da "Si approva" del 09/03/1951 produce data_valutazione 09/03/1951
   ed esito_valutazione "Approvata".
   [FINE ESEMPIO]

2) RIGETTO INTERNO A UN VISTO/DELIBERAZIONE - se l'annotazione di
   data_valutazione è formalmente un "Visto" o richiama una
   deliberazione ma il TESTO INTERNO contiene una formula di rigetto
   specifica, l'esito è "Respinta", NON "Approvata". Il "Visto"
   in quel caso è solo intestazione formale, non un'approvazione.

   La parola "Visto" può introdurre un atto che formalizza un rigetto
   e non costituisce da sola un'approvazione.

   [ESEMPIO NON DOCUMENTALE — NON COPIARE I VALORI]
   "Visto: Con deliberazione N.12 del 19.12.950 è stato respinto" produce una valutazione respinta con
   data sostanziale 19/12/1950; la parola "Visto" non rende positivo l'esito.
   [FINE ESEMPIO]

3) PIÙ ESITI nella STESSA annotazione con la stessa data, in conflitto
   tra loro → "".

testo_valutazione:
Trascrivi brevemente il testo originale o la parte più rilevante (annotazione, timbro, parere) effettivamente usata per compilare data_valutazione ed esito_valutazione.
Se non leggibile, usa "".

=== SINTESI ===

sintesi:
Riassunto neutro e breve, massimo 1-2 frasi, basato solo sul contenuto del documento.
Ogni volta che nella sintesi viene riportato il valore di uno dei campi estratti (protocollo, data_protocollo, richiedente, comune, odonimo, civico, foglio, particella, subalterno, categoria_catastale, data_valutazione, esito_valutazione), il valore deve essere SEMPRE preceduto dalla relativa etichetta in forma leggibile.
Usa le etichette: Protocollo, Data protocollo, Richiedente, Comune, Odonimo, Civico, Foglio, Particella, Subalterno, Categoria catastale, Data valutazione, Esito valutazione.
Non riportare nella sintesi campi con valore "".
[ESEMPIO NON DOCUMENTALE — NON COPIARE I VALORI]
Le forme "Protocollo 22343", "Richiedente Rossi Mario", "Comune Copertino", "Odonimo Via Roma" e
"Categoria catastale A/3" mostrano esclusivamente l'uso delle etichette nella sintesi.
[FINE ESEMPIO]

=== STRUTTURA JSON OBBLIGATORIA ===

CONTROLLO FINALE ANTI-CONTAMINAZIONE: confronta mentalmente tutti i valori compilati con i blocchi ESEMPIO.
Se un valore compare soltanto negli esempi e non è visibile nelle immagini `PAGINA N`, sostituiscilo con
`""`. Gli esempi non sono mai evidenza.

Esegui inoltre questi controlli obbligatori prima dell'output:
- protocollo: non è un codice di busta/fascicolo/frontespizio ed è localizzato su una vera segnatura di protocollo;
- data_protocollo: appartiene alla stessa registrazione del protocollo e non è presentazione, nascita, firma o valutazione;
- richiedente: contiene soltanto nominativi completi confermati nel fascicolo, senza Comune, luogo, data o anno;
- civico: è contiguo all'odonimo dell'immobile e non ha forma o funzione di data;
- valutazione: riguarda un vero parere/decisione sulla pratica e non l'inizio dell'attività o dei lavori;
- ogni valore deriva dalle immagini del fascicolo e non dagli esempi.
Se uno di questi controlli fallisce, imposta `needs_review` a true e usa `""` quando il valore non è
semanticamente valido.

Restituisci esattamente questa struttura, senza chiavi aggiuntive. Non restituire classificazioni, liste di
pagine o coordinate.

{
  "fields": {
    "protocollo": {"value": "", "rank": 3},
    "data_protocollo": {"value": "", "rank": 3},
    "richiedente": {"value": "", "rank": 3},
    "comune": {"value": "", "rank": 3},
    "odonimo": {"value": "", "rank": 3},
    "civico": {"value": "", "rank": 3},
    "foglio": {"value": "", "rank": 3},
    "particella": {"value": "", "rank": 3},
    "subalterno": {"value": "", "rank": 3},
    "categoria_catastale": {"value": "", "rank": 3},
    "data_valutazione": {"value": "", "rank": 3},
    "esito_valutazione": {"value": "", "rank": 3},
    "testo_valutazione": {"value": "", "rank": 3},
    "sintesi": {"value": "", "rank": 3}
  },
  "cadastral_pairs": [],
  "needs_review": false,
  "notes": []
}

OUTPUT: restituisci SOLO il JSON.
