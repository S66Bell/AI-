#!/data/data/com.termux/files/usr/bin/bash
# One-time setup for running JARVIS on an Android phone inside Termux.
#
#   1. Install Termux from F-Droid (the Play Store build is outdated):
#      https://f-droid.org/packages/com.termux/
#   2. In Termux:  pkg install git && git clone <this repo> && cd <repo>
#   3. bash scripts/termux/setup.sh
#
# What it does: installs Python + llama.cpp, installs JARVIS's (pure-Python)
# dependencies, downloads a small tool-calling model from Hugging Face, and
# writes a .env that points JARVIS at the local llama-server.
set -euo pipefail

cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
MODELS="$HOME/models"
mkdir -p "$MODELS"

# Pick a model. Qwen2.5 Instruct models are small, support tool calling, and
# handle Japanese well. The size is chosen from the phone's RAM unless you
# override it with:  JARVIS_MODEL_SIZE=1.5b|3b|7b
RAM_MB="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
if [ -z "${JARVIS_MODEL_SIZE:-}" ]; then
  if   [ "$RAM_MB" -ge 10000 ]; then JARVIS_MODEL_SIZE=7b     # e.g. Galaxy S26 (12GB)
  elif [ "$RAM_MB" -ge 5500 ];  then JARVIS_MODEL_SIZE=3b
  else                               JARVIS_MODEL_SIZE=1.5b
  fi
  echo "==> Detected ${RAM_MB}MB RAM → model size $JARVIS_MODEL_SIZE (override with JARVIS_MODEL_SIZE=...)"
fi
SIZE="$JARVIS_MODEL_SIZE"
case "$SIZE" in
  1.5b) FILE="qwen2.5-1.5b-instruct-q4_k_m.gguf"; REPO="Qwen/Qwen2.5-1.5B-Instruct-GGUF" ;;   # ~1.1GB
  3b)   FILE="qwen2.5-3b-instruct-q4_k_m.gguf";   REPO="Qwen/Qwen2.5-3B-Instruct-GGUF" ;;     # ~2.0GB
  # The official 7B GGUF is split in two files; bartowski's is a single file.
  7b)   FILE="Qwen2.5-7B-Instruct-Q4_K_M.gguf";   REPO="bartowski/Qwen2.5-7B-Instruct-GGUF" ;; # ~4.7GB
  *) echo "Unknown JARVIS_MODEL_SIZE=$SIZE (use 1.5b, 3b or 7b)"; exit 1 ;;
esac
URL="https://huggingface.co/$REPO/resolve/main/$FILE"

echo "==> Updating Termux (fixes 'CANNOT LINK EXECUTABLE' errors from half-upgraded packages)"
export DEBIAN_FRONTEND=noninteractive
APT_OPTS=(-y -o Dpkg::Options::=--force-confnew)
pkg update -y || true
apt full-upgrade "${APT_OPTS[@]}"

echo "==> Installing packages"
apt install "${APT_OPTS[@]}" python git curl termux-api clang cmake make

echo "==> Installing llama.cpp"
if ! command -v llama-server >/dev/null 2>&1; then
  # Termux ships a prebuilt package (CPU). For GPU offload on Adreno phones
  # you can additionally try:  pkg install llama-cpp-backend-vulkan
  if apt install "${APT_OPTS[@]}" llama-cpp; then
    echo "    installed from the Termux repo"
  else
    echo "    building from source (this takes a while on a phone)"
    SRC="$HOME/llama.cpp"
    # A failed earlier clone can leave an empty directory behind.
    [ -f "$SRC/CMakeLists.txt" ] || { rm -rf "$SRC"; git clone --depth 1 https://github.com/ggml-org/llama.cpp "$SRC"; }
    cmake -S "$SRC" -B "$SRC/build" -DGGML_NATIVE=ON -DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release
    cmake --build "$SRC/build" --config Release -j"$(nproc)" --target llama-server
    mkdir -p "$PREFIX/bin"
    ln -sf "$SRC/build/bin/llama-server" "$PREFIX/bin/llama-server"
  fi
fi

echo "==> Installing JARVIS dependencies"
pip install --upgrade pip >/dev/null
pip install -r "$ROOT/requirements.txt"

if [ ! -f "$MODELS/$FILE" ]; then
  echo "==> Downloading model $FILE (one-time; Wi-Fi recommended)"
  curl -L --fail --retry 5 -C - -o "$MODELS/$FILE.part" "$URL"
  mv "$MODELS/$FILE.part" "$MODELS/$FILE"
else
  echo "==> Model already present: $MODELS/$FILE"
fi

if [ ! -f "$ROOT/.env" ]; then
  echo "==> Writing .env"
  cat > "$ROOT/.env" <<ENV
JARVIS_PROVIDER=llamacpp
JARVIS_OPENAI_BASE_URL=http://127.0.0.1:8080/v1
JARVIS_OPENAI_MODEL=local
JARVIS_WEB_HOST=127.0.0.1
JARVIS_WEB_PORT=8765
JARVIS_USER_NAME=Sir
JARVIS_NAME=JARVIS
JARVIS_DATA_DIR=~/.jarvis
JARVIS_AGENT_MAX_STEPS=30
ENV
fi

# Remember which model start.sh should load.
echo "$MODELS/$FILE" > "$ROOT/.jarvis-model-path"

# Give the phone's storage to JARVIS's file tools (asks for permission once).
termux-setup-storage || true

cat <<MSG

Setup complete.
  Start JARVIS:   bash scripts/termux/start.sh
  Then open:      http://localhost:8765  (add it to your home screen)
MSG
