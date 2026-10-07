"""Entry point: ``python -m jarvis`` (terminal) or ``python -m jarvis web`` (phone UI)."""

from __future__ import annotations

import argparse
import sys

from .config import Config


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS — your own AI assistant")
    sub = parser.add_subparsers(dest="command")
    web = sub.add_parser("web", help="serve the phone-friendly web UI (PWA)")
    web.add_argument("--host", help="bind address (default: JARVIS_WEB_HOST or 127.0.0.1)")
    web.add_argument("--port", type=int, help="port (default: JARVIS_WEB_PORT or 8765)")
    sub.add_parser("cli", help="interactive terminal (default)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    config = Config.load()
    if args.command == "web":
        from .web import serve

        serve(config, host=args.host, port=args.port)
        return

    from .cli import CLI

    CLI(config).run()


if __name__ == "__main__":
    main()
