# YouTube Transcript

Retrieve the captions/transcript from any YouTube video.

## What it does

Adds a `get_youtube_transcript` tool. Pass a YouTube URL or video ID; it returns the full transcript text. Great for summarizing, Q&A, or fact-checking video content.

## Requirements

- `youtube-transcript-api` Python package (included in sidecar dependencies).

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `language` | `en` | Preferred transcript language code. Falls back to any available language. |

## Example

> **User:** Summarize this YouTube video: https://youtu.be/dQw4w9WgXcQ  
> **Assistant:** *(calls `get_youtube_transcript(...)`)* The video is a music video by Rick Astley…

## Notes

- Only works for videos that have auto-generated or manual captions enabled.
- Age-restricted or private videos are not supported.
