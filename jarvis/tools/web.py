"""Local web access tools: search and fetch.

These let a local model reach the internet without any paid API. `web_search`
uses DuckDuckGo's public HTML endpoint (no key required); `web_fetch` retrieves
a page and returns its readable text. Both need a live internet connection —
the rest of JARVIS works fully offline.
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote_plus, unquote

from . import Tool, ToolContext

_UA = "Mozilla/5.0 (compatible; JARVIS/0.1; +https://localhost)"
_TAG_RE = re.compile(r"<[^>]+>")
_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>', re.DOTALL
)


def _strip_html(raw: str) -> str:
    text = _TAG_RE.sub("", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_ddg_href(href: str) -> str:
    # DuckDuckGo wraps result links as /l/?uddg=<encoded-url>
    m = re.search(r"uddg=([^&]+)", href)
    return unquote(m.group(1)) if m else href


def _web_search(tool_input: dict, ctx: ToolContext) -> str:
    import requests

    query = tool_input.get("query", "").strip()
    if not query:
        return "Error: no search query provided."
    max_results = int(tool_input.get("max_results", 5))

    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": _UA},
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        return f"Web search failed (no internet connection?): {exc}"

    body = resp.text
    titles = list(_RESULT_RE.finditer(body))
    snippets = [_strip_html(m.group("snippet")) for m in _SNIPPET_RE.finditer(body)]

    if not titles:
        return f"No results found for '{query}'."

    lines = []
    for i, m in enumerate(titles[:max_results]):
        title = _strip_html(m.group("title"))
        url = _clean_ddg_href(m.group("href"))
        snippet = snippets[i] if i < len(snippets) else ""
        lines.append(f"{i + 1}. {title}\n   {url}\n   {snippet}".rstrip())
    return f"Search results for '{query}':\n\n" + "\n\n".join(lines)


def _web_fetch(tool_input: dict, ctx: ToolContext) -> str:
    import requests

    url = tool_input.get("url", "").strip()
    if not url:
        return "Error: no URL provided."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return f"Failed to fetch {url} (no internet connection?): {exc}"

    ctype = resp.headers.get("content-type", "")
    if "html" in ctype or not ctype:
        # Drop script/style, then strip tags.
        cleaned = re.sub(
            r"<(script|style)[^>]*>.*?</\1>", " ", resp.text, flags=re.DOTALL | re.I
        )
        text = _strip_html(cleaned)
    else:
        text = resp.text

    limit = 8000
    if len(text) > limit:
        text = text[:limit] + f"\n...[truncated, {len(text) - limit} more chars]"
    return f"Content of {url}:\n\n{text}"


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="web_search",
            description="Web search (DuckDuckGo): titles, URLs, snippets. Needs internet.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."},
                    "max_results": {
                        "type": "integer",
                        "description": "Result count (default 5).",
                    },
                },
                "required": ["query"],
            },
            run=_web_search,
        ),
        Tool(
            name="web_fetch",
            description="Fetch a web page and return its readable text.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch."}
                },
                "required": ["url"],
            },
            run=_web_fetch,
        ),
    ]
