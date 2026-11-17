#!/bin/zsh
set -euo pipefail

PROJECT_DIR=${0:A:h}
cd "$PROJECT_DIR"

echo "Arresto Mnemos..."
LAUNCH_DOMAIN="gui/$(id -u)"
launchctl kill SIGTERM "$LAUNCH_DOMAIN/com.mnemos.model-supervisor" >/dev/null 2>&1 || true
for attempt in {1..240}; do
  if ! curl -sS --max-time 1 http://127.0.0.1:18500/status >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if [[ -f /tmp/mnemos-model-supervisor.pid ]]; then
  rm -f /tmp/mnemos-model-supervisor.pid /tmp/mnemos-model-supervisor.token
fi
"$PROJECT_DIR/scripts/stop_legacy_model_servers.sh"
docker compose down
echo "Backend, frontend, database, MLX e MiniCPM-OCR sono stati arrestati."
sleep 2
