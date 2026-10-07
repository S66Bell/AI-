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
# Prefer a native build (scripts/termux/build-llama.sh) over the generic package.
LLAMA_SERVER="llama-server"
[ -x "$HOME/llama.cpp/build/bin/llama-server" ] && LLAMA_SERVER="$HOME/llama.cpp/build/bin/llama-server"
CTX="${JARVIS_CTX:-8192}"
# Threads: measured on a Galaxy S26 with scripts/termux/bench.sh, using all
# 8 visible cores was fastest for both prompt reading and generation
# (109 vs 56 tok/s at 6 threads). Override with JARVIS_THREADS=N.
NPROC="$(nproc)"
THREADS="${JARVIS_THREADS:-$(( NPROC > 8 ? 8 : NPROC ))}"
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
  # --cache-reuse lets the server keep already-processed prompt chunks even
  # when something earlier in the prompt changed: the difference between
  # re-reading a few hundred tokens and the whole conversation every turn.
  EXTRA=""
  "$LLAMA_SERVER" --help 2>&1 | grep -q -- "--cache-reuse" && EXTRA="--cache-reuse 256"
  echo "    using $LLAMA_SERVER"
  # -np 1: one slot. Several slots would process requests concurrently on a
  # phone CPU (each one crawling) and each slot has its own cache, so the
  # chat kept landing on a cold slot and re-reading the whole prompt.
  # -fa off: llama-server turns flash attention on automatically, llama-bench
  # does not; on this phone's CPU the server read prompts several times
  # slower than the bench with it on. Override with JARVIS_FA=on to compare.
  FA="${JARVIS_FA:-off}"
  "$LLAMA_SERVER" -m "$MODEL_PATH" --host 127.0.0.1 --port "$PORT" \
    -c "$CTX" -t "$THREADS" -np 1 -fa "$FA" --jinja $EXTRA >"$LOG" 2>&1 &
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
