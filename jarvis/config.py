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

    # Which brain drives JARVIS:
    #   "llamacpp" — llama.cpp's llama-server (or any OpenAI-compatible API)
    #   "ollama"   — Ollama
    #   "claude"   — Anthropic's Claude API
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
    # OpenAI-compatible server (llama.cpp llama-server, LM Studio, TGI, ...).
    openai_base_url: str
    openai_model: str
    openai_api_key: str
    # Web UI (phone-friendly PWA).
    web_host: str
    web_port: int
    web_token: str
    # Agent mode.
    agent_max_steps: int
    agent_allow_dangerous: bool
    agent_self_check: bool
    # Learning (memory reflection).
    reflect_enabled: bool
    reflect_every: int
    learn_idle_seconds: float
    # How many past turns to replay into the prompt at startup. Small keeps
    # a phone fast; the rolling summary covers everything older.
    history_turns: int

    @property
    def is_openai_compat(self) -> bool:
        return self.provider in ("llamacpp", "openai", "lmstudio", "local")

    @property
    def is_local(self) -> bool:
        """True for any non-Claude brain (runs on hardware you control)."""
        return self.provider != "claude"

    @property
    def active_model(self) -> str:
        """The model name to show the user, whichever provider is active."""
        if self.provider == "ollama":
            return self.ollama_model
        if self.is_openai_compat:
            return self.openai_model
        return self.model

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
            user_name=os.environ.get("JARVIS_USER_NAME", ""),
            assistant_name=os.environ.get("JARVIS_NAME", "MIRA"),
            data_dir=data_dir,
            show_thinking=_bool("JARVIS_SHOW_THINKING", False),
            confirm_all_shell=_bool("JARVIS_CONFIRM_ALL_SHELL", False),
            voice=_bool("JARVIS_VOICE", False),
            # Streaming is used throughout, so a generous ceiling is safe.
            max_tokens=int(os.environ.get("JARVIS_MAX_TOKENS", "16000")),
            ollama_host=os.environ.get("JARVIS_OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.environ.get("JARVIS_OLLAMA_MODEL", "qwen2.5:7b"),
            ollama_num_ctx=int(os.environ.get("JARVIS_OLLAMA_NUM_CTX", "8192")),
            openai_base_url=os.environ.get(
                "JARVIS_OPENAI_BASE_URL", "http://127.0.0.1:8080/v1"
            ).rstrip("/"),
            openai_model=os.environ.get("JARVIS_OPENAI_MODEL", "local"),
            openai_api_key=os.environ.get("JARVIS_OPENAI_API_KEY", "no-key"),
            web_host=os.environ.get("JARVIS_WEB_HOST", "127.0.0.1"),
            web_port=int(os.environ.get("JARVIS_WEB_PORT", "8765")),
            web_token=os.environ.get("JARVIS_WEB_TOKEN", "").strip(),
            agent_max_steps=int(os.environ.get("JARVIS_AGENT_MAX_STEPS", "40")),
            agent_allow_dangerous=_bool("JARVIS_AGENT_ALLOW_DANGEROUS", False),
            agent_self_check=_bool("JARVIS_AGENT_SELF_CHECK", True),
            reflect_enabled=_bool("JARVIS_LEARN", True),
            reflect_every=int(os.environ.get("JARVIS_LEARN_EVERY", "3")),
            learn_idle_seconds=float(os.environ.get("JARVIS_LEARN_IDLE", "90")),
            history_turns=int(os.environ.get("JARVIS_HISTORY_TURNS", "16")),
        )
