#!/data/data/com.termux/files/usr/bin/bash
# Build llama.cpp on the phone, optimised for *this* CPU.
#
# The Termux package is a generic ARM build. Flagship phones have DOTPROD and
# I8MM instructions that make 4-bit models several times faster at reading
# the prompt; a native build switches them on. Takes 10–20 minutes. Keep the
# phone plugged in and the screen on.
#
#   bash scripts/termux/build-llama.sh
#
# start.sh prefers ~/llama.cpp/build/bin/llama-server when it exists.
set -euo pipefail
pkg install -y git cmake clang make >/dev/null
SRC="$HOME/llama.cpp"
if [ -f "$SRC/CMakeLists.txt" ]; then
  echo "==> Updating llama.cpp source"
  git -C "$SRC" pull --ff-only || true
else
  echo "==> Fetching llama.cpp source"
  rm -rf "$SRC"
  git clone --depth 1 https://github.com/ggml-org/llama.cpp "$SRC"
fi
echo "==> Configuring (native CPU optimisations on)"
cmake -S "$SRC" -B "$SRC/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=ON \
  -DGGML_OPENMP=OFF \
  -DLLAMA_CURL=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF
echo "==> Building llama-server and llama-bench (this is the slow part)"
cmake --build "$SRC/build" --config Release -j"$(nproc)" --target llama-server llama-bench
echo
echo "Done: $SRC/build/bin/llama-server"
"$SRC/build/bin/llama-server" --version 2>&1 | head -n 2
echo "Restart MIRA with  bash scripts/termux/start.sh  — it will use this build."
