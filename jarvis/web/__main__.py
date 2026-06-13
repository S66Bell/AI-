"""Entry point: `python -m jarvis.web` — run JARVIS as a local web app.

Serves the same assistant as the terminal CLI through a browser UI. By default
it binds to localhost and opens in your PC's browser; set JARVIS_WEB_HOST=0.0.0.0
to also reach it from a phone on the same Wi-Fi.
"""

from __future__ import annotations

import os
import socket
import threading
import webbrowser

from ..config import Config
from .server import create_app


def _lan_ip() -> str:
    """Best-effort local IP so we can also show a phone-reachable URL."""
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

    # Fail fast with a clear message instead of a traceback when credentials
    # for the chosen brain are missing (the assistant is built eagerly below).
    if config.is_claude and not config.api_key:
        print("No ANTHROPIC_API_KEY set. Add it, or use JARVIS_PROVIDER=ollama / hf.")
        return
    if config.is_hf and not config.hf_token:
        print("No Hugging Face token set. Set HF_TOKEN (or JARVIS_HF_TOKEN) to use "
              "JARVIS_PROVIDER=hf, or use JARVIS_PROVIDER=ollama.")
        return

    app = create_app(config)

    port = config.web_port
    local_url = f"http://localhost:{port}"
    exposed = config.web_host not in ("127.0.0.1", "localhost")

    print(f"\n  {config.assistant_name} is running on your PC:")
    print(f"    {local_url}")
    if exposed:
        print(f"    http://{_lan_ip()}:{port}  (phone on the same Wi-Fi)")
        if not config.web_token:
            print("    No token set — anyone on your network can reach it. "
                  "Set JARVIS_WEB_TOKEN before exposing it.")
    print("  Tip: in the browser you can install it as an app (Add to Home Screen).\n")

    # Pop the browser open shortly after the server starts listening — but only
    # for a local run. When bound to all interfaces (LAN / a HF Space) there's
    # usually no desktop browser to open, so we skip it.
    if not exposed and os.environ.get("JARVIS_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(local_url)).start()

    uvicorn.run(app, host=config.web_host, port=port, log_level="info")


if __name__ == "__main__":
    main()
