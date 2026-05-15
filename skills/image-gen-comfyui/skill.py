"""
image-gen-comfyui skill
Generates images by submitting a workflow to a local ComfyUI server.
"""
from __future__ import annotations

import base64
import json
import time
import uuid

from langchain_core.tools import tool

_CONFIG: dict = {}

# Minimal text-to-image workflow template
_WORKFLOW_TEMPLATE = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "cfg": 7,
            "denoise": 1,
            "latent_image": ["5", 0],
            "model": ["4", 0],
            "negative": ["7", 0],
            "positive": ["6", 0],
            "sampler_name": "euler",
            "scheduler": "normal",
            "seed": 42,
            "steps": 20,
        },
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.ckpt"},
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {"batch_size": 1, "height": 512, "width": 512},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["4", 1], "text": ""},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["4", 1], "text": "bad quality, blurry"},
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ragdoll_", "images": ["8", 0]},
    },
}


@tool
def generate_image_comfyui(prompt: str) -> str:
    """Generate an image using a locally running ComfyUI server.
    Submits a text-to-image workflow and returns the result as a base64 data URI.

    Args:
        prompt: Text description of the image to generate.
    """
    try:
        import requests  # type: ignore
    except ImportError:
        return "Error: requests package is not installed."

    host = _CONFIG.get("host", "127.0.0.1:8188")
    checkpoint = _CONFIG.get("checkpoint", "v1-5-pruned-emaonly.ckpt")
    steps = int(_CONFIG.get("steps", 20))
    base_url = f"http://{host}"

    workflow = json.loads(json.dumps(_WORKFLOW_TEMPLATE))
    workflow["4"]["inputs"]["ckpt_name"] = checkpoint
    workflow["6"]["inputs"]["text"] = prompt
    workflow["3"]["inputs"]["steps"] = steps
    workflow["3"]["inputs"]["seed"] = int(time.time()) % 2**31

    client_id = str(uuid.uuid4())

    try:
        # Queue the prompt
        queue_resp = requests.post(
            f"{base_url}/prompt",
            json={"prompt": workflow, "client_id": client_id},
            timeout=10,
        )
        queue_resp.raise_for_status()
        prompt_id = queue_resp.json().get("prompt_id")
        if not prompt_id:
            return "Error: ComfyUI did not return a prompt_id."

        # Poll for completion (max 120 seconds)
        for _ in range(120):
            time.sleep(1)
            hist_resp = requests.get(f"{base_url}/history/{prompt_id}", timeout=10)
            if not hist_resp.ok:
                continue
            history = hist_resp.json()
            if prompt_id not in history:
                continue

            outputs = history[prompt_id].get("outputs", {})
            for node_output in outputs.values():
                images = node_output.get("images", [])
                if images:
                    img_info = images[0]
                    img_resp = requests.get(
                        f"{base_url}/view",
                        params={
                            "filename": img_info["filename"],
                            "subfolder": img_info.get("subfolder", ""),
                            "type": img_info.get("type", "output"),
                        },
                        timeout=15,
                    )
                    img_resp.raise_for_status()
                    b64 = base64.b64encode(img_resp.content).decode()
                    return (
                        f"Image generated successfully.\n"
                        f"Data URI:\ndata:image/png;base64,{b64}"
                    )

        return "Timeout: ComfyUI did not finish within 120 seconds."
    except Exception as exc:
        return f"ComfyUI generation failed: {exc}"


def register() -> list:
    return [generate_image_comfyui]
