#!/bin/zsh
set -euo pipefail

PROJECT_DIR=${0:A:h}
cd "$PROJECT_DIR"

echo "Avvio Mnemos..."
DOC_AI_MODEL_PATH=${DOC_AI_MODEL_PATH:-$PROJECT_DIR/models/Qwen3-4B-Instruct-2507-4bit}
export DOC_AI_MODEL_PATH

wait_for_service() {
  local url=$1
  local label=$2
  for attempt in {1..240}; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$label pronto."
      return 0
    fi
    sleep 1
  done
  echo "Avvio di $label non completato. Controlla i log in /tmp/mnemos-*.log." >&2
  return 1
}

if [[ -f "$DOC_AI_MODEL_PATH/config.json" ]] && ! curl -fsS http://127.0.0.1:8081/v1/models >/dev/null 2>&1; then
  nohup "$PROJECT_DIR/scripts/start_mlx.sh" > /tmp/mnemos-mlx.log 2>&1 &
  echo $! > /tmp/mnemos-mlx.pid
  wait_for_service http://127.0.0.1:8081/v1/models "Qwen / MLX" || exit 1
elif [[ ! -f "$DOC_AI_MODEL_PATH/config.json" ]]; then
  echo "Modello MLX non trovato in $DOC_AI_MODEL_PATH. Scarica Qwen3-4B-Instruct-2507-4bit o configura DOC_AI_MODEL_PATH." >&2
  exit 1
fi

if ! curl -fsS http://127.0.0.1:18499/health >/dev/null 2>&1; then
  nohup "$PROJECT_DIR/scripts/start_minicpm_ocr.sh" > /tmp/mnemos-minicpm-ocr.log 2>&1 &
  echo $! > /tmp/mnemos-minicpm-ocr.pid
  wait_for_service http://127.0.0.1:18499/health "MiniCPM-OCR" || exit 1
fi

docker compose up -d

wait_for_service http://127.0.0.1:8000/api/health "Backend" || exit 1
echo "Sistema pronto: http://localhost:5174"
open http://localhost:5174
