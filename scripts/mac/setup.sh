#!/bin/bash
# One-time setup for running MIRA on a Mac (Apple Silicon or Intel).
#
#   git clone https://github.com/S66Bell/AI-.git mira && cd mira
#   bash scripts/mac/setup.sh
#
# Installs llama.cpp (Metal-accelerated) and Python via Homebrew, creates a
# virtualenv with MIRA's dependencies, downloads a model sized for this
# Mac's RAM, and writes a .env that lets your phone connect over Wi-Fi.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
MODELS="$HOME/models"
mkdir -p "$MODELS" "$HOME/.jarvis"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew が必要です。先に https://brew.sh の 1 行コマンドでインストールしてから、もう一度実行してください。"
  exit 1
fi

echo "==> Installing llama.cpp and Python (Homebrew)"
brew list llama.cpp >/dev/null 2>&1 || brew install llama.cpp
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
PY="$(brew --prefix python@3.12)/bin/python3.12"

echo "==> Creating virtualenv and installing MIRA's dependencies"
[ -d "$ROOT/.venv" ] || "$PY" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q --upgrade pip
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"

# Model by RAM (Metal shares system memory; leave room for macOS and apps).
RAM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
if [ -z "${JARVIS_MODEL_SIZE:-}" ]; then
  if   [ "$RAM_GB" -ge 40 ]; then JARVIS_MODEL_SIZE=32b
  elif [ "$RAM_GB" -ge 20 ]; then JARVIS_MODEL_SIZE=14b
  elif [ "$RAM_GB" -ge 12 ]; then JARVIS_MODEL_SIZE=7b
  else                            JARVIS_MODEL_SIZE=3b
  fi
  echo "==> ${RAM_GB}GB RAM → model size $JARVIS_MODEL_SIZE (override with JARVIS_MODEL_SIZE=3b|7b|14b|32b)"
fi
case "$JARVIS_MODEL_SIZE" in
  3b)  FILE="qwen2.5-3b-instruct-q4_k_m.gguf";    REPO="Qwen/Qwen2.5-3B-Instruct-GGUF" ;;      # ~2.0GB
  7b)  FILE="Qwen2.5-7B-Instruct-Q4_K_M.gguf";    REPO="bartowski/Qwen2.5-7B-Instruct-GGUF" ;; # ~4.7GB
  14b) FILE="Qwen2.5-14B-Instruct-Q4_K_M.gguf";   REPO="bartowski/Qwen2.5-14B-Instruct-GGUF" ;;# ~9.0GB
  32b) FILE="Qwen2.5-32B-Instruct-Q4_K_M.gguf";   REPO="bartowski/Qwen2.5-32B-Instruct-GGUF" ;;# ~20GB
  *) echo "Unknown JARVIS_MODEL_SIZE=$JARVIS_MODEL_SIZE"; exit 1 ;;
esac
if [ ! -f "$MODELS/$FILE" ]; then
  echo "==> Downloading $FILE (one-time)"
  curl -L --fail --retry 5 -C - -o "$MODELS/$FILE.part" "https://huggingface.co/$REPO/resolve/main/$FILE"
  mv "$MODELS/$FILE.part" "$MODELS/$FILE"
else
  echo "==> Model already present: $MODELS/$FILE"
fi
echo "$MODELS/$FILE" > "$ROOT/.jarvis-model-path"

if [ ! -f "$ROOT/.env" ]; then
  echo "==> Writing .env"
  TOKEN="$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 24)"
  cat > "$ROOT/.env" <<ENV
JARVIS_PROVIDER=llamacpp
JARVIS_OPENAI_BASE_URL=http://127.0.0.1:8080/v1
JARVIS_OPENAI_MODEL=local
# Reachable from your phone on the same Wi-Fi; the token keeps others out.
JARVIS_WEB_HOST=0.0.0.0
JARVIS_WEB_PORT=8765
JARVIS_WEB_TOKEN=$TOKEN
JARVIS_NAME=MIRA
JARVIS_USER_NAME=
JARVIS_DATA_DIR=~/.jarvis
JARVIS_HISTORY_TURNS=30
JARVIS_LEARN_IDLE=30
ENV
fi

cat <<MSG

Setup complete.
  Start:   bash scripts/mac/start.sh
  Phone:   open the URL it prints (same Wi-Fi) and enter the token from .env
  Always-on at login:  bash scripts/mac/install-service.sh
MSG
