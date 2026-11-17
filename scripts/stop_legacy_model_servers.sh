#!/bin/zsh
set -euo pipefail

stop_if_mnemos_pid() {
  local pid_file=$1
  local marker=$2
  [[ -f "$pid_file" ]] || return 0
  local pid
  pid=$(cat "$pid_file")
  if [[ "$pid" == <-> ]] && ps -p "$pid" -o command= 2>/dev/null | rg -Fq "$marker"; then
    kill "$pid" 2>/dev/null || true
    for attempt in {1..40}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

stop_if_mnemos_pid /tmp/mnemos-mlx.pid "mlx_lm server"
stop_if_mnemos_pid /tmp/mnemos-minicpm-ocr.pid "llama-server"
