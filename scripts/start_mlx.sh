#!/bin/zsh
set -euo pipefail

PROJECT_DIR=${0:A:h:h}
MODEL_DIR=${DOC_AI_MODEL_PATH:-$PROJECT_DIR/models/Qwen3-4B-Instruct-2507-4bit}

if [[ -z "$MODEL_DIR" ]]; then
  echo "Imposta DOC_AI_MODEL_PATH con il percorso del modello MLX da avviare." >&2
  exit 1
fi

if [[ ! -f "$MODEL_DIR/config.json" ]]; then
  echo "Configurazione del modello non trovata in $MODEL_DIR" >&2
  exit 1
fi

exec "$PROJECT_DIR/.venv-mlx/bin/python" -m mlx_lm server \
  --host 0.0.0.0 \
  --port 8081 \
  --model "$MODEL_DIR"
