#!/data/data/com.termux/files/usr/bin/bash
# Start the local model server and JARVIS's web UI on the phone.
#   bash scripts/termux/start.sh            # foreground; Ctrl-C stops both
#   JARVIS_CTX=4096 bash scripts/termux/start.sh   # smaller context for low-RAM phones
set -euo pipefail
cd "$(dirname "$0")/../.."

MODEL_PATH="${JARVIS_MODEL_PATH:-$(cat .jarvis-model-path 2>/dev/null || true)}"
if [ -z "$MODEL_PATH" ] || [ ! -f "$MODEL_PATH" ]; then
  echo "No model found. Run  bash scripts/termux/setup.sh  first (or set JARVIS_MODEL_PATH)."
  exit 1
fi
PORT="${JARVIS_LLM_PORT:-8080}"
CTX="${JARVIS_CTX:-8192}"
# Use the performance cores only: on a 8–10 core phone the efficiency cores
# slow generation down if llama.cpp spreads across all of them.
NPROC="$(nproc)"
if [ -z "${JARVIS_THREADS:-}" ]; then
  if [ "$NPROC" -ge 8 ]; then JARVIS_THREADS=6; elif [ "$NPROC" -ge 4 ]; then JARVIS_THREADS=4; else JARVIS_THREADS="$NPROC"; fi
fi
THREADS="$JARVIS_THREADS"
LOG="$HOME/.jarvis/llama-server.log"
mkdir -p "$HOME/.jarvis"

# Keep the CPU awake while JARVIS runs (needs the Termux:API app; harmless otherwise).
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock || true

cleanup() {
  [ -n "${LLM_PID:-}" ] && kill "$LLM_PID" 2>/dev/null || true
  command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock || true
}
trap cleanup EXIT INT TERM

if curl -fs "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
  echo "==> llama-server already running on port $PORT"
else
  echo "==> Starting llama-server ($(basename "$MODEL_PATH"), ctx=$CTX, threads=$THREADS)"
  llama-server -m "$MODEL_PATH" --host 127.0.0.1 --port "$PORT" \
    -c "$CTX" -t "$THREADS" --jinja --flash-attn on >"$LOG" 2>&1 &
  LLM_PID=$!
  for i in $(seq 1 120); do
    if curl -fs "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then break; fi
    if ! kill -0 "$LLM_PID" 2>/dev/null; then
      echo "llama-server exited. Last log lines:"; tail -n 20 "$LOG"; exit 1
    fi
    sleep 1
  done
fi

echo "==> Starting JARVIS web UI"
exec python -m jarvis web
