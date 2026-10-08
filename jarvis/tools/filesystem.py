"""Filesystem tools: read, write, and list files.

All paths are confined to ``config.fs_root`` (default ``~/.jarvis/workspace``).
Relative paths are taken from there; absolute paths and ``..`` that escape it
are refused. Set ``JARVIS_FS_ROOT=/`` to lift the restriction deliberately.
"""

from __future__ import annotations

from pathlib import Path

from . import Tool, ToolContext

_MAX_READ = 200_000  # bytes


class SandboxError(Exception):
    pass


def _resolve(path: str, ctx: ToolContext) -> Path:
    root = ctx.config.fs_root
    raw = Path(str(path or ".")).expanduser()
    candidate = (raw if raw.is_absolute() else root / raw).resolve()
    if root == Path("/"):
        return candidate
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        raise SandboxError(
            f"'{path}' is outside the allowed folder {root}. "
            f"Files can only be used inside it (JARVIS_FS_ROOT widens this)."
        )
    return candidate


def _read_file(tool_input: dict, ctx: ToolContext) -> str:
    try:
        path = _resolve(tool_input["path"], ctx)
    except SandboxError as exc:
        return f"Error: {exc}"
    if not path.exists():
        return f"Error: no such file: {path}"
    if path.is_dir():
        return f"Error: {path} is a directory. Use list_directory instead."
    data = path.read_bytes()
    if len(data) > _MAX_READ:
        return (
            f"File is {len(data)} bytes; only the first {_MAX_READ} are shown.\n\n"
            + data[:_MAX_READ].decode("utf-8", errors="replace")
        )
    return data.decode("utf-8", errors="replace")


def _write_file(tool_input: dict, ctx: ToolContext) -> str:
    try:
        path = _resolve(tool_input["path"], ctx)
    except SandboxError as exc:
        return f"Error: {exc}"
    content = tool_input.get("content", "")
    append = bool(tool_input.get("append", False))

    if ctx.tainted:
        if not ctx.confirm(f"Web content was read this turn. Still write to {path}?"):
            return "Write declined by the user. File unchanged."
    elif path.exists() and not append:
        if not ctx.confirm(f"Overwrite existing file {path}?"):
            return "Write declined by the user. File unchanged."

    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as fh:
        fh.write(content)
    verb = "Appended to" if append else "Wrote"
    return f"{verb} {path} ({len(content)} chars)."


def _list_directory(tool_input: dict, ctx: ToolContext) -> str:
    try:
        path = _resolve(tool_input.get("path", "."), ctx)
    except SandboxError as exc:
        return f"Error: {exc}"
    if not path.exists():
        return f"Error: no such directory: {path}"
    if not path.is_dir():
        return f"Error: {path} is not a directory."

    entries = []
    for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        marker = "/" if child.is_dir() else ""
        try:
            size = child.stat().st_size if child.is_file() else ""
        except OSError:
            size = ""
        entries.append(f"{child.name}{marker}\t{size}")
    listing = "\n".join(entries) if entries else "(empty)"
    return f"Contents of {path}:\n{listing}"


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="read_file",
            description="Read a text file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file."}
                },
                "required": ["path"],
            },
            run=_read_file,
        ),
        Tool(
            name="write_file",
            description="Write text to a file (creates or overwrites; append=true to add).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file."},
                    "content": {"type": "string", "description": "Text to write."},
                    "append": {
                        "type": "boolean",
                        "description": "Append instead of overwrite.",
                    },
                },
                "required": ["path", "content"],
            },
            run=_write_file,
        ),
        Tool(
            name="list_directory",
            description="List a directory.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory (default: current).",
                    }
                },
                "required": [],
            },
            run=_list_directory,
        ),
    ]
