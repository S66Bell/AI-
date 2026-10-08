"""Tools for learning new material into the knowledge base and recalling it."""

from __future__ import annotations

from . import Tool, ToolContext


def get_tools(knowledge) -> list[Tool]:
    def learn(tool_input: dict, ctx: ToolContext) -> str:
        title = str(tool_input.get("title", "")).strip()
        url = str(tool_input.get("url", "")).strip()
        path = str(tool_input.get("path", "")).strip()
        text = str(tool_input.get("text", "")).strip()
        source = "text"
        if url:
            from .web import _web_fetch, _UNTRUSTED

            fetched = _web_fetch({"url": url}, ctx)
            if fetched.startswith("Error") or fetched.startswith("Failed"):
                return fetched
            text = fetched.replace(_UNTRUSTED, "", 1)
            text = text.split("\n\n", 1)[1] if "\n\n" in text else text
            source = url
            title = title or url
        elif path:
            from .filesystem import _read_file

            text = _read_file({"path": path}, ctx)
            if text.startswith("Error"):
                return text
            source = path
            title = title or path
        if not text:
            return "Error: give a url, a path, or text to learn."
        try:
            info = knowledge.add(title or "メモ", text, source=source)
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Learned '{info['title']}' ({info['chars']} chars, {info['chunks']} chunks). I can recall it later."

    def search(tool_input: dict, ctx: ToolContext) -> str:
        query = str(tool_input.get("query", "")).strip()
        if not query:
            return "Error: no query."
        hits = knowledge.search(query, k=int(tool_input.get("k", 4)))
        if not hits:
            return "Nothing relevant in the knowledge base."
        return "\n\n".join(f"[{h['title']}] (score {h['score']})\n{h['text']}" for h in hits)

    return [
        Tool(
            name="learn_document",
            description="Save a web page, a file, or pasted text into long-term knowledge so you can recall it later.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title."},
                    "url": {"type": "string", "description": "Web page to learn."},
                    "path": {"type": "string", "description": "File to learn (inside the workspace)."},
                    "text": {"type": "string", "description": "Text to learn."},
                },
            },
            run=learn,
        ),
        Tool(
            name="search_knowledge",
            description="Search the knowledge base of things you were asked to learn.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for."},
                    "k": {"type": "integer", "description": "How many snippets (default 4)."},
                },
                "required": ["query"],
            },
            run=search,
        ),
    ]
