#!/data/data/com.termux/files/usr/bin/bash
# Find out which llama-server setting makes prompt reading slow on this phone.
# Starts the server several times with different flags, sends the same
# ~1500-token prompt, and prints the measured tokens/s for each variant.
#
#   bash scripts/termux/bench-server.sh
#   JARVIS_MODEL_PATH=~/models/x.gguf bash scripts/termux/bench-server.sh
set -uo pipefail
cd "$(dirname "$0")/../.."
MODEL="${JARVIS_MODEL_PATH:-}"
[ -z "$MODEL" ] && [ -f "$HOME/models/qwen2.5-3b-instruct-q4_k_m.gguf" ] && MODEL="$HOME/models/qwen2.5-3b-instruct-q4_k_m.gguf"
[ -z "$MODEL" ] && MODEL="$(cat .jarvis-model-path 2>/dev/null || true)"
[ -f "$MODEL" ] || { echo "No model found (set JARVIS_MODEL_PATH)"; exit 1; }
SERVER="$HOME/llama.cpp/build/bin/llama-server"; [ -x "$SERVER" ] || SERVER="llama-server"
PORT=8099
THREADS="${JARVIS_THREADS:-8}"
pkill -f "llama-server" 2>/dev/null && sleep 2

PROMPT_FILE="$HOME/.jarvis/bench-prompt.json"
python - "$PROMPT_FILE" <<'PY'
import json, sys
text = ("あなたはMIRA。ユーザーの親友みたいなAI。日本語でフランクに話す。ツールを使って実際に作業する。" * 60)
json.dump({"prompt": text + "\n\n質問: 今日の気分は?\n答え:", "n_predict": 16, "temperature": 0}, open(sys.argv[1], "w"), ensure_ascii=False)
PY

run_variant() {  # $1 = label, rest = extra server flags
  local label="$1"; shift
  echo "--- $label"
  "$SERVER" -m "$MODEL" --host 127.0.0.1 --port $PORT -t "$THREADS" -np 1 "$@" >"$HOME/.jarvis/bench-server.log" 2>&1 &
  local pid=$!
  for i in $(seq 1 90); do curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
  if ! curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "  server failed to start:"; tail -n 5 "$HOME/.jarvis/bench-server.log" | sed 's/^/    /'; kill $pid 2>/dev/null; return
  fi
  for round in 1 2; do
    local t0=$(date +%s)
    curl -s --max-time 600 "http://127.0.0.1:$PORT/completion" -H 'Content-Type: application/json' -d @"$PROMPT_FILE" \
      | python -c "
import json,sys
try:
    d=json.load(sys.stdin); t=d.get('timings',{})
    print(f\"  round $round: prompt {t.get('prompt_n')} tok at {t.get('prompt_per_second',0):.1f} tok/s ({t.get('prompt_ms',0)/1000:.1f}s), gen {t.get('predicted_per_second',0):.1f} tok/s\")
except Exception as e:
    print('  round $round: no timings:', e)
"
    local t1=$(date +%s); echo "          wall $((t1-t0))s"
  done
  kill $pid 2>/dev/null; wait $pid 2>/dev/null
  sleep 2
}

run_variant "A: as start.sh (ctx 8192, fa auto, cache-reuse)" -c 8192 --jinja --cache-reuse 256
run_variant "B: flash-attn off"                                 -c 8192 --jinja --cache-reuse 256 -fa off
run_variant "C: fa off, no cache-reuse"                         -c 8192 --jinja -fa off
run_variant "D: fa off, ctx 4096"                               -c 4096 --jinja -fa off
run_variant "E: fa off, ctx 4096, batch 256"                    -c 4096 --jinja -fa off -b 256 -ub 256
echo
echo "Round 2 of each variant should be fast if the prompt cache works."
echo "Compare 'prompt ... tok/s' with llama-bench (~110 on this phone)."
