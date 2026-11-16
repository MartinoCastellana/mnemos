#!/bin/zsh
set -euo pipefail

PROJECT_DIR=${0:A:h}
cd "$PROJECT_DIR"

echo "Arresto Mnemos..."
docker compose down
pkill -f 'mlx_vlm.server' 2>/dev/null || true
if [[ -f /tmp/mnemos-minicpm-ocr.pid ]]; then
  kill "$(cat /tmp/mnemos-minicpm-ocr.pid)" 2>/dev/null || true
  rm -f /tmp/mnemos-minicpm-ocr.pid
fi
echo "Backend, frontend, database, MLX e MiniCPM-OCR sono stati arrestati."
sleep 2
