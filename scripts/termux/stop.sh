#!/data/data/com.termux/files/usr/bin/bash
# Stop llama-server and the JARVIS web UI if they were left running.
pkill -f "python -m jarvis web" 2>/dev/null || true
pkill -f "llama-server" 2>/dev/null || true
command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock || true
echo "stopped"
