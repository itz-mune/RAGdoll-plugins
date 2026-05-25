"""
image-search skill — RAGdoll plugin.

Provides a search_images tool that returns direct image URLs from the
configured provider (DuckDuckGo by default, no API key required).

Supported providers
-------------------
duckduckgo  — via ddgs (already a RAGdoll dependency), no credentials needed (default)
unsplash    — requires unsplash_access_key in plugin config
pexels      — requires pexels_api_key in plugin config
pixabay     — requires pixabay_api_key in plugin config

File R/W integration
--------------------
The file_rw skill calls this tool to get image URLs when creating .docx/.pdf/.html
documents. Returned URLs can be embedded directly with Markdown image syntax:
    ![caption](url)
"""
from __future__ import annotations

import json
from pathlib import Path

from langchain.tools import BaseTool
from pydantic import BaseModel, Field

# ── Plugin config (injected by loader) ────────────────────────────────────────
_CONFIG: dict = {}


# ── Schema ────────────────────────────────────────────────────────────────────

class ImageSearchInput(BaseModel):
    query: str = Field(
        description=(
            "What to search for. Be specific and descriptive "
            "(e.g. 'Albert Einstein portrait black and white', "
            "'mountain landscape sunrise', 'Python programming code')."
        )
    )
    count: int = Field(
        default=3,
        description="Number of images to return (1–10). Default 3.",
    )


# ── Tool ──────────────────────────────────────────────────────────────────────

class ImageSearchTool(BaseTool):
    name: str = "search_images"
    description: str = (
        "Search for freely-licensed images and return their direct URLs. "
        "ONLY trigger this tool when: "
        "(1) the user explicitly asks to find, search for, retrieve, or include images, or "
        "(2) the file_rw skill is creating a .docx/.pdf/.html document and needs image URLs "
        "to embed — in that case call this tool before calling file_rw. "
        "Do NOT use this for general web searches — use web_search instead. "
        "Returns a JSON array: [{url, title, source, width, height}]. "
        "Pass the returned URLs directly to file_rw content as ![caption](url) in Markdown."
    )
    args_schema: type[BaseModel] = ImageSearchInput
    return_direct: bool = False

    def _run(self, **kwargs) -> str:  # type: ignore[override]
        raise RuntimeError("ImageSearchTool must be called from an async (LangGraph) context.")

    async def _arun(  # type: ignore[override]
        self,
        query: str,
        count: int = 3,
    ) -> str:
        config  = _CONFIG or {}
        provider = str(config.get("provider", "duckduckgo")).lower()
        count    = max(1, min(count, 10))

        try:
            if provider == "duckduckgo":
                return await _search_ddg(query, count)
            elif provider == "unsplash":
                key = str(config.get("unsplash_access_key", "")).strip()
                if not key:
                    return _err(
                        "Unsplash Access Key is not configured. "
                        "Add it in Image Search plugin settings, or switch the provider to DuckDuckGo."
                    )
                return await _search_unsplash(query, count, key)
            elif provider == "pexels":
                key = str(config.get("pexels_api_key", "")).strip()
                if not key:
                    return _err(
                        "Pexels API Key is not configured. "
                        "Add it in Image Search plugin settings, or switch the provider to DuckDuckGo."
                    )
                return await _search_pexels(query, count, key)
            elif provider == "pixabay":
                key = str(config.get("pixabay_api_key", "")).strip()
                if not key:
                    return _err(
                        "Pixabay API Key is not configured. "
                        "Add it in Image Search plugin settings, or switch the provider to DuckDuckGo."
                    )
                return await _search_pixabay(query, count, key)
            else:
                return _err(
                    f"Unknown provider '{provider}'. "
                    "Valid options: duckduckgo, unsplash, pexels, pixabay."
                )
        except Exception as exc:
            return _err(str(exc))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _err(msg: str) -> str:
    return json.dumps({"error": msg})


def _result(items: list[dict]) -> str:
    # Filter out items with no URL
    items = [i for i in items if i.get("url")]
    if not items:
        return _err("No images found for this query. Try a different search term.")
    return json.dumps(items, ensure_ascii=False)


# ── DuckDuckGo (default, no key) ──────────────────────────────────────────────

async def _search_ddg(query: str, count: int) -> str:
    import asyncio

    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # older package name fallback
        except ImportError:
            return _err("ddgs package not installed. Run: uv add ddgs")

    def _sync() -> list[dict]:
        with DDGS() as ddgs:
            return list(ddgs.images(query, max_results=count))

    try:
        results = await asyncio.to_thread(_sync)
    except Exception as exc:
        return _err(f"DuckDuckGo image search failed: {exc}")

    items = []
    for r in results:
        items.append({
            "url":    r.get("image", ""),
            "title":  r.get("title", ""),
            "source": r.get("source", ""),
            "width":  r.get("width"),
            "height": r.get("height"),
        })
    return _result(items)


# ── Unsplash ──────────────────────────────────────────────────────────────────

async def _search_unsplash(query: str, count: int, key: str) -> str:
    import asyncio
    import urllib.request
    import urllib.parse

    def _sync() -> dict:
        params = urllib.parse.urlencode({
            "query": query, "per_page": count, "orientation": "landscape",
        })
        req = urllib.request.Request(
            f"https://api.unsplash.com/search/photos?{params}",
            headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    data = await asyncio.to_thread(_sync)
    items = []
    for r in data.get("results", []):
        items.append({
            "url":    r["urls"]["regular"],
            "title":  r.get("alt_description") or r.get("description") or query,
            "source": "unsplash.com",
            "width":  r.get("width"),
            "height": r.get("height"),
        })
    return _result(items)


# ── Pexels ────────────────────────────────────────────────────────────────────

async def _search_pexels(query: str, count: int, key: str) -> str:
    import asyncio
    import urllib.request
    import urllib.parse

    def _sync() -> dict:
        params = urllib.parse.urlencode({
            "query": query, "per_page": count, "orientation": "landscape",
        })
        req = urllib.request.Request(
            f"https://api.pexels.com/v1/search?{params}",
            headers={"Authorization": key},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    data = await asyncio.to_thread(_sync)
    items = []
    for r in data.get("photos", []):
        items.append({
            "url":    r["src"]["large"],
            "title":  r.get("alt") or query,
            "source": "pexels.com",
            "width":  r.get("width"),
            "height": r.get("height"),
        })
    return _result(items)


# ── Pixabay ───────────────────────────────────────────────────────────────────

async def _search_pixabay(query: str, count: int, key: str) -> str:
    import asyncio
    import urllib.request
    import urllib.parse

    def _sync() -> dict:
        params = urllib.parse.urlencode({
            "key": key, "q": query, "per_page": count,
            "image_type": "photo", "orientation": "horizontal", "safesearch": "true",
        })
        req = urllib.request.Request(
            f"https://pixabay.com/api/?{params}",
            headers={"User-Agent": "RAGdoll/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    data = await asyncio.to_thread(_sync)
    items = []
    for r in data.get("hits", []):
        items.append({
            "url":    r.get("largeImageURL") or r.get("webformatURL", ""),
            "title":  r.get("tags", query),
            "source": "pixabay.com",
            "width":  r.get("imageWidth"),
            "height": r.get("imageHeight"),
        })
    return _result(items)


# ── Pydantic v2 forward-ref fix ───────────────────────────────────────────────
ImageSearchInput.model_rebuild()
ImageSearchTool.model_rebuild()


def register() -> list:
    """Called by the RAGdoll plugin loader."""
    return [ImageSearchTool()]
