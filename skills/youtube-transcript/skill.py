"""
youtube-transcript skill
Fetches the transcript/captions for a YouTube video.
"""
from __future__ import annotations

import re

from langchain_core.tools import tool

_LANG = "en"


def _extract_video_id(url_or_id: str) -> str:
    """Extract the 11-character video ID from a YouTube URL or return it as-is."""
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url_or_id)
        if m:
            return m.group(1)
    # Assume it's already a bare video ID
    if re.match(r"^[A-Za-z0-9_-]{11}$", url_or_id):
        return url_or_id
    return url_or_id


@tool
def get_youtube_transcript(video_url: str) -> str:
    """Retrieve the transcript (captions) of a YouTube video.
    Accepts a full YouTube URL or bare video ID.

    Args:
        video_url: YouTube video URL (e.g. https://youtu.be/dQw4w9WgXcQ)
                   or video ID (e.g. dQw4w9WgXcQ).
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled  # type: ignore
    except ImportError:
        return "Error: youtube-transcript-api package is not installed."

    video_id = _extract_video_id(video_url)

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try preferred language first, then any available
        try:
            transcript = transcript_list.find_transcript([_LANG])
        except NoTranscriptFound:
            transcript = transcript_list.find_generated_transcript(
                [t.language_code for t in transcript_list]
            )

        entries = transcript.fetch()
        text = " ".join(e["text"] for e in entries)
        return f"Transcript for video {video_id} ({transcript.language}):\n\n{text}"

    except TranscriptsDisabled:
        return f"Transcripts are disabled for video: {video_id}"
    except Exception as exc:
        return f"Failed to get transcript for {video_id}: {exc}"


def register() -> list:
    return [get_youtube_transcript]
