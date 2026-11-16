# Mnemos

Mnemos acquisisce fascicoli PDF, estrae il testo, applica una pipeline locale e mostra i risultati con le relative evidenze e il registro delle operazioni.

## Avvio

Su macOS avvia i modelli locali e i servizi con:

```bash
./AVVIA_FASCICOLO_AI.command
```

Per avviare soltanto backend e interfaccia:

```bash
docker compose up --build
```

In questo caso avvia anche MiniCPM-OCR e MLX separatamente prima di elaborare documenti.

- Interfaccia: http://localhost:5174
- API: http://localhost:8000/docs
- Stato: http://localhost:8000/api/health

I documenti e i risultati restano nel database e nello spazio di archiviazione locale.

## Pipeline

La pipeline è monolitica: caricamento del PDF originale, creazione di un PDF di lavoro in bianco e nero a 120 DPI, stima deterministica dell’orientamento pagina per pagina con Tesseract OSD e correzione solo quando la confidenza supera la soglia configurata. Le pagine con orientamento incerto restano invariate e l’esito viene registrato nell’audit. MiniCPM-OCR analizza poi una pagina alla volta; Python scrive una micro memory per pagina e consolida i candidati. Qwen locale legge la global memory (fino a cinque candidati per campo) e sceglie gli ID; Python valida la scelta e scrive i risultati finali. L’originale resta conservato.

I campi e le relative regole sono configurati in `docs/instructions/pipeline_rules.json`. Aggiungi una voce in `fields` e le sue regole di selezione in `profiles` per introdurre campi dinamici.

## Modello locale

MiniCPM-OCR usa il modello GGUF in `models/minicpm-ocr/MiniCPM-OCR-1.0-gguf`, servito localmente da llama.cpp sulla porta `18499`. Il selettore usa `mlx-community/Qwen3-4B-Instruct-2507-4bit` (Q4), servito da MLX sulla porta `8081`; il percorso dei pesi si imposta con `DOC_AI_MODEL_PATH`.

Per scaricare Qwen3 Q4 nella directory già configurata:

```bash
uvx --from huggingface_hub hf download mlx-community/Qwen3-4B-Instruct-2507-4bit --local-dir models/Qwen3-4B-Instruct-2507-4bit
```

Per avviare MLX, imposta il percorso del modello e poi esegui:

```bash
DOC_AI_MODEL_PATH=/percorso/al/modello ./scripts/start_mlx.sh
```

Avvia MiniCPM-OCR con `./scripts/start_minicpm_ocr.sh`. Il backend usa le dipendenze dichiarate in `backend/pyproject.toml`; il codice Python riutilizzato da MiniCPM-OCR è incluso in `MiniCPM-OCR/sdk/minicpmvocr`. Per un ambiente Python locale installa il progetto con `pip install -e ./backend`. Il backend Docker installa PyTorch dalla distribuzione CPU e usa PP-DocLayoutV3 tramite Transformers; i pesi di layout vengono scaricati nello storage persistente.

Puoi configurare `DOC_AI_MODEL_NAME`, `DOC_AI_MODEL_ENDPOINT`, `DOC_AI_MINICPM_MODEL_NAME` e `DOC_AI_MINICPM_ENDPOINT` nell'ambiente del backend. L’elaborazione richiede entrambi i motori locali.

## MiniCPM-OCR

La cartella `MiniCPM-OCR/` contiene solo il codice Python riutilizzato dalla pipeline e la relativa licenza. Modelli e binari di runtime sono in `models/minicpm-ocr/`; tutte le dipendenze Python sono dichiarate dal progetto in `backend/pyproject.toml`.
