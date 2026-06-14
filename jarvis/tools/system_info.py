"""Lightweight system / time introspection tools."""

from __future__ import annotations

import platform
import shutil

from . import Tool, ToolContext


def _now(tool_input: dict, ctx: ToolContext) -> str:
    now = ctx.config.now()
    return now.strftime("%A, %d %B %Y, %H:%M:%S %Z (%z)")


def _system(tool_input: dict, ctx: ToolContext) -> str:
    uname = platform.uname()
    lines = [
        f"system: {uname.system} {uname.release}",
        f"version: {uname.version}",
        f"machine: {uname.machine}",
        f"processor: {uname.processor or 'unknown'}",
        f"python: {platform.python_version()}",
    ]
    try:
        total, used, free = shutil.disk_usage("/")
        gb = 1024**3
        lines.append(
            f"disk (/): {used // gb}G used / {total // gb}G total, {free // gb}G free"
        )
    except OSError:
        pass
    return "\n".join(lines)


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="get_datetime",
            description="Get the current local date and time.",
            input_schema={"type": "object", "properties": {}, "required": []},
            run=_now,
        ),
        Tool(
            name="get_system_info",
            description="Get information about the host machine (OS, CPU, Python, disk).",
            input_schema={"type": "object", "properties": {}, "required": []},
            run=_system,
        ),
    ]
