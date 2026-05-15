# Image Gen (ComfyUI)

Generate images using your **local** ComfyUI instance — completely free, fully private.

## What it does

Adds a `generate_image_comfyui` tool that submits a minimal text-to-image workflow to a ComfyUI server running on your machine and returns the result as a base64 image.

## Requirements

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) installed and running locally.
- At least one Stable Diffusion checkpoint downloaded into ComfyUI's `models/checkpoints/` directory.
- `requests` Python package (included in sidecar dependencies).

## Setup

1. Start ComfyUI: `python main.py --listen 127.0.0.1 --port 8188`
2. Configure the plugin with your checkpoint filename.

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `host` | `127.0.0.1:8188` | ComfyUI server address. |
| `checkpoint` | `v1-5-pruned-emaonly.ckpt` | Model checkpoint filename. |
| `steps` | `20` | Diffusion steps (10–50 typical). |

## Example

> **User:** Generate a photo of a cozy cabin in the woods  
> **Assistant:** *(calls `generate_image_comfyui(...)`)* Here is your image…

## Notes

- Generation can take 5–60 seconds depending on your GPU and step count.
- The workflow uses a minimal KSampler + VAEDecode pipeline. For complex workflows, edit `skill.py` directly.
