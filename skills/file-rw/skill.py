"""
File Read/Write skill — RAGdoll plugin.

Operations: read | write | patch | create | delete | rename | copy | move | stats | list

For write/patch/delete the skill computes a diff or stats preview, then
emits a permission_request SSE event that carries the preview data so the
frontend can render FileRWPermissionDialog before any file is modified.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

from langchain.tools import BaseTool
from pydantic import BaseModel, Field

# ── Bootstrap sys.path ────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

_loader_mod = sys.modules.get("plugins.loader")
if _loader_mod:
    _sidecar_dir = str(Path(_loader_mod.__file__).parent.parent)
    if _sidecar_dir not in sys.path:
        sys.path.insert(0, _sidecar_dir)

# ── Plugin config (injected by loader) ────────────────────────────────────────
_CONFIG: dict = {}

# ── SSE markers ──────────────────────────────────────────────────────────────
_OP_MARKER    = "__RAGDOLL_FILE_OP__"
_STATS_MARKER = "__RAGDOLL_FILE_STATS__"

# ── Critical path check (reuse universal-file-access if installed) ─────────────

def _is_critical(path: str) -> bool:
    try:
        from indexer import is_critical_path
        return is_critical_path(path)
    except ImportError:
        # Fallback: check common system directories
        p = path.lower().replace("\\", "/")
        critical = (
            "/windows/system32", "/windows/syswow64",
            "/system/library", "/usr/bin", "/usr/lib",
            "c:/windows", "c:/program files",
        )
        return any(p.startswith(c) for c in critical)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b //= 1024
    return f"{b:.0f} TB"


def _actionable_error(operation: str, path: str, exc: Exception) -> str:
    msg = str(exc)
    if "permission" in msg.lower() or "access" in msg.lower():
        hint = "Try running RAGdoll with elevated permissions."
    elif "not found" in msg.lower() or "no such" in msg.lower():
        hint = "Use the search_files tool to find the correct path."
    elif "disk" in msg.lower() or "no space" in msg.lower():
        hint = "Free up disk space and try again."
    elif "locked" in msg.lower() or "being used" in msg.lower():
        hint = "Close any applications that have the file open and try again."
    else:
        hint = ""
    return f"Could not {operation} '{path}': {msg}" + (f" {hint}" if hint else "")


def _format_listing(listing) -> str:
    """Format DirectoryListing as a readable tree."""
    from file_ops import DirectoryListing
    lines = [f"📁 {listing.path}/ ({listing.total_count} items)\n"]
    entries = listing.entries
    for i, e in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        if e.is_directory:
            lines.append(f"{connector}📁 {e.name}/")
        else:
            size_str = f" ({_fmt_size(e.size_bytes)})" if e.size_bytes is not None else ""
            lines.append(f"{connector}📄 {e.name}{size_str}")
    if listing.hidden_count:
        lines.append(f"\n_{listing.hidden_count} hidden item(s) not shown_")
    return "\n".join(lines)


# ── Pydantic schema ────────────────────────────────────────────────────────────

class FileRWInput(BaseModel):
    operation: str = Field(
        description=(
            "Operation to perform: "
            "read | write | patch | create | delete | rename | copy | move | stats | list"
        )
    )
    path: str = Field(
        description="Absolute path to the target file or directory."
    )
    content: Optional[str] = Field(
        default=None,
        description="New file content for 'write' and 'create' operations.",
    )
    patches: Optional[list[dict]] = Field(
        default=None,
        description=(
            "List of targeted edits for 'patch' operation. "
            "Each item: {search: str, replace: str, occurrence: int} "
            "(occurrence 1=first, -1=last, 0=all occurrences)."
        ),
    )
    destination: Optional[str] = Field(
        default=None,
        description="Destination path for 'copy', 'move', and 'rename' operations.",
    )
    permanent_delete: bool = Field(
        default=False,
        description="For 'delete': true = permanently delete, false = move to recycle bin.",
    )
    multiple_paths: Optional[list[str]] = Field(
        default=None,
        description="For bulk operations: list of additional paths to process.",
    )
    show_hidden: bool = Field(
        default=False,
        description="For 'list': include hidden files/directories.",
    )
    sort_by: str = Field(
        default="name",
        description="For 'list': sort by 'name' | 'modified' | 'size' | 'type'.",
    )


# ── Tool ──────────────────────────────────────────────────────────────────────

class FileRWTool(BaseTool):
    name: str = "file_rw"
    description: str = (
        "Read, write, create, delete, rename, copy, move files and directories, "
        "or get file/directory statistics and listings. "
        "Works with paths returned by the search_files tool. "
        "Always use search_files first if you don't know the exact path. "
        "For write and delete operations, always shows the user a diff or preview "
        "before executing — the user must approve before any file is modified. "
        "To read a file's contents after finding it with search_files, use operation='read'."
    )
    args_schema: type[BaseModel] = FileRWInput
    return_direct: bool = False

    def _run(self, **kwargs) -> str:  # type: ignore[override]
        raise RuntimeError("FileRWTool must be called from an async (LangGraph) context.")

    async def _arun(  # type: ignore[override]
        self,
        operation: str,
        path: str,
        content: Optional[str] = None,
        patches: Optional[list[dict]] = None,
        destination: Optional[str] = None,
        permanent_delete: bool = False,
        multiple_paths: Optional[list[str]] = None,
        show_hidden: bool = False,
        sort_by: str = "name",
    ) -> str:
        from file_ops import FileOps
        from diff_engine import DiffEngine
        from permissions_bus import request_permission

        config = _CONFIG or {}
        ops  = FileOps(config)
        diff = DiffEngine()
        op   = operation.strip().lower()

        # ── READ ────────────────────────────────────────────────────────────────
        if op == "read":
            try:
                result = await ops.read_file(path)
                name = Path(path).name
                header = (
                    f"Contents of **{name}** "
                    f"({_fmt_size(result.size_bytes)}, {result.line_count} lines, "
                    f"{result.encoding}):\n\n"
                )
                return header + result.content
            except Exception as exc:
                return _actionable_error("read", path, exc)

        # ── STATS ───────────────────────────────────────────────────────────────
        if op == "stats":
            try:
                s = await ops.get_stats(path)
                payload = {_STATS_MARKER: s.to_dict()}
                return f"\n{_STATS_MARKER}{json.dumps(s.to_dict())}{_STATS_MARKER}\n"
            except Exception as exc:
                return _actionable_error("stat", path, exc)

        # ── LIST ────────────────────────────────────────────────────────────────
        if op == "list":
            try:
                listing = await ops.list_directory(path, show_hidden, sort_by)
                return _format_listing(listing)
            except Exception as exc:
                return _actionable_error("list", path, exc)

        # ── WRITE ────────────────────────────────────────────────────────────────
        if op == "write":
            if content is None:
                return "Error: 'content' is required for the 'write' operation."
            try:
                original = await ops.read_original_for_diff(path)
                diff_result = diff.compute_diff(original, content, Path(path).name)
                approved = await request_permission(
                    files=[path],
                    is_critical=_is_critical(path),
                    permission_level="write",
                    operation="write",
                    diff=diff_result.to_dict(),
                )
                if not approved:
                    return "Write cancelled — the user denied the change."
                result = await ops.write_file(path, content)
                if not result.ok:
                    return _actionable_error("write", path, Exception(result.error or ""))
                payload = {
                    "operation": "write",
                    "path": path,
                    "additions": diff_result.additions,
                    "deletions": diff_result.deletions,
                    "backup_path": result.backup_path,
                    "diff": diff_result.to_dict(),
                }
                return (
                    f"✓ Written **{Path(path).name}** "
                    f"(+{diff_result.additions} −{diff_result.deletions} lines)"
                    f"\n{_OP_MARKER}{json.dumps(payload)}{_OP_MARKER}\n"
                )
            except Exception as exc:
                return _actionable_error("write", path, exc)

        # ── PATCH ────────────────────────────────────────────────────────────────
        if op == "patch":
            if not patches:
                return "Error: 'patches' list is required for the 'patch' operation."
            try:
                read_result = await ops.read_file(path)
                original = read_result.content
                patched, errors = ops.apply_patches(original, patches)
                diff_result = diff.compute_diff(original, patched, Path(path).name)
                if diff_result.additions == 0 and diff_result.deletions == 0:
                    return f"No changes — all patch search strings already match the current content."
                approved = await request_permission(
                    files=[path],
                    is_critical=_is_critical(path),
                    permission_level="write",
                    operation="patch",
                    diff=diff_result.to_dict(),
                )
                if not approved:
                    return "Patch cancelled — the user denied the change."
                write_result = await ops.write_file(path, patched)
                if not write_result.ok:
                    return _actionable_error("patch", path, Exception(write_result.error or ""))
                error_note = ("\n\n⚠ Some patches were skipped:\n" +
                              "\n".join(f"  • {e}" for e in errors)) if errors else ""
                payload = {
                    "operation": "patch",
                    "path": path,
                    "additions": diff_result.additions,
                    "deletions": diff_result.deletions,
                    "backup_path": write_result.backup_path,
                    "diff": diff_result.to_dict(),
                    "patch_errors": errors,
                }
                return (
                    f"✓ Patched **{Path(path).name}** "
                    f"(+{diff_result.additions} −{diff_result.deletions} lines)"
                    f"{error_note}"
                    f"\n{_OP_MARKER}{json.dumps(payload)}{_OP_MARKER}\n"
                )
            except Exception as exc:
                return _actionable_error("patch", path, exc)

        # ── CREATE ────────────────────────────────────────────────────────────────
        if op == "create":
            try:
                p = Path(path)
                if p.suffix:  # has extension → file
                    result = await ops.create_file(path, content or "")
                    if not result.ok:
                        return _actionable_error("create", path, Exception(result.error or ""))
                    return f"✓ Created file **{p.name}** at `{path}`"
                else:
                    result = await ops.create_directory(path)
                    if not result.ok:
                        return _actionable_error("create", path, Exception(result.error or ""))
                    return f"✓ Created directory `{path}`"
            except Exception as exc:
                return _actionable_error("create", path, exc)

        # ── DELETE ────────────────────────────────────────────────────────────────
        if op == "delete":
            all_paths = [path] + (multiple_paths or [])
            try:
                # Collect stats for all targets
                target_stats = []
                for tp in all_paths:
                    try:
                        s = await ops.get_stats(tp)
                        target_stats.append(s.to_dict())
                    except Exception:
                        target_stats.append({"absolute_path": tp, "error": "stat failed"})

                permanent = permanent_delete or ops.default_permanent
                approved = await request_permission(
                    files=all_paths,
                    is_critical=any(_is_critical(p) for p in all_paths),
                    permission_level="delete",
                    operation="delete",
                    permanent_delete=permanent,
                    target_stats=target_stats,
                )
                if not approved:
                    return "Delete cancelled — the user denied the operation."

                results = await ops.delete_multiple(all_paths, permanent)
                ok = [r for r in results if r.ok]
                failed = [r for r in results if not r.ok]

                mode = "permanently deleted" if permanent else "moved to recycle bin"
                msg = f"✓ {len(ok)} item(s) {mode}."
                if failed:
                    msg += "\n\n⚠ Failed:\n" + "\n".join(
                        f"  • {r.path}: {r.error}" for r in failed
                    )
                return msg
            except Exception as exc:
                return _actionable_error("delete", path, exc)

        # ── RENAME ────────────────────────────────────────────────────────────────
        if op == "rename":
            if not destination:
                return "Error: 'destination' (new name) is required for 'rename'."
            result = await ops.rename(path, destination)
            if not result.ok:
                return _actionable_error("rename", path, Exception(result.error or ""))
            return f"✓ Renamed to `{result.path}`"

        # ── COPY ─────────────────────────────────────────────────────────────────
        if op == "copy":
            if not destination:
                return "Error: 'destination' path is required for 'copy'."
            result = await ops.copy(path, destination)
            if not result.ok:
                return _actionable_error("copy", path, Exception(result.error or ""))
            return f"✓ Copied `{path}` → `{destination}`"

        # ── MOVE ─────────────────────────────────────────────────────────────────
        if op == "move":
            if not destination:
                return "Error: 'destination' path is required for 'move'."
            result = await ops.move(path, destination)
            if not result.ok:
                return _actionable_error("move", path, Exception(result.error or ""))
            return f"✓ Moved `{path}` → `{destination}`"

        return (
            f"Unknown operation '{operation}'. "
            "Valid operations: read, write, patch, create, delete, rename, copy, move, stats, list"
        )


# ── Pydantic v2 forward-reference fix ─────────────────────────────────────────
FileRWInput.model_rebuild()
FileRWTool.model_rebuild()


def register() -> list:
    """Called by the RAGdoll plugin loader."""
    return [FileRWTool()]
