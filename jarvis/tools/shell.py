"""Shell command execution — JARVIS's hands on the system.

Commands are run through the user's shell. Anything that looks destructive
(or every command, if JARVIS_CONFIRM_ALL_SHELL=1) requires explicit user
confirmation before it runs.
"""

from __future__ import annotations

import re
import subprocess

from . import Tool, ToolContext

# Patterns that warrant a confirmation prompt before running.
_DANGEROUS = [
    r"\brm\b.*-[a-z]*r",        # rm -r / rm -rf
    r"\brm\b\s+-[a-z]*f",        # rm -f
    r"\bmkfs\b",
    r"\bdd\b\s+if=",
    r":\(\)\s*\{",               # fork bomb
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bchmod\b\s+-R",
    r"\bchown\b\s+-R",
    r">\s*/dev/sd",
    r"\bgit\b.*\bpush\b.*--force",
    r"\bgit\b.*\breset\b.*--hard",
    r"\bsudo\b",
    r"\bcurl\b.*\|\s*(ba)?sh",   # curl | sh
    r"\bwget\b.*\|\s*(ba)?sh",
]


def _looks_dangerous(command: str) -> bool:
    return any(re.search(p, command) for p in _DANGEROUS)


def _run_shell(tool_input: dict, ctx: ToolContext) -> str:
    command = tool_input.get("command", "").strip()
    if not command:
        return "Error: no command provided."

    timeout = int(tool_input.get("timeout", 60))
    must_confirm = ctx.config.confirm_all_shell or _looks_dangerous(command)

    if must_confirm:
        if not ctx.confirm(f"Run shell command?\n    {command}"):
            return "Command declined by the user. Not executed."

    ctx.notify(f"running: {command}")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."

    out = proc.stdout or ""
    err = proc.stderr or ""
    # Keep tool results bounded so we don't blow the context window.
    out = _truncate(out)
    err = _truncate(err)

    parts = [f"exit code: {proc.returncode}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    if not out and not err:
        parts.append("(no output)")
    return "\n".join(parts)


def _truncate(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n...[{len(text) - limit} chars truncated]...\n{tail}"


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="run_shell",
            description="Run a shell command; returns exit code, stdout and stderr. Risky commands ask the user first.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to run.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 60).",
                    },
                },
                "required": ["command"],
            },
            run=_run_shell,
        )
    ]
