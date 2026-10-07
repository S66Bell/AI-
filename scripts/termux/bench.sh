#!/data/data/com.termux/files/usr/bin/bash
# Raw model speed on this phone, independent of MIRA.
#
#   bash scripts/termux/bench.sh                # 3B model if present, else the configured one
#   JARVIS_MODEL_PATH=~/models/x.gguf bash scripts/termux/bench.sh
#
# Runs llama-bench for the Termux package build and the native build (if
# built) with 2/4/6/8 threads. pp = prompt reading, tg = text generation,
# both in tokens per second. Charge the phone above 50 %, turn off power
# saving and let it cool down first — otherwise the numbers mean nothing.
set -uo pipefail
cd "$(dirname "$0")/../.."
MODEL="${JARVIS_MODEL_PATH:-}"
[ -z "$MODEL" ] && [ -f "$HOME/models/qwen2.5-3b-instruct-q4_k_m.gguf" ] && MODEL="$HOME/models/qwen2.5-3b-instruct-q4_k_m.gguf"
[ -z "$MODEL" ] && MODEL="$(cat .jarvis-model-path 2>/dev/null || true)"
if [ -z "$MODEL" ] || [ ! -f "$MODEL" ]; then echo "No model found (set JARVIS_MODEL_PATH)"; exit 1; fi

echo "=== MIRA bench: $(basename "$MODEL") ==="
command -v termux-battery-status >/dev/null 2>&1 && termux-battery-status 2>/dev/null | grep -E '"percentage"|"status"|"temperature"' | sed 's/^/  battery/' || true
pkill -f llama-server 2>/dev/null && echo "  (stopped the running llama-server so it doesn't skew the result)" && sleep 2

run_one() {  # $1 = label, $2 = llama-bench binary
  [ -x "$2" ] || { echo "--- $1: not available"; return; }
  echo "--- $1 ($2)"
  "$2" -m "$MODEL" -p 256 -n 32 -t 2,4,6,8 -r 1 2>/dev/null | grep -E '^\|' | grep -vE 'model|---'
}
run_one "termux package" "$PREFIX/bin/llama-bench"
run_one "native build"   "$HOME/llama.cpp/build/bin/llama-bench"
echo
echo "pp256 = prompt reading, tg32 = generation (tokens/s). Higher is better."
echo "Good for this phone: pp > 100, tg > 15 (3B). Below pp 30: throttled, power saving, or wrong build."
