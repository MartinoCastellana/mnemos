# Mnemos

Mnemos acquisisce fascicoli PDF, estrae il testo, applica una pipeline locale e mostra i risultati con le relative evidenze e il registro delle operazioni.

## Avvio

Su macOS avvia Mnemos con il supervisore dei modelli e i servizi:

```bash
./AVVIA_FASCICOLO_AI.command
```

Il supervisore parte senza caricare modelli. Durante una run carica MiniCPM per l'OCR, lo scarica completamente e poi carica Qwen per selezionare i candidati globali. Al termine scarica anche Qwen; i due modelli non sono residenti insieme.

Il solo `docker compose up --build` avvia backend e interfaccia ma non il supervisore host; in questa configurazione l'API rifiuta l'elaborazione, così non carica i modelli fuori sequenza.

- Interfaccia: http://localhost:5174
- API: http://localhost:8000/docs
- Stato: http://localhost:8000/api/health

I documenti e i risultati restano nel database e nello spazio di archiviazione locale.

## Pipeline

La pipeline crea un PDF di lavoro a colori a 120 DPI e valuta deterministicamente l'orientamento pagina per pagina. MiniCPM-OCR analizza una pagina alla volta; Python scrive una micro memory e prepara fino a cinque candidati per campo. Dopo aver scaricato MiniCPM, Qwen sceglie gli ID dei candidati dalla memoria globale. Python convalida ID, confidence e regole del campo, poi scrive i risultati; se Qwen non restituisce una scelta valida, il fallback Python preferisce il valore identico estratto più volte e usa confidence semantica e OCR come spareggi. L'originale resta conservato.

I campi e le relative regole sono configurati in `docs/instructions/pipeline_rules.json`. Aggiungi una voce in `fields` e le sue regole di selezione in `profiles` per introdurre campi dinamici.

## Modelli locali

MiniCPM-OCR usa il modello GGUF Q4_K_M in `models/minicpm-ocr/MiniCPM-OCR-1.0-gguf`, servito da llama.cpp sulla porta `18499`; il modello draft DSpark è Q4_K_M e il proiettore multimodale resta F16. Qwen3 4B Instruct 2507 usa la quantizzazione MLX a 4 bit in `models/Qwen3-4B-Instruct-2507-4bit`, servito sulla porta `8081`. Il supervisore avvia i modelli in fasi esclusive e scarica ciascuno prima di caricare l'altro.

`scripts/start_mlx.sh` e `scripts/start_minicpm_ocr.sh` sono avviati dal supervisore; non lanciarli manualmente durante una run Mnemos. Il supervisore host usa Python standard, genera un token locale a ogni avvio e lo passa al backend Docker. Per un ambiente Python locale installa il progetto con `pip install -e ./backend`. Il backend Docker installa PyTorch CPU e usa PP-DocLayoutV3 tramite Transformers; i pesi del layout vengono scaricati nello storage persistente.

Puoi configurare `DOC_AI_MODEL_NAME`, `DOC_AI_MODEL_ENDPOINT`, `DOC_AI_MINICPM_MODEL_NAME` e `DOC_AI_MINICPM_ENDPOINT` nell'ambiente del backend.

## MiniCPM-OCR

La cartella `MiniCPM-OCR/` contiene solo il codice Python riutilizzato dalla pipeline e la relativa licenza. Modelli e binari di runtime sono in `models/minicpm-ocr/`; tutte le dipendenze Python sono dichiarate dal progetto in `backend/pyproject.toml`.
