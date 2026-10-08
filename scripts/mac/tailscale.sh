#!/bin/bash
# Reach MIRA from anywhere, securely, with Tailscale (no port forwarding).
#
#   bash scripts/mac/tailscale.sh          # install, serve MIRA over HTTPS, lock LAN access
#   bash scripts/mac/tailscale.sh off      # stop serving and reopen LAN access
#
# After this, MIRA is reachable only by devices logged into YOUR Tailscale
# account, at https://<mac-name>.<tailnet>.ts.net — encrypted end to end,
# with a real certificate, so the phone can use the microphone and install
# MIRA to the home screen. The web UI is bound to 127.0.0.1 so nothing on
# the local Wi-Fi can reach it directly.
set -euo pipefail
cd "$(dirname "$0")/../.."

TS="$(command -v tailscale || true)"
[ -z "$TS" ] && [ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ] && TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
PORT="$(grep -E '^JARVIS_WEB_PORT=' .env 2>/dev/null | tail -n 1 | cut -d= -f2 || true)"
PORT="${PORT:-8765}"
set_kv() { if grep -qE "^$1=" .env; then sed -i '' "s|^$1=.*|$1=$2|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi; }

if [ "${1:-}" = "off" ]; then
  [ -n "$TS" ] && "$TS" serve --https=443 off 2>/dev/null || true
  set_kv JARVIS_WEB_HOST 0.0.0.0
  echo "Tailscale serve stopped; web UI will listen on the LAN again after restart."
  exit 0
fi

if [ -z "$TS" ]; then
  echo "==> Installing Tailscale (Homebrew cask)"
  brew install --cask tailscale
  TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
  open -a Tailscale || true
fi

if ! "$TS" status >/dev/null 2>&1; then
  echo
  echo "Tailscale はまだログインしていません。メニューバーの Tailscale アイコン → Log in で"
  echo "ログイン(Google / GitHub / Apple などで無料)してから、もう一度このスクリプトを実行してください。"
  open -a Tailscale 2>/dev/null || true
  exit 1
fi

echo "==> Serving MIRA over HTTPS inside your tailnet"
if ! "$TS" serve --bg "$PORT" 2>/dev/null; then
  # Older CLI syntax.
  "$TS" serve https / "http://127.0.0.1:$PORT"
fi

HOST="$("$TS" status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || echo "<mac-name>.<tailnet>.ts.net")"
set_kv JARVIS_WEB_HOST 127.0.0.1
cat <<MSG

Done.
  URL for your phone (with Tailscale installed and logged in to the same account):
    https://$HOST/
  Token: $(grep -E '^JARVIS_WEB_TOKEN=' .env | tail -n 1 | cut -d= -f2)

  The web UI now listens on 127.0.0.1 only (LAN access closed); restart MIRA:
    bash scripts/mac/start.sh      (or it restarts itself if installed as a service)

  If 'serve' complained about HTTPS certificates: open https://login.tailscale.com/admin/dns
  and enable "MagicDNS" and "HTTPS Certificates", then run this script again.
MSG
