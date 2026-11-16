# Istruzioni di analisi Mnemos

## Pipeline

Segui un unico flusso per ogni PDF:

1. Conserva il PDF originale caricato.
2. Crea un PDF di lavoro ottimizzato e normalizza le rotazioni delle pagine.
3. Analizza il PDF di lavoro pagina per pagina con le librerie Python e il modello MiniCPM-OCR incluso nel progetto.
4. Per ogni pagina, Python scrive una micro memory con testo, contesto, evidenze e candidati estratti secondo le regole configurate.
5. Python consolida le micro memory in una global memory, mantenendo al massimo cinque candidati per campo.
6. Il modello Qwen locale legge la global memory e sceglie un candidate ID per ciascun campo presente. Non inventa né riscrive valori.
7. Python controlla che gli ID scelti esistano, applica validazioni e regole di coerenza, quindi scrive i risultati dell’analisi.

La lavorazione è un’unica pipeline coordinata dal backend. MiniCPM-OCR produce il testo; Python produce e salva le memorie e i candidati; Qwen svolge soltanto la selezione globale.

## Campi e regole

I campi attivi e le relative regole sono definiti in `docs/instructions/pipeline_rules.json`. Per aggiungere o modificare un campo, configurare etichetta, profilo, ruoli ammessi, istruzione di selezione e regole Python di estrazione e validazione. Il sistema non deve dipendere da un numero fisso di campi.

La global memory può includere fino a cinque candidati per campo. Il selettore può scegliere soltanto un ID presente nella memoria di quel campo. Se non esistono candidati, Python registra il campo come non rilevato senza chiedere al modello di inventare un valore.

## Evidenze e output

Ogni valore scritto deve risalire a un candidato generato da Python e includere pagina ed evidenza disponibili. Le normalizzazioni sono limitate ai formati esplicitamente configurati. Le sintesi, quando previste dalle regole del campo, sono composte da Python.
