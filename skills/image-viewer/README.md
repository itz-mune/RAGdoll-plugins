# Image Viewer

Fetch an image from a URL and analyze it with the active vision model.

## What it does

Adds a `view_image` tool. When triggered, it downloads the image at the given URL, base64-encodes it, and returns a data URI the model can describe or use for visual Q&A.

## Requirements

- `requests` Python package (included in sidecar dependencies).
- A vision-capable model (GPT-4o, Claude 3, Gemini 1.5+, etc.).

## Example

> **User:** What does this chart show? https://example.com/chart.png  
> **Assistant:** *(calls `view_image("https://example.com/chart.png")`)* The chart is a bar graph showing…

## Notes

- Maximum recommended image size: ~5 MB (larger images slow down responses).
- Supported formats: JPEG, PNG, GIF, WebP, BMP.
