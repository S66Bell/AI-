#!/bin/bash
# Stop MIRA and the model server (also the background service if installed).
launchctl bootout "gui/$(id -u)/com.mira.assistant" 2>/dev/null || true
pkill -f "jarvis web" 2>/dev/null || true
pkill -f "llama-server" 2>/dev/null || true
echo "stopped"
