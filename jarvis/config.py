"""Configuration loading for JARVIS.

All settings come from environment variables (optionally via a `.env` file),
so the assistant stays a single, portable process you fully control.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional at runtime
    pass


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    """Resolved runtime configuration."""

    api_key: str | None
    model: str
    effort: str
    user_name: str
    assistant_name: str
    data_dir: Path
    show_thinking: bool
    confirm_all_shell: bool
    voice: bool
    max_tokens: int

    @classmethod
    def load(cls) -> "Config":
        data_dir = Path(
            os.environ.get("JARVIS_DATA_DIR", "~/.jarvis")
        ).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("JARVIS_MODEL", "claude-opus-4-8"),
            effort=os.environ.get("JARVIS_EFFORT", "high"),
            user_name=os.environ.get("JARVIS_USER_NAME", "Sir"),
            assistant_name=os.environ.get("JARVIS_NAME", "JARVIS"),
            data_dir=data_dir,
            show_thinking=_bool("JARVIS_SHOW_THINKING", False),
            confirm_all_shell=_bool("JARVIS_CONFIRM_ALL_SHELL", False),
            voice=_bool("JARVIS_VOICE", False),
            # Streaming is used throughout, so a generous ceiling is safe.
            max_tokens=int(os.environ.get("JARVIS_MAX_TOKENS", "16000")),
        )
