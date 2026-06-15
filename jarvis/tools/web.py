"""Local web access tools: search and fetch.

These let a local model reach the internet. `web_search` prefers a real search
API when a key is configured — Tavily or Brave (both have free tiers) — which is
reliable from cloud hosts like a Hugging Face Space, where DuckDuckGo's keyless
HTML endpoint is routinely blocked (HTTP 403). With no key it falls back to that
keyless DuckDuckGo endpoint, which still works fine on home networks. `web_fetch`
retrieves a page and returns its readable text. Both need a live internet
connection — the rest of JARVIS works fully offline.
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


def _format_results(query: str, rows: list[dict]) -> str:
    """Render a uniform result list from any provider. Each row is
    {title, url, snippet}."""
    if not rows:
        return f"No results found for '{query}'."
    lines = []
    for i, r in enumerate(rows):
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        lines.append(f"{i + 1}. {title}\n   {url}\n   {snippet}".rstrip())
    return f"Search results for '{query}':\n\n" + "\n\n".join(lines)


def _search_tavily(query: str, max_results: int, key: str) -> str:
    import requests

    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": key,
            "query": query,
            "max_results": max_results,
            "include_answer": True,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    rows = [
        {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content")}
        for r in data.get("results", [])[:max_results]
    ]
    out = _format_results(query, rows)
    # Tavily can synthesise a direct answer; surface it first when present.
    answer = (data.get("answer") or "").strip()
    if answer:
        out = f"Answer: {answer}\n\n{out}"
    return out


def _search_brave(query: str, max_results: int, key: str) -> str:
    import requests

    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": max_results},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    results = (resp.json().get("web") or {}).get("results", [])
    rows = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "snippet": r.get("description"),
        }
        for r in results[:max_results]
    ]
    return _format_results(query, rows)


def _search_duckduckgo(query: str, max_results: int) -> str:
    import requests

    resp = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers={"User-Agent": _UA},
        timeout=20,
    )
    resp.raise_for_status()

    body = resp.text
    titles = list(_RESULT_RE.finditer(body))
    snippets = [_strip_html(m.group("snippet")) for m in _SNIPPET_RE.finditer(body)]
    rows = []
    for i, m in enumerate(titles[:max_results]):
        snippet = snippets[i] if i < len(snippets) else ""
        rows.append(
            {
                "title": _strip_html(m.group("title")),
                "url": _clean_ddg_href(m.group("href")),
                "snippet": snippet,
            }
        )
    return _format_results(query, rows)


def _web_search(tool_input: dict, ctx: ToolContext) -> str:
    import requests

    query = tool_input.get("query", "").strip()
    if not query:
        return "Error: no search query provided."
    max_results = int(tool_input.get("max_results", 5))
    config = ctx.config

    # Prefer a configured API (reliable from the cloud); else keyless DuckDuckGo.
    try:
        if config.tavily_api_key:
            return _search_tavily(query, max_results, config.tavily_api_key)
        if config.brave_api_key:
            return _search_brave(query, max_results, config.brave_api_key)
        return _search_duckduckgo(query, max_results)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        # Cloud IPs get 403/429 from DuckDuckGo's keyless endpoint. Point the
        # user at the reliable fix rather than failing opaquely.
        if not (config.tavily_api_key or config.brave_api_key) and status in (
            403,
            429,
        ):
            return (
                f"Web search is blocked here (HTTP {status} from the keyless "
                "DuckDuckGo endpoint — common on cloud hosts). Set a free "
                "JARVIS_TAVILY_API_KEY or JARVIS_BRAVE_API_KEY to enable "
                "reliable search."
            )
        return f"Web search failed (HTTP {status})."
    except requests.RequestException as exc:
        return f"Web search failed (no internet connection?): {exc}"


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
            description=(
                "Search the web and return the top results (title, URL, "
                "snippet). Use this to find current information. Requires an "
                "internet connection."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."},
                    "max_results": {
                        "type": "integer",
                        "description": "How many results to return (default 5).",
                    },
                },
                "required": ["query"],
            },
            run=_web_search,
        ),
        Tool(
            name="web_fetch",
            description=(
                "Fetch a web page by URL and return its readable text content. "
                "Requires an internet connection."
            ),
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
