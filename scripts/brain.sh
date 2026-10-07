#!/usr/bin/env bash
# Switch MIRA's brain by editing .env.
#   bash scripts/brain.sh groq gsk_xxx     # Groq cloud (fast, free tier), tools stay on this device
#   bash scripts/brain.sh groq             # keep the saved key
#   bash scripts/brain.sh local            # back to llama.cpp on this device
#   bash scripts/brain.sh groq gsk_xxx llama-3.1-8b-instant   # pick a model
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
set_kv() {  # key value
  if grep -qE "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi
}
case "${1:-}" in
  groq)
    set_kv JARVIS_PROVIDER groq
    [ -n "${2:-}" ] && set_kv JARVIS_GROQ_API_KEY "$2"
    [ -n "${3:-}" ] && set_kv JARVIS_GROQ_MODEL "$3"
    grep -qE '^JARVIS_GROQ_API_KEY=.+' .env || echo "warning: no API key saved yet (bash scripts/brain.sh groq gsk_...)"
    echo "Brain: Groq ($(grep -E '^JARVIS_GROQ_MODEL=' .env | tail -n 1 | cut -d= -f2)) — restart with scripts/termux/start.sh"
    ;;
  local|llamacpp)
    set_kv JARVIS_PROVIDER llamacpp
    echo "Brain: local llama.cpp — restart with scripts/termux/start.sh"
    ;;
  *) echo "usage: bash scripts/brain.sh groq [API_KEY] [MODEL] | local"; exit 1 ;;
esac
