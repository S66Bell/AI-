"""Entry point: `python -m jarvis`."""

from __future__ import annotations

from .cli import CLI
from .config import Config


def main() -> None:
    config = Config.load()
    CLI(config).run()


if __name__ == "__main__":
    main()
