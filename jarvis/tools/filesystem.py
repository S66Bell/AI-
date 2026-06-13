"""Filesystem tools: read, write, and list files."""

from __future__ import annotations

from pathlib import Path

from . import Tool, ToolContext

_MAX_READ = 200_000  # bytes


def _resolve(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _read_file(tool_input: dict, ctx: ToolContext) -> str:
    path = _resolve(tool_input["path"])
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
    path = _resolve(tool_input["path"])
    content = tool_input.get("content", "")
    append = bool(tool_input.get("append", False))

    if path.exists() and not append:
        if not ctx.confirm(f"Overwrite existing file {path}?"):
            return "Write declined by the user. File unchanged."

    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as fh:
        fh.write(content)
    verb = "Appended to" if append else "Wrote"
    return f"{verb} {path} ({len(content)} chars)."


def _list_directory(tool_input: dict, ctx: ToolContext) -> str:
    path = _resolve(tool_input.get("path", "."))
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
            description="Read a text file from the local filesystem and return its contents.",
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
            description=(
                "Write text to a file on the local filesystem, creating parent "
                "directories as needed. Overwriting an existing file is confirmed "
                "with the user unless appending."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file."},
                    "content": {"type": "string", "description": "Text to write."},
                    "append": {
                        "type": "boolean",
                        "description": "Append instead of overwriting (default false).",
                    },
                },
                "required": ["path", "content"],
            },
            run=_write_file,
        ),
        Tool(
            name="list_directory",
            description="List the files and subdirectories in a directory.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path (defaults to current directory).",
                    }
                },
                "required": [],
            },
            run=_list_directory,
        ),
    ]
