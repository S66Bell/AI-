"""Configuration loading for JARVIS.

All settings come from environment variables (optionally via a `.env` file),
so the assistant stays a single, portable process you fully control.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional at runtime
    pass


def _resolve_data_dir() -> Path:
    """Pick a writable directory for memory/history/db.

    Honours JARVIS_DATA_DIR, but if that can't be created (a common Space
    mistake: pointing at /data without enabling persistent storage), fall back
    to a writable location so JARVIS still starts instead of crashing."""
    candidates: list[Path] = []
    env = os.environ.get("JARVIS_DATA_DIR")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(Path.home() / ".jarvis")
    candidates.append(Path(tempfile.gettempdir()) / "jarvis")

    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            # Confirm we can actually write here.
            probe = path / ".write_test"
            probe.touch()
            probe.unlink()
            return path
        except OSError:
            continue
    # Last resort: the temp dir itself is essentially always writable.
    return Path(tempfile.gettempdir())


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
    # If set, JARVIS always replies in this language (e.g. "日本語", "English").
    language: str | None
    data_dir: Path
    show_thinking: bool
    confirm_all_shell: bool
    voice: bool
    max_tokens: int
    # Local-LLM (Ollama) settings.
    ollama_host: str
    ollama_model: str
    ollama_num_ctx: int
    # Hugging Face Inference settings.
    hf_token: str | None
    hf_model: str
    hf_base_url: str
    # Web / PWA front-end settings.
    web_host: str
    web_port: int
    web_token: str | None

    @property
    def is_local(self) -> bool:
        return self.provider == "ollama"

    @property
    def speech_lang(self) -> str:
        """A BCP-47 locale for the browser's voice features (recognition + TTS).
        Honours JARVIS_SPEECH_LANG; otherwise derives one from JARVIS_LANGUAGE.
        Empty string means 'let the browser decide'."""
        explicit = os.environ.get("JARVIS_SPEECH_LANG")
        if explicit:
            return explicit.strip()
        mapping = {
            "日本語": "ja-JP", "japanese": "ja-JP", "ja": "ja-JP",
            "english": "en-US", "英語": "en-US", "en": "en-US",
            "中文": "zh-CN", "chinese": "zh-CN",
            "한국어": "ko-KR", "korean": "ko-KR",
            "español": "es-ES", "spanish": "es-ES",
            "français": "fr-FR", "french": "fr-FR",
            "deutsch": "de-DE", "german": "de-DE",
        }
        if self.language:
            key = self.language.strip()
            return mapping.get(key, mapping.get(key.lower(), ""))
        return ""

    @property
    def is_hf(self) -> bool:
        return self.provider == "hf"

    @property
    def is_claude(self) -> bool:
        return self.provider == "claude"

    @property
    def uses_local_web_tools(self) -> bool:
        """Backends that need JARVIS to run web search/fetch itself (i.e. not
        Claude, which uses Anthropic's server-side web tools)."""
        return not self.is_claude

    @property
    def active_model(self) -> str:
        """The model name to show the user, whichever provider is active."""
        if self.is_local:
            return self.ollama_model
        if self.is_hf:
            return self.hf_model
        return self.model

    @classmethod
    def load(cls) -> "Config":
        data_dir = _resolve_data_dir()

        return cls(
            provider=os.environ.get("JARVIS_PROVIDER", "ollama").strip().lower(),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("JARVIS_MODEL", "claude-opus-4-8"),
            effort=os.environ.get("JARVIS_EFFORT", "high"),
            user_name=os.environ.get("JARVIS_USER_NAME", "Sir"),
            assistant_name=os.environ.get("JARVIS_NAME", "JARVIS"),
            language=(os.environ.get("JARVIS_LANGUAGE") or None),
            data_dir=data_dir,
            show_thinking=_bool("JARVIS_SHOW_THINKING", False),
            confirm_all_shell=_bool("JARVIS_CONFIRM_ALL_SHELL", False),
            voice=_bool("JARVIS_VOICE", False),
            # Streaming is used throughout, so a generous ceiling is safe.
            max_tokens=int(os.environ.get("JARVIS_MAX_TOKENS", "16000")),
            ollama_host=os.environ.get("JARVIS_OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.environ.get("JARVIS_OLLAMA_MODEL", "qwen2.5:7b"),
            ollama_num_ctx=int(os.environ.get("JARVIS_OLLAMA_NUM_CTX", "8192")),
            # Hugging Face Inference (JARVIS_PROVIDER=hf). Token is read from the
            # standard HF env vars too, so it works on Spaces out of the box.
            hf_token=(
                os.environ.get("JARVIS_HF_TOKEN")
                or os.environ.get("HF_TOKEN")
                or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
                or None
            ),
            hf_model=os.environ.get("JARVIS_HF_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
            hf_base_url=os.environ.get(
                "JARVIS_HF_BASE_URL", "https://router.huggingface.co/v1"
            ),
            # Bind to localhost by default — it's a PC-local app. To reach it
            # from a phone on the same Wi-Fi, set JARVIS_WEB_HOST=0.0.0.0.
            web_host=os.environ.get("JARVIS_WEB_HOST", "127.0.0.1"),
            web_port=int(os.environ.get("JARVIS_WEB_PORT", "8765")),
            web_token=(os.environ.get("JARVIS_WEB_TOKEN") or None),
        )
