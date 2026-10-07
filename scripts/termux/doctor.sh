#!/data/data/com.termux/files/usr/bin/bash
# Collects everything needed to debug "JARVIS doesn't start" on a phone.
# Run it and paste the whole output:   bash scripts/termux/doctor.sh
cd "$(dirname "$0")/../.."
echo "=== JARVIS doctor ==="
echo "date: $(date)"
echo "repo: $(pwd)  branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null)  commit: $(git rev-parse --short HEAD 2>/dev/null)"
echo "ram: $(awk '/MemTotal/ {printf "%d MB total", $2/1024}' /proc/meminfo), $(awk '/MemAvailable/ {printf "%d MB free", $2/1024}' /proc/meminfo)   cores: $(nproc)"
echo
echo "--- tools"
for t in python pip curl git llama-server termux-wake-lock; do
  if command -v "$t" >/dev/null 2>&1; then echo "  $t: $(command -v "$t")"; else echo "  $t: MISSING"; fi
done
python --version 2>&1 | sed 's/^/  /'
llama-server --version 2>&1 | head -n 2 | sed 's/^/  /'
echo
echo "--- python packages"
python - <<'PY' 2>&1 | sed 's/^/  /'
import importlib
for m in ("dotenv", "requests", "rich", "prompt_toolkit"):
    try:
        importlib.import_module(m); print(m, "ok")
    except Exception as e:
        print(m, "FAILED:", e)
try:
    import jarvis, jarvis.web, jarvis.backends.openai_compat
    print("jarvis", jarvis.__version__, "imports ok")
except Exception as e:
    import traceback; traceback.print_exc()
PY
echo
echo "--- model"
MP="$(cat .jarvis-model-path 2>/dev/null || true)"
echo "  .jarvis-model-path: ${MP:-<missing>}"
[ -n "$MP" ] && ls -la "$MP" 2>&1 | sed 's/^/  /'
ls -la "$HOME/models" 2>/dev/null | sed 's/^/  /'
echo
echo "--- .env"
[ -f .env ] && sed 's/^\(JARVIS_WEB_TOKEN=\).*/\1<hidden>/; s/^\(ANTHROPIC_API_KEY=\).*/\1<hidden>/' .env | sed 's/^/  /' || echo "  <no .env>"
echo
echo "--- ports"
if curl -fs --max-time 3 http://127.0.0.1:8080/v1/models >/dev/null 2>&1; then echo "  llama-server :8080 → answering"; else echo "  llama-server :8080 → NOT answering"; fi
if curl -fs --max-time 3 http://127.0.0.1:8765/api/state 2>/dev/null; then echo; echo "  jarvis web :8765 → answering"; else echo "  jarvis web :8765 → NOT answering"; fi
echo
echo "--- processes"
ps -ef 2>/dev/null | grep -E "llama-server|jarvis" | grep -v grep | sed 's/^/  /' || true
echo
echo "--- web log (last 25 lines)"
tail -n 25 "$HOME/.jarvis/web.log" 2>/dev/null | sed 's/^/  /' || echo "  <no log>"
echo
echo "--- llama-server log (last 25 lines)"
tail -n 25 "$HOME/.jarvis/llama-server.log" 2>/dev/null | sed 's/^/  /' || echo "  <no log>"
echo
echo "--- quick web start test (5s)"
( python -m jarvis web --port 8799 >"$HOME/.jarvis/web-test.log" 2>&1 & echo $! > /tmp/jarvis-doctor.pid ); sleep 5
if curl -fs --max-time 3 http://127.0.0.1:8799/api/state >/dev/null 2>&1; then echo "  web server starts fine"; else echo "  web server FAILED to start:"; sed 's/^/    /' "$HOME/.jarvis/web-test.log"; fi
kill "$(cat /tmp/jarvis-doctor.pid)" 2>/dev/null || true
echo "=== end ==="
