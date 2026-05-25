"""
url-fetcher skill
Fetches a webpage and extracts clean readable text using Trafilatura.
"""
from __future__ import annotations

from langchain_core.tools import tool

_MAX_CHARS = 8000


@tool
def fetch_url(url: str) -> str:
    """Fetch the main readable content from a webpage URL.
    Removes ads, navigation, and boilerplate — returns clean article text.

    IMPORTANT: Use the returned content silently as context for your task.
    Do NOT reproduce the full fetched content in your reply unless the user
    explicitly asks to see the raw page text. When using it as a reference
    (e.g. to write a document, answer a question, or compare information),
    just use the information — do not quote or paste the entire page.

    Args:
        url: The full URL of the webpage to fetch (must include https://).
    """
    try:
        import trafilatura  # type: ignore
    except ImportError:
        return "Error: trafilatura package is not installed."

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return f"Failed to download content from: {url}"

        text = trafilatura.extract(downloaded, include_links=False, include_images=False)
        if not text:
            # Fallback: return raw stripped HTML text
            import re
            text = re.sub(r"<[^>]+>", " ", downloaded)
            text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return f"Could not extract readable content from: {url}"

        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + f"\n\n… [truncated at {_MAX_CHARS} chars]"

        return f"Content from {url}:\n\n{text}"
    except Exception as exc:
        return f"Failed to fetch URL: {exc}"


def register() -> list:
    return [fetch_url]
