"""Interactive terminal interface for JARVIS."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .assistant import Assistant
from .config import Config
from .memory import Memory

HELP = """\
Commands:
  /help            show this help
  /memory          list everything JARVIS remembers
  /forget <text>   forget remembered facts matching <text>
  /reset           clear the current conversation context
  /clear-history   wipe saved conversation history on disk
  /thinking        toggle showing JARVIS's reasoning
  /voice           toggle voice mode (if available)
  /exit, /quit     shut down
Anything else is sent to JARVIS.
"""


class Emitter:
    """Streams assistant text to the terminal, tracking line position so
    status lines and prompts never collide with a half-written sentence."""

    def __init__(self, console: Console):
        self.console = console
        self._at_line_start = True
        self._wrote_prefix = False

    def text(self, chunk: str) -> None:
        if not self._wrote_prefix:
            self.console.print("[bold cyan]JARVIS[/] ", end="")
            self._wrote_prefix = True
        sys.stdout.write(chunk)
        sys.stdout.flush()
        if chunk:
            self._at_line_start = chunk.endswith("\n")

    def newline_if_needed(self) -> None:
        if not self._at_line_start:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._at_line_start = True

    def end_turn(self) -> None:
        self.newline_if_needed()
        self._wrote_prefix = False

    def status(self, msg: str) -> None:
        self.newline_if_needed()
        self.console.print(f"[dim]· {msg}[/]")


class CLI:
    def __init__(self, config: Config):
        self.config = config
        self.console = Console()
        self.memory = Memory(config.data_dir)
        self.emitter = Emitter(self.console)
        self.show_thinking = config.show_thinking
        self.voice = None
        # The backend (esp. Ollama readiness) is initialised lazily in run(),
        # so connection problems surface as a friendly message, not a traceback.
        self.assistant: Assistant | None = None
        if config.voice:
            self._enable_voice()

    def _build_assistant(self) -> bool:
        try:
            self.assistant = Assistant(
                self.config,
                self.memory,
                emit=self.emitter.text,
                confirm=self._confirm,
                notify=self.emitter.status,
                on_thinking=self._on_thinking if self.show_thinking else None,
            )
            return True
        except Exception as exc:  # e.g. Ollama not running / model not pulled
            self.console.print(f"[red]Couldn't start the model backend:[/]\n{exc}")
            return False

    # ── confirmation / thinking callbacks ──────────────────────────────
    def _confirm(self, question: str) -> bool:
        self.emitter.newline_if_needed()
        self.console.print(Panel(question, title="Confirm", border_style="yellow"))
        try:
            answer = self.console.input("[yellow]Proceed? [y/N] [/]").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes")

    def _on_thinking(self, chunk: str) -> None:
        # Reasoning summary streams in dim italics.
        sys.stdout.write(f"\033[2;3m{chunk}\033[0m")
        sys.stdout.flush()

    # ── voice ──────────────────────────────────────────────────────────
    def _enable_voice(self) -> bool:
        from .voice import Voice, voice_available

        if not voice_available():
            self.console.print(
                "[yellow]Voice dependencies not installed. "
                "Run: pip install -r requirements-voice.txt[/]"
            )
            return False
        try:
            self.voice = Voice()
            return True
        except Exception as exc:  # mic/engine init can fail on headless boxes
            self.console.print(f"[yellow]Voice unavailable: {exc}[/]")
            self.voice = None
            return False

    # ── banner ─────────────────────────────────────────────────────────
    def _banner(self) -> None:
        name = self.config.assistant_name
        if self.config.is_local:
            backend_desc = f"local · {self.config.active_model} (offline-capable)"
        else:
            backend_desc = f"Claude · {self.config.active_model} · effort: {self.config.effort}"
        title = Text(f"{name} online.", style="bold cyan")
        subtitle = Text(
            f"Good to see you, {self.config.user_name}. "
            f"Brain: {backend_desc}\n"
            f"Type /help for commands.",
            style="dim",
        )
        self.console.print(Panel(Text.assemble(title, "\n", subtitle), border_style="cyan"))

    # ── command handling ───────────────────────────────────────────────
    def _handle_command(self, raw: str) -> bool:
        """Return True if the input was a command (and handled)."""
        cmd, _, arg = raw[1:].partition(" ")
        cmd = cmd.lower()
        arg = arg.strip()

        if cmd in ("exit", "quit"):
            raise SystemExit
        if cmd == "help":
            self.console.print(HELP)
        elif cmd == "memory":
            facts = self.memory.facts_as_text()
            self.console.print(Panel(facts or "Nothing remembered yet.", title="Memory"))
        elif cmd == "forget":
            if not arg:
                self.console.print("[yellow]Usage: /forget <text>[/]")
            else:
                self.console.print(self.memory.forget(arg))
        elif cmd == "reset":
            self.assistant.reset()
            self.console.print("[dim]Conversation context cleared.[/]")
        elif cmd == "clear-history":
            self.console.print(self.memory.clear_history())
            self.assistant.reset()
        elif cmd == "thinking":
            self.show_thinking = not self.show_thinking
            self.assistant.config.show_thinking = self.show_thinking
            self.assistant.on_thinking = self._on_thinking if self.show_thinking else None
            self.console.print(
                f"[dim]Reasoning display {'on' if self.show_thinking else 'off'}.[/]"
            )
        elif cmd == "voice":
            if self.voice is None:
                if self._enable_voice():
                    self.console.print("[dim]Voice mode on.[/]")
            else:
                self.voice = None
                self.console.print("[dim]Voice mode off.[/]")
        else:
            self.console.print(f"[yellow]Unknown command: /{cmd}[/] (try /help)")
        return True

    # ── input ──────────────────────────────────────────────────────────
    def _read_input(self) -> str | None:
        if self.voice is not None:
            self.console.print("[dim]· listening...[/]")
            heard = self.voice.listen(timeout=10)
            if heard:
                self.console.print(f"[bold green]{self.config.user_name}[/] {heard}")
            return heard
        try:
            return self.console.input("[bold green]You[/] ")
        except EOFError:
            raise SystemExit

    # ── main loop ──────────────────────────────────────────────────────
    def run(self) -> None:
        if not self.config.is_local and not self.config.api_key:
            self.console.print(
                "[red]No ANTHROPIC_API_KEY found.[/] "
                "Copy .env.example to .env and add your key, "
                "or set JARVIS_PROVIDER=ollama to run a free local model."
            )
            return

        if not self._build_assistant():
            return

        self._banner()
        while True:
            try:
                user_input = self._read_input()
            except (SystemExit, KeyboardInterrupt):
                break
            if user_input is None:
                continue
            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                try:
                    self._handle_command(user_input)
                except SystemExit:
                    break
                continue

            try:
                reply = self.assistant.chat(user_input)
                self.emitter.end_turn()
                if self.voice is not None and reply:
                    self.voice.speak(reply)
            except KeyboardInterrupt:
                self.emitter.end_turn()
                self.console.print("[dim]· interrupted[/]")
            except Exception as exc:
                self.emitter.end_turn()
                self.console.print(f"[red]Error: {type(exc).__name__}: {exc}[/]")

        self.console.print(
            f"\n[cyan]{self.config.assistant_name} signing off. "
            f"Goodbye, {self.config.user_name}.[/]"
        )
