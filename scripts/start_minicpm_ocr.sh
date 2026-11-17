#!/bin/zsh
set -euo pipefail

PROJECT_DIR=${0:A:h:h}
RUNTIME_DIR=${MINICPM_RUNTIME_DIR:-$PROJECT_DIR/models/minicpm-ocr}
SERVER=${MINICPM_LLAMA_SERVER:-$RUNTIME_DIR/llama.cpp-bin/llama-b11901/llama-server}
MODEL_DIR=${OCR_GGUF_DIR:-$RUNTIME_DIR/MiniCPM-OCR-1.0-gguf}
PORT=${DOC_AI_MINICPM_PORT:-18499}
SLEEP_IDLE_SECONDS=${DOC_AI_MINICPM_SLEEP_IDLE_SECONDS:-30}

[[ -x "$SERVER" ]] || { echo "llama-server non trovato: $SERVER" >&2; exit 1; }
[[ -f "$MODEL_DIR/MiniCPM-OCR-1_0-Q4_K_M.gguf" ]] || { echo "Modello MiniCPM-OCR Q4_K_M non trovato: $MODEL_DIR" >&2; exit 1; }
[[ -f "$MODEL_DIR/mmproj-model-f16-4x.gguf" ]] || { echo "mmproj MiniCPM-OCR non trovato: $MODEL_DIR" >&2; exit 1; }
[[ -f "$MODEL_DIR/dspark-MiniCPM-OCR-1_0-Q4_K_M.gguf" ]] || { echo "Modello DSpark Q4_K_M non trovato: $MODEL_DIR" >&2; exit 1; }

exec "$SERVER" \
  --model "$MODEL_DIR/MiniCPM-OCR-1_0-Q4_K_M.gguf" \
  --mmproj "$MODEL_DIR/mmproj-model-f16-4x.gguf" \
  --model-draft "$MODEL_DIR/dspark-MiniCPM-OCR-1_0-Q4_K_M.gguf" \
  --spec-type draft-dspark \
  --spec-draft-n-max 15 \
  --n-gpu-layers 99 \
  --gpu-layers-draft 99 \
  --flash-attn on \
  --ctx-size 8192 \
  --parallel 1 \
  --host 0.0.0.0 \
  --port "$PORT" \
  --sleep-idle-seconds "$SLEEP_IDLE_SECONDS" \
  --alias minicpm-ocr \
  --jinja \
  --reasoning off
