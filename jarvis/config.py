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

    # Which brain drives JARVIS: "ollama" (local, free, offline) or "claude".
    provider: str
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
    # Local-LLM (Ollama) settings.
    ollama_host: str
    ollama_model: str
    ollama_num_ctx: int
    # Web / PWA front-end settings.
    web_host: str
    web_port: int
    web_token: str | None

    @property
    def is_local(self) -> bool:
        return self.provider == "ollama"

    @property
    def active_model(self) -> str:
        """The model name to show the user, whichever provider is active."""
        return self.ollama_model if self.is_local else self.model

    @classmethod
    def load(cls) -> "Config":
        data_dir = Path(
            os.environ.get("JARVIS_DATA_DIR", "~/.jarvis")
        ).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            provider=os.environ.get("JARVIS_PROVIDER", "ollama").strip().lower(),
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
            ollama_host=os.environ.get("JARVIS_OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.environ.get("JARVIS_OLLAMA_MODEL", "qwen2.5:7b"),
            ollama_num_ctx=int(os.environ.get("JARVIS_OLLAMA_NUM_CTX", "8192")),
            # Bind on all interfaces by default so a phone on the same Wi-Fi can
            # reach it; put a token in front before exposing beyond the LAN.
            web_host=os.environ.get("JARVIS_WEB_HOST", "0.0.0.0"),
            web_port=int(os.environ.get("JARVIS_WEB_PORT", "8765")),
            web_token=(os.environ.get("JARVIS_WEB_TOKEN") or None),
        )
