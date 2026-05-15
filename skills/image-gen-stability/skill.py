"""
image-gen-stability skill
Generates images using the Stability AI REST API.
"""
from __future__ import annotations

import base64
import os

from langchain_core.tools import tool

_CONFIG: dict = {}

_API_HOST = "https://api.stability.ai"


@tool
def generate_image_stability(prompt: str) -> str:
    """Generate an image using Stability AI Stable Diffusion.
    Returns a base64-encoded PNG data URI.

    Args:
        prompt: Detailed description of the image to generate.
    """
    try:
        import requests  # type: ignore
    except ImportError:
        return "Error: requests package is not installed."

    api_key = _CONFIG.get("api_key") or os.getenv("STABILITY_API_KEY")
    if not api_key:
        return "Error: No Stability AI API key configured. Set it in plugin settings or STABILITY_API_KEY env var."

    aspect_ratio = _CONFIG.get("aspect_ratio", "1:1")

    try:
        response = requests.post(
            f"{_API_HOST}/v2beta/stable-image/generate/core",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "image/*",
            },
            files={"none": ""},
            data={
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "output_format": "png",
            },
            timeout=60,
        )

        if not response.ok:
            try:
                err = response.json()
            except Exception:
                err = response.text
            return f"Stability API error {response.status_code}: {err}"

        b64 = base64.b64encode(response.content).decode()
        data_uri = f"data:image/png;base64,{b64}"
        return (
            f"Image generated successfully.\n"
            f"Size: {len(response.content):,} bytes\n\n"
            f"Data URI:\n{data_uri}"
        )
    except Exception as exc:
        return f"Image generation failed: {exc}"


def register() -> list:
    return [generate_image_stability]
