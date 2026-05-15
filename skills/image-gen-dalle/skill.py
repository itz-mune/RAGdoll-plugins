"""
image-gen-dalle skill
Generates images using OpenAI DALL-E 3.
"""
from __future__ import annotations

import os

from langchain_core.tools import tool

_CONFIG: dict = {}


@tool
def generate_image_dalle(prompt: str) -> str:
    """Generate an image using DALL-E 3 from a text description.
    Returns a URL to the generated image.

    Args:
        prompt: Detailed description of the image to generate.
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return "Error: openai package is not installed."

    api_key = _CONFIG.get("api_key") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Error: No OpenAI API key configured. Set it in plugin settings or OPENAI_API_KEY env var."

    model = _CONFIG.get("model", "dall-e-3")
    size = _CONFIG.get("size", "1024x1024")

    try:
        client = OpenAI(api_key=api_key)
        response = client.images.generate(
            model=model,
            prompt=prompt,
            size=size,  # type: ignore
            quality="standard",
            n=1,
        )
        url = response.data[0].url
        revised = response.data[0].revised_prompt
        result = f"Generated image URL: {url}"
        if revised and revised != prompt:
            result += f"\n\nRevised prompt: {revised}"
        return result
    except Exception as exc:
        return f"Image generation failed: {exc}"


def register() -> list:
    return [generate_image_dalle]
