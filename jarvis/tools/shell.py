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
    # Sending data somewhere (exfiltration) or pulling remote code.
    r"\bcurl\b.*\s(-d|--data|-F|--form|-T|--upload-file|-X\s*POST|-X\s*PUT)\b",
    r"\bwget\b.*--post",
    r"\b(ssh|scp|sftp|rsync|nc|ncat|netcat|telnet)\b",
    r"\b(python3?|perl|ruby|node)\b.*\s-c\s",   # inline scripts
    r"\beval\b",
    r"\bbase64\b.*\|",
    # macOS: settings, keychain, automation, services, disks.
    r"\b(osascript|launchctl|defaults\s+write|security\b|diskutil|tmutil|networksetup|pmset|csrutil|spctl|killall)\b",
    # Credentials and keys.
    r"(\.ssh/|\.aws/|\.gnupg/|id_rsa|id_ed25519|\.env\b|keychain)",
    r"\bcrontab\b",
    r"\b(kill|pkill)\b.*-9",
    r">\s*~?/(etc|usr|bin|sbin|System|Library)/",
]


def _looks_dangerous(command: str) -> bool:
    return any(re.search(p, command) for p in _DANGEROUS)


def _run_shell(tool_input: dict, ctx: ToolContext) -> str:
    command = tool_input.get("command", "").strip()
    if not command:
        return "Error: no command provided."

    timeout = max(1, min(int(tool_input.get("timeout", 60)), 600))
    must_confirm = ctx.config.confirm_all_shell or _looks_dangerous(command)
    if ctx.tainted:
        # Untrusted web content was read this turn: never run anything unasked.
        must_confirm = True

    if must_confirm:
        why = " (web content was read this turn)" if ctx.tainted else ""
        if not ctx.confirm(f"Run shell command?{why}\n    {command}"):
            return "Command declined by the user. Not executed."

    ctx.notify(f"running: {command}")
    try:
        cwd = ctx.config.fs_root if ctx.config.fs_root.is_dir() else None
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
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
