"""
File System Indexer for Universal File Access skill.

Builds and maintains a fast local index of user files using:
  - msgpack for fast serialisation (~10× faster than JSON)
  - BM25 via rank_bm25 for token-based retrieval
  - Character trigrams for fuzzy fallback
  - watchdog for incremental live updates

Index lives at:
  {ragdoll_plugins}/universal-file-access/index/file_index.msgpack
  {ragdoll_plugins}/universal-file-access/index/index_meta.json
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ── Index storage ─────────────────────────────────────────────────────────────

def _index_dir() -> Path:
    base = os.environ.get("RAGDOLL_DATA_DIR")
    if base:
        d = Path(base) / "ragdoll_plugins" / "universal-file-access" / "index"
    else:
        d = Path(__file__).parent / "index"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Critical / system paths ───────────────────────────────────────────────────

_CRITICAL: dict[str, list[str]] = {
    "Windows": [
        "c:\\windows",
        "c:\\program files",
        "c:\\program files (x86)",
        "c:\\programdata",
    ],
    "Darwin": ["/system", "/library", "/usr", "/bin", "/sbin", "/etc", "/private"],
    "Linux":  ["/etc", "/sys", "/proc", "/boot", "/root", "/usr/bin", "/usr/sbin", "/bin", "/sbin"],
}


def is_critical_path(path: str) -> bool:
    system = platform.system()
    p = path.lower() if system == "Windows" else path
    for prefix in _CRITICAL.get(system, _CRITICAL["Linux"]):
        if p.startswith(prefix):
            return True
    return False


# ── Standard user directories ─────────────────────────────────────────────────

def _standard_dirs() -> list[Path]:
    home = Path.home()
    system = platform.system()

    if system == "Windows":
        candidates = [
            home / "Documents",
            home / "Desktop",
            home / "Downloads",
            home / "OneDrive",
            home / "Pictures",
            home / "Music",
            home / "Videos",
        ]
        # Corporate OneDrive variants: "OneDrive - CompanyName"
        try:
            for child in home.iterdir():
                if child.is_dir() and child.name.lower().startswith("onedrive - "):
                    candidates.append(child)
        except PermissionError:
            pass
    elif system == "Darwin":
        candidates = [
            home / "Documents",
            home / "Desktop",
            home / "Downloads",
            home / "Library" / "CloudStorage",
            home / "Pictures",
            home / "Music",
            home / "Movies",
        ]
    else:
        candidates = [
            home / "Documents",
            home / "Desktop",
            home / "Downloads",
            home / "Pictures",
            home / "Music",
            home / "Videos",
        ]

    return [d for d in candidates if d.exists()]


# ── Skip patterns ─────────────────────────────────────────────────────────────

_SKIP_EXTENSIONS = frozenset({
    "sys", "dll", "so", "dylib", "pdb", "ilk", "exp",
    "obj", "o", "a", "lib", "pch", "gch",
    # Note: .exe intentionally excluded per spec
})

_MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB

_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# ── FileRecord ────────────────────────────────────────────────────────────────

@dataclass
class FileRecord:
    path: str
    name: str           # stem only (no extension)
    extension: str      # lowercase, no dot
    name_tokens: list[str]
    name_trigrams: list[str]
    size_bytes: int
    modified_at: float
    created_at: float
    is_hidden: bool
    depth: int
    parent_dir: str


def _tokenize(filename: str) -> list[str]:
    """Split a filename into BM25-ready tokens."""
    name = _CAMEL_RE.sub(" ", filename)
    parts = re.split(r"[\s_\-\.]+", name)
    return [p.lower() for p in parts if len(p) >= 2]


def _trigrams(text: str) -> list[str]:
    t = text.lower()
    if len(t) < 3:
        return [t] if t else []
    return [t[i:i + 3] for i in range(len(t) - 2)]


def _is_hidden_win(path: Path) -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return bool(attrs != -1 and attrs & 2)  # FILE_ATTRIBUTE_HIDDEN = 0x2
    except Exception:
        return False


def _make_record(path: Path, depth: int) -> FileRecord | None:
    try:
        stat = path.stat()
        if stat.st_size > _MAX_FILE_SIZE:
            return None
        ext = path.suffix.lstrip(".").lower() if path.suffix else ""
        if ext in _SKIP_EXTENSIONS:
            return None
        stem = path.stem
        is_hidden = stem.startswith(".") or _is_hidden_win(path)
        full_name = path.name
        tokens = _tokenize(full_name)
        tris = list(set(_trigrams(stem) + _trigrams(ext)))
        return FileRecord(
            path=str(path),
            name=stem,
            extension=ext,
            name_tokens=tokens,
            name_trigrams=tris,
            size_bytes=stat.st_size,
            modified_at=stat.st_mtime,
            created_at=stat.st_ctime,
            is_hidden=is_hidden,
            depth=depth,
            parent_dir=path.parent.name,
        )
    except (PermissionError, OSError):
        return None


# ── Index state ───────────────────────────────────────────────────────────────

@dataclass
class IndexState:
    records: list[FileRecord]         = field(default_factory=list)
    trigram_map: dict[str, list[int]] = field(default_factory=dict)
    extension_map: dict[str, list[int]] = field(default_factory=dict)
    path_map: dict[str, int]          = field(default_factory=dict)
    modified_sorted: list[int]        = field(default_factory=list)
    bm25_corpus: list[list[str]]      = field(default_factory=list)
    bm25_dirty: bool                  = True
    last_built: float                 = 0.0
    file_count: int                   = 0
    watching: bool                    = False


_index: IndexState = IndexState()


def _build_structures(records: list[FileRecord]) -> IndexState:
    state = IndexState()
    state.records = records
    state.bm25_corpus = [r.name_tokens for r in records]
    state.bm25_dirty = False
    state.last_built = time.time()
    state.file_count = len(records)

    trigram_map: dict[str, list[int]] = {}
    ext_map: dict[str, list[int]] = {}
    path_map: dict[str, int] = {}

    for i, r in enumerate(records):
        path_map[r.path] = i
        for tri in r.name_trigrams:
            trigram_map.setdefault(tri, []).append(i)
        ext_map.setdefault(r.extension, []).append(i)

    state.trigram_map = trigram_map
    state.extension_map = ext_map
    state.path_map = path_map
    state.modified_sorted = sorted(
        range(len(records)),
        key=lambda i: records[i].modified_at,
        reverse=True,
    )
    return state


# ── Disk I/O ──────────────────────────────────────────────────────────────────

def _save_index() -> None:
    try:
        import msgpack
        d = _index_dir()
        data = {
            "records": [asdict(r) for r in _index.records],
            "last_built": _index.last_built,
        }
        (d / "file_index.msgpack").write_bytes(
            msgpack.packb(data, use_bin_type=True)
        )
        meta = {
            "last_built": _index.last_built,
            "file_count": _index.file_count,
            "version": "1",
        }
        (d / "index_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    except Exception as exc:
        print(f"[FileAccess] Failed to save index: {exc}")


def _load_index() -> bool:
    try:
        import msgpack
        d = _index_dir()
        idx_path = d / "file_index.msgpack"
        if not idx_path.exists():
            return False
        data = msgpack.unpackb(idx_path.read_bytes(), raw=False)
        records = [FileRecord(**r) for r in data.get("records", [])]
        global _index
        _index = _build_structures(records)
        _index.last_built = float(data.get("last_built", 0.0))
        return True
    except Exception as exc:
        print(f"[FileAccess] Failed to load index: {exc}")
        return False


def clear_index() -> None:
    d = _index_dir()
    for fname in ("file_index.msgpack", "index_meta.json"):
        p = d / fname
        if p.exists():
            p.unlink()
    global _index
    _index = IndexState()


# ── Build (sync, runs in thread pool) ────────────────────────────────────────

@dataclass
class IndexStats:
    files_indexed: int
    dirs_scanned: int
    build_time_ms: int


def _build_index_sync(config: dict) -> IndexStats:
    include_hidden = bool(config.get("include_hidden_files", False))
    t0 = time.time()

    dirs_scanned = 0
    records: list[FileRecord] = []

    for root_dir in _standard_dirs():
        for dirpath, dirnames, filenames in os.walk(root_dir, topdown=True):
            dirs_scanned += 1
            cur = Path(dirpath)

            # Prune hidden subdirectories in-place
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            # Compute depth relative to the root we're walking
            try:
                depth = len(cur.relative_to(root_dir).parts)
            except ValueError:
                depth = 0

            for fname in filenames:
                if not include_hidden and fname.startswith("."):
                    continue
                fpath = cur / fname
                rec = _make_record(fpath, depth)
                if rec:
                    records.append(rec)

    global _index
    _index = _build_structures(records)
    _save_index()

    return IndexStats(
        files_indexed=len(records),
        dirs_scanned=dirs_scanned,
        build_time_ms=int((time.time() - t0) * 1000),
    )


async def build_index(config: dict) -> IndexStats:
    """Build index off-thread so the event loop stays free."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _build_index_sync, config)


# ── Accessors ─────────────────────────────────────────────────────────────────

def get_index() -> IndexState:
    return _index


def get_index_stats() -> dict:
    return {
        "file_count": _index.file_count,
        "last_built": _index.last_built,
        "watching": _index.watching,
        "index_size_mb": round(
            sum(len(r.path) + len(r.name) + 100 for r in _index.records) / (1024 * 1024), 2
        ),
    }


def _estimate_depth(path_str: str) -> int:
    p = Path(path_str)
    for d in _standard_dirs():
        try:
            return len(p.relative_to(d).parts) - 1
        except ValueError:
            continue
    return 5


# ── Watchdog ──────────────────────────────────────────────────────────────────

_watchdog_observer = None


def _start_watchdog() -> object | None:
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                rec = _make_record(Path(event.src_path), _estimate_depth(event.src_path))
                if rec and rec.path not in _index.path_map:
                    idx = len(_index.records)
                    _index.records.append(rec)
                    _index.path_map[rec.path] = idx
                    _index.extension_map.setdefault(rec.extension, []).append(idx)
                    for tri in rec.name_trigrams:
                        _index.trigram_map.setdefault(tri, []).append(idx)
                    _index.bm25_corpus.append(rec.name_tokens)
                    _index.bm25_dirty = True
                    _index.file_count += 1
                    _index.modified_sorted = sorted(
                        range(len(_index.records)),
                        key=lambda i: _index.records[i].modified_at,
                        reverse=True,
                    )

            def on_deleted(self, event):
                if event.is_directory:
                    return
                idx = _index.path_map.pop(event.src_path, None)
                if idx is not None:
                    _index.bm25_dirty = True
                    _index.file_count = max(0, _index.file_count - 1)

            def on_moved(self, event):
                if event.is_directory:
                    return
                idx = _index.path_map.pop(event.src_path, None)
                if idx is not None:
                    old = _index.records[idx]
                    new_path = Path(event.dest_path)
                    _index.records[idx] = FileRecord(
                        path=str(new_path),
                        name=new_path.stem,
                        extension=new_path.suffix.lstrip(".").lower(),
                        name_tokens=_tokenize(new_path.name),
                        name_trigrams=list(set(_trigrams(new_path.stem))),
                        size_bytes=old.size_bytes,
                        modified_at=time.time(),
                        created_at=old.created_at,
                        is_hidden=old.is_hidden,
                        depth=old.depth,
                        parent_dir=new_path.parent.name,
                    )
                    _index.path_map[event.dest_path] = idx
                    _index.bm25_dirty = True

            def on_modified(self, event):
                if event.is_directory:
                    return
                idx = _index.path_map.get(event.src_path)
                if idx is not None:
                    r = _index.records[idx]
                    _index.records[idx] = FileRecord(
                        **{**asdict(r), "modified_at": time.time()}
                    )
                    _index.modified_sorted = sorted(
                        range(len(_index.records)),
                        key=lambda i: _index.records[i].modified_at,
                        reverse=True,
                    )

        handler = _Handler()
        observer = Observer()
        roots = _standard_dirs()
        for d in roots:
            observer.schedule(handler, str(d), recursive=True)
        observer.start()
        _index.watching = True
        print(f"[FileAccess] Watchdog started on {len(roots)} director(ies)")
        return observer
    except ImportError:
        print("[FileAccess] watchdog not installed — install with: uv add watchdog")
        return None
    except Exception as exc:
        print(f"[FileAccess] Watchdog failed to start: {exc}")
        return None


# ── Startup helper called from sidecar lifespan ───────────────────────────────

async def init_index(config: dict) -> None:
    global _watchdog_observer
    meta_path = _index_dir() / "index_meta.json"
    rebuild_hours = float(config.get("index_rebuild_hours", 24))

    loaded = False
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            age_hours = (time.time() - float(meta.get("last_built", 0))) / 3600
            if age_hours < rebuild_hours:
                loaded = _load_index()
                if loaded:
                    print(
                        f"[FileAccess] Loaded index: "
                        f"{_index.file_count} files ({age_hours:.1f}h old)"
                    )
        except Exception:
            pass

    if not loaded:
        print("[FileAccess] Building file index in background…")
        stats = await build_index(config)
        print(
            f"[FileAccess] Index built: "
            f"{stats.files_indexed} files scanned in {stats.build_time_ms}ms"
        )

    if _watchdog_observer is None or not getattr(_watchdog_observer, "is_alive", lambda: False)():
        _watchdog_observer = _start_watchdog()
