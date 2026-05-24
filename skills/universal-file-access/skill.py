"""
Universal File Access — LangChain/LangGraph tool.

Wires together the indexer, searcher, and permissions_bus to give the LLM
the ability to find files on the user's computer without ever reading file
contents (that's the File R/W skill's job).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

from langchain.tools import BaseTool
from pydantic import BaseModel, Field

# ── Bootstrap sys.path ───────────────────────────────────────────────────────
# 1. Add this plugin's directory so indexer.py / searcher.py are importable.
# 2. Add the sidecar directory so permissions_bus.py is importable.
#    We locate sidecar/ by inspecting the already-loaded plugins.loader module
#    (always present in the sidecar process) — this avoids hard-coding paths.

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

_loader_mod = sys.modules.get("plugins.loader")
if _loader_mod:
    _sidecar_dir = str(Path(_loader_mod.__file__).parent.parent)
    if _sidecar_dir not in sys.path:
        sys.path.insert(0, _sidecar_dir)

# ── Plugin config (injected by loader when saved config exists) ───────────────
_CONFIG: dict = {}

# ── Frontend marker ──────────────────────────────────────────────────────────
# The frontend's MessageThread detects this in assistant messages and renders
# FileResultDisplay instead of plain markdown for that section.
_MARKER = "__RAGDOLL_FILES__"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _human_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b //= 1024
    return f"{b:.0f} TB"


def _human_date(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%b %d, %Y")


def _format_results(results: list, query: str) -> str:
    """
    Returns a markdown string that embeds a JSON payload between __RAGDOLL_FILES__
    markers so the frontend can render a rich card list.
    """
    payload = [
        {
            "path":       r.path,
            "name":       r.name,
            "extension":  r.extension,
            "score":      r.score,
            "modified_at": r.modified_at,
            "size_bytes": r.size_bytes,
            "match_reason": r.match_reason,
        }
        for r in results
    ]

    lines = [f"Found **{len(results)}** file(s) matching _{query}_:\n"]
    for i, r in enumerate(results[:5], 1):
        lines.append(
            f"{i}. **{r.name}.{r.extension}**  \n"
            f"   `{r.path}`  \n"
            f"   {_human_date(r.modified_at)} · {_human_size(r.size_bytes)} · score {r.score:.0%}\n"
        )
    if len(results) > 5:
        lines.append(f"_…and {len(results) - 5} more._\n")

    top = results[0]
    lines.append(
        f"\nThe most likely match is **{top.name}.{top.extension}**. "
        "To read its contents ask me to open or summarise it "
        "(requires the File R/W skill)."
    )

    marker_json = f"\n{_MARKER}{json.dumps(payload)}{_MARKER}\n"
    return "\n".join(lines) + marker_json


# ── Tool ──────────────────────────────────────────────────────────────────────

class _Input(BaseModel):
    query: str = Field(
        description=(
            "Natural language description of the file to find. "
            "Be specific: include filename keywords, approximate date, or file type."
        )
    )
    directory_hint: Optional[str] = Field(
        default=None,
        description=(
            "Optional directory path to restrict search to "
            "(use when a previous search returned too many unrelated results)."
        ),
    )


class UniversalFileAccessTool(BaseTool):
    name: str = "search_files"
    description: str = (
        "Search for files on the user's computer by describing what you're looking for "
        "in natural language. "
        "ALWAYS call this tool when the user asks to find, locate, open, or access any file "
        "on their machine — documents, PDFs, spreadsheets, images, videos, code, or anything "
        "else stored locally. "
        "NEVER tell the user you cannot access their file system. "
        "NEVER ask them to find the file themselves. "
        "NEVER describe how to use File Explorer or Finder. "
        "Call this tool first, every time, without exception."
    )
    args_schema: type[BaseModel] = _Input
    return_direct: bool = False

    # sync stub — LangGraph uses _arun in async mode
    def _run(  # type: ignore[override]
        self, query: str, directory_hint: Optional[str] = None
    ) -> str:
        raise RuntimeError(
            "UniversalFileAccessTool must be called from an async (LangGraph) context."
        )

    async def _arun(  # type: ignore[override]
        self, query: str, directory_hint: Optional[str] = None
    ) -> str:
        from indexer import get_index, is_critical_path, init_index
        from searcher import search_files, search_recent_documents
        from permissions_bus import request_permission

        config = _CONFIG or {}
        threshold_type  = config.get("threshold_type", "files")
        threshold_value = int(config.get("threshold_value", 20))
        t_start = time.time()

        # Lazy init: if the sidecar skipped this plugin at startup, build now.
        idx = get_index()
        if idx.file_count == 0:
            await init_index(config)

        # ── Step 1: Search ────────────────────────────────────────────────────
        results = await search_files(query, config, limit=50)

        if directory_hint:
            hint = directory_hint.rstrip("/\\").lower()
            results = [r for r in results if r.path.lower().startswith(hint)]

        good = [r for r in results if r.score >= 0.70]
        weak = [r for r in results if 0.40 <= r.score < 0.70]

        # ── Step 2: Collect files to access ──────────────────────────────────
        if good:
            files_to_access = [r.path for r in good[:5]]
        elif weak:
            files_to_access = [r.path for r in weak[:10]]
        else:
            recent = await search_recent_documents(limit=threshold_value)
            files_to_access = [r.path for r in recent]

        # ── Step 3: Threshold checks ──────────────────────────────────────────
        if not files_to_access:
            return (
                f"No files found matching '{query}'. "
                "The file index may be stale — rebuild it from "
                "Settings > Plugins > Universal File Access > Rebuild index."
            )

        if threshold_type == "seconds":
            if (time.time() - t_start) >= threshold_value:
                return (
                    f"Search timed out after {threshold_value}s without finding "
                    f"strong matches for '{query}'."
                )

        if threshold_type == "files" and not good and not weak:
            return (
                f"Searched {threshold_value} file(s) without finding a strong match "
                f"for '{query}'. "
                "Could you give me more context? For example: roughly when you created "
                "it, which folder it might be in, or any keywords from the filename."
            )

        # ── Step 4: Single batched permission request ─────────────────────────
        # ALL files are bundled into ONE permission request — never request per-file.
        any_critical = any(is_critical_path(f) for f in files_to_access)
        approved = await request_permission(
            files=files_to_access,
            is_critical=any_critical,
        )

        if not approved:
            return (
                "The user denied file access. "
                "Do not attempt to access files again in this conversation "
                "without explicitly asking the user first."
            )

        # ── Step 5: Format and return results ─────────────────────────────────
        if good:
            return _format_results(good[:10], query)

        if weak:
            header = (
                f"No strong matches found for '{query}', "
                "but here are some possible candidates:\n\n"
            )
            return header + _format_results(weak[:10], query)

        # Fallback: recent documents
        recent_results = await search_recent_documents(limit=10)
        if recent_results:
            return (
                f"No files matched '{query}' directly. "
                f"Here are your {len(recent_results)} most recently modified documents — "
                "perhaps one of these is what you're looking for?\n\n"
            ) + _format_results(recent_results, query)

        return f"No files found matching '{query}'."


# Pydantic v2 needs an explicit rebuild when `from __future__ import annotations`
# is in effect — otherwise the validator is left in a mock/incomplete state.
UniversalFileAccessTool.model_rebuild()


def register() -> list:
    """Called by the RAGdoll plugin loader. Returns list of LangChain tools."""
    return [UniversalFileAccessTool()]
