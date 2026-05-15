"""
web-search skill
Provides a web_search tool powered by DuckDuckGo (no API key needed).
"""
from __future__ import annotations

from langchain_core.tools import tool

_MAX_RESULTS = 5


@tool
def web_search(query: str) -> str:
    """Search the web for current information. Returns a list of titles, URLs,
    and short snippets from DuckDuckGo.

    Args:
        query: The search query string.
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "Error: duckduckgo-search package is not installed."

    try:
        max_r = _MAX_RESULTS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_r))

        if not results:
            return "No results found."

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("href", "")
            body = r.get("body", "")
            lines.append(f"{i}. **{title}**\n   {url}\n   {body}")

        return "\n\n".join(lines)
    except Exception as exc:
        return f"Search failed: {exc}"


def register() -> list:
    """Called by the plugin loader. Must return a list of LangChain tools."""
    return [web_search]
