#!/bin/zsh
set -euo pipefail

PROJECT_DIR=${0:A:h}
cd "$PROJECT_DIR"

echo "Avvio Mnemos..."
SUPERVISOR_PID_FILE=/tmp/mnemos-model-supervisor.pid
SUPERVISOR_TOKEN_FILE=/tmp/mnemos-model-supervisor.token

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

SUPERVISOR_READY=false
if [[ -f "$SUPERVISOR_PID_FILE" && -f "$SUPERVISOR_TOKEN_FILE" ]]; then
  DOC_AI_MODEL_SUPERVISOR_TOKEN=$(cat "$SUPERVISOR_TOKEN_FILE")
  export DOC_AI_MODEL_SUPERVISOR_TOKEN
  if curl -fsS -H "X-Mnemos-Token: $DOC_AI_MODEL_SUPERVISOR_TOKEN" \
    http://127.0.0.1:18500/status >/dev/null 2>&1; then
    SUPERVISOR_READY=true
  fi
fi

if [[ "$SUPERVISOR_READY" != true ]]; then
  LAUNCH_DOMAIN="gui/$(id -u)"
  launchctl bootout "$LAUNCH_DOMAIN/com.mnemos.model-supervisor" >/dev/null 2>&1 || true
  if [[ -f "$SUPERVISOR_PID_FILE" ]]; then
    OLD_SUPERVISOR_PID=$(cat "$SUPERVISOR_PID_FILE")
    if [[ "$OLD_SUPERVISOR_PID" == <-> ]] && \
      ps -p "$OLD_SUPERVISOR_PID" -o command= 2>/dev/null | rg -Fq "model_supervisor.py"; then
      kill "$OLD_SUPERVISOR_PID" 2>/dev/null || true
      for attempt in {1..240}; do
        kill -0 "$OLD_SUPERVISOR_PID" 2>/dev/null || break
        sleep 0.25
      done
    fi
    rm -f "$SUPERVISOR_PID_FILE"
  fi
  "$PROJECT_DIR/scripts/stop_legacy_model_servers.sh"
  umask 077
  DOC_AI_MODEL_SUPERVISOR_TOKEN=$(openssl rand -hex 32)
  export DOC_AI_MODEL_SUPERVISOR_TOKEN
  print -r -- "$DOC_AI_MODEL_SUPERVISOR_TOKEN" > "$SUPERVISOR_TOKEN_FILE"
  python3 "$PROJECT_DIR/scripts/install_model_supervisor.py" >/dev/null
  launchctl bootstrap "$LAUNCH_DOMAIN" \
    "$HOME/Library/LaunchAgents/com.mnemos.model-supervisor.plist"
  launchctl kickstart -k "$LAUNCH_DOMAIN/com.mnemos.model-supervisor"
  launchctl print "$LAUNCH_DOMAIN/com.mnemos.model-supervisor" >/dev/null
  echo "launchd" > "$SUPERVISOR_PID_FILE"
  for attempt in {1..30}; do
    if curl -fsS -H "X-Mnemos-Token: $DOC_AI_MODEL_SUPERVISOR_TOKEN" \
      http://127.0.0.1:18500/status >/dev/null 2>&1; then
      SUPERVISOR_READY=true
      break
    fi
    sleep 1
  done
fi
if [[ "$SUPERVISOR_READY" != true ]]; then
  echo "Il supervisore dei modelli non è partito. Controlla /tmp/mnemos-model-supervisor.log." >&2
  exit 1
fi

docker compose up -d --build

wait_for_service http://127.0.0.1:8000/api/health "Backend" || exit 1
echo "Sistema pronto: http://localhost:5174"
echo "MiniCPM e Qwen verranno caricati in fasi distinte, mai insieme."
open http://localhost:5174
