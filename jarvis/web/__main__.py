"""Entry point: `python -m jarvis.web` — serve JARVIS as an installable PWA."""

from __future__ import annotations

import socket

from ..config import Config
from .server import create_app


def _lan_ip() -> str:
    """Best-effort local IP so the start-up message shows a phone-reachable URL."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # no packets sent; just picks the route's iface
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main() -> None:
    import uvicorn

    config = Config.load()
    app = create_app(config)

    port = config.web_port
    ip = _lan_ip()
    scheme = "http"
    print(f"\n  {config.assistant_name} web — open on your phone (same Wi-Fi):")
    print(f"    {scheme}://{ip}:{port}")
    print(f"    {scheme}://localhost:{port}  (this machine)")
    if config.web_token:
        print("    A token is set — enter it in the app's settings to connect.")
    else:
        print("    No token set. Set JARVIS_WEB_TOKEN before exposing beyond your LAN.")
    print("  Add to Home Screen for a full-screen, app-like JARVIS.\n")

    uvicorn.run(app, host=config.web_host, port=port, log_level="info")


if __name__ == "__main__":
    main()
