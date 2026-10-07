#!/bin/bash
# Start the model server (Metal) and MIRA's web UI on this Mac.
#   bash scripts/mac/start.sh              # Ctrl-C stops both
#   JARVIS_CTX=32768 bash scripts/mac/start.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
PY="./.venv/bin/python"; [ -x "$PY" ] || PY="python3"

if [ ! -f .env ]; then
  echo "No .env yet. Run  bash scripts/mac/setup.sh  first."
  exit 1
fi
env_get() { grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d ' \r' || true; }
PROVIDER="${JARVIS_PROVIDER:-$(env_get JARVIS_PROVIDER)}"
if [ "$PROVIDER" = "groq" ] || [ "$PROVIDER" = "claude" ]; then
  echo "==> Brain: $PROVIDER (cloud). Starting the web UI only."
  exec caffeinate -i -s "$PY" -m jarvis web
fi

MODEL_PATH="${JARVIS_MODEL_PATH:-$(cat .jarvis-model-path 2>/dev/null || true)}"
if [ -z "$MODEL_PATH" ] || [ ! -f "$MODEL_PATH" ]; then
  echo "No model found. Run  bash scripts/mac/setup.sh  first (or set JARVIS_MODEL_PATH)."
  exit 1
fi
PORT="${JARVIS_LLM_PORT:-8080}"
CTX="${JARVIS_CTX:-16384}"
LOG="$HOME/.jarvis/llama-server.log"
mkdir -p "$HOME/.jarvis"

cleanup() { [ -n "${LLM_PID:-}" ] && kill "$LLM_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if curl -fs "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
  echo "==> llama-server already running on port $PORT"
else
  echo "==> Starting llama-server ($(basename "$MODEL_PATH"), ctx=$CTX, Metal)"
  EXTRA=""
  llama-server --help 2>&1 | grep -q -- "--cache-reuse" && EXTRA="--cache-reuse 256"
  # -ngl 99: every layer on the GPU. -np 1: one slot so the prompt cache is
  # never split. -fa on: flash attention is a win on Metal.
  caffeinate -i -s llama-server -m "$MODEL_PATH" --host 127.0.0.1 --port "$PORT" \
    -c "$CTX" -ngl 99 -np 1 -fa on --jinja $EXTRA >"$LOG" 2>&1 &
  LLM_PID=$!
  for i in $(seq 1 180); do
    if curl -fs "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then break; fi
    if ! kill -0 "$LLM_PID" 2>/dev/null; then
      echo "llama-server exited. Last log lines:"; tail -n 20 "$LOG"; exit 1
    fi
    sleep 1
  done
fi

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<このMacのIP>")"
TOKEN="$(env_get JARVIS_WEB_TOKEN)"
PORT_WEB="$(env_get JARVIS_WEB_PORT)"
echo "==> Starting MIRA web UI"
echo "    this Mac:   http://localhost:${PORT_WEB:-8765}/"
echo "    phone:      http://$IP:${PORT_WEB:-8765}/   token: ${TOKEN:-(none)}"
exec caffeinate -i -s "$PY" -m jarvis web
