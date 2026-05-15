# Image Gen (DALL-E)

Generate images from text descriptions using OpenAI's DALL-E 3.

## What it does

Adds a `generate_image_dalle` tool. The LLM can call it with a detailed prompt and receive back a URL to the generated image.

## Requirements

- `openai` Python package (included via `langchain-openai` in sidecar dependencies).
- An OpenAI API key with access to the Images API.

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `api_key` | *(env)* | Your OpenAI API key. Falls back to `OPENAI_API_KEY` env var. |
| `model` | `dall-e-3` | `dall-e-3` or `dall-e-2`. |
| `size` | `1024x1024` | Output dimensions. DALL-E 3 supports `1024x1024`, `1792x1024`, `1024x1792`. |

## Example

> **User:** Draw a futuristic cityscape at sunset  
> **Assistant:** *(calls `generate_image_dalle(...)`)* Here is your image: https://…

## Pricing

DALL-E 3 Standard 1024×1024 costs $0.040 per image. See [OpenAI pricing](https://openai.com/pricing) for details.
