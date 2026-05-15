# Image Gen (Stability AI)

Generate images using Stability AI's Stable Diffusion models.

## What it does

Adds a `generate_image_stability` tool that calls the Stability AI REST API and returns the image as a base64 data URI.

## Requirements

- `requests` Python package (included in sidecar dependencies).
- A Stability AI API key from [platform.stability.ai](https://platform.stability.ai/).

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `api_key` | *(env)* | Your Stability AI key. Falls back to `STABILITY_API_KEY` env var. |
| `aspect_ratio` | `1:1` | Output aspect ratio (`1:1`, `16:9`, `4:3`, `3:2`, `21:9`, `9:21`, `9:16`, `2:3`). |

## Example

> **User:** Generate a watercolor painting of a mountain lake  
> **Assistant:** *(calls `generate_image_stability(...)`)* Here is the generated image…

## Pricing

Stability AI charges per image based on the model and resolution. See [pricing](https://platform.stability.ai/pricing) for details.
