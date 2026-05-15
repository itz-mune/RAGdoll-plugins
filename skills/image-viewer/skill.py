"""
image-viewer skill
Downloads an image from a URL and returns it as a base64 data URI so the
calling LLM can describe or analyze it.
"""
from __future__ import annotations

import base64
import mimetypes

from langchain_core.tools import tool


@tool
def view_image(url: str) -> str:
    """Fetch an image from a URL and return a description.
    The image is downloaded and returned as a base64 data URI that the model
    can display or analyze using its vision capabilities.

    Args:
        url: Public URL of the image (JPEG, PNG, GIF, WebP, etc.).
    """
    try:
        import requests  # type: ignore
    except ImportError:
        return "Error: requests package is not installed."

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if not content_type.startswith("image/"):
            # Guess from URL
            guessed, _ = mimetypes.guess_type(url)
            content_type = guessed or "image/jpeg"

        b64 = base64.b64encode(resp.content).decode()
        data_uri = f"data:{content_type};base64,{b64}"

        return (
            f"Image fetched successfully.\n"
            f"Content-Type: {content_type}\n"
            f"Size: {len(resp.content):,} bytes\n"
            f"Data URI (truncated): {data_uri[:120]}…\n\n"
            f"Full data URI for rendering:\n{data_uri}"
        )
    except Exception as exc:
        return f"Failed to fetch image: {exc}"


def register() -> list:
    return [view_image]
