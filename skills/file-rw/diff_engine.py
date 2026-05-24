"""
Production-grade diff engine — Myers algorithm (via difflib) with semantic
enhancements for prose files (diff-match-patch) and optional Pygments
syntax token data for frontend highlighting.
"""
from __future__ import annotations

import difflib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── File-type sets ─────────────────────────────────────────────────────────────

_CODE_EXTS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".cpp", ".c", ".h",
    ".java", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".r", ".sql",
    ".sh", ".bash", ".zsh", ".fish", ".yaml", ".yml", ".toml", ".json",
    ".xml", ".html", ".htm", ".css", ".scss", ".less", ".vue", ".svelte",
    ".lua", ".dart", ".ex", ".exs", ".clj", ".hs", ".ml", ".fs",
})
_TEXT_EXTS = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".ini",
    ".env", ".gitignore", ".editorconfig",
})

_LARGE_BYTES  = 512 * 1024   # 512 KB → partial diff
_DIFF_TIMEOUT = 2.0           # seconds → simplified fallback


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class DiffLine:
    type: str                         # "context" | "insert" | "delete"
    content: str                      # text without trailing newline
    original_lineno: Optional[int]    # None for inserted lines
    modified_lineno: Optional[int]    # None for deleted lines
    tokens: list[tuple[str, str]] = field(default_factory=list)
    # (token_css_class, text) pairs; empty = no highlighting


@dataclass
class DiffHunk:
    original_start: int   # 1-indexed
    original_count: int
    modified_start: int
    modified_count: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class DiffResult:
    filename: str
    is_binary:   bool = False
    partial:     bool = False   # file was too large; diff may miss changes
    simplified:  bool = False   # diff took too long; hunk list omitted
    hunks:       list[DiffHunk] = field(default_factory=list)
    additions:   int   = 0
    deletions:   int   = 0
    original_lines: int   = 0
    modified_lines: int   = 0
    original_size:  int   = 0   # bytes
    modified_size:  int   = 0
    diff_ratio:     float = 0.0  # 0–1 similarity (1 = identical)
    syntax_language: str  = ""   # Pygments lexer alias for frontend

    def to_dict(self) -> dict:
        return {
            "filename":       self.filename,
            "is_binary":      self.is_binary,
            "partial":        self.partial,
            "simplified":     self.simplified,
            "additions":      self.additions,
            "deletions":      self.deletions,
            "original_lines": self.original_lines,
            "modified_lines": self.modified_lines,
            "original_size":  self.original_size,
            "modified_size":  self.modified_size,
            "diff_ratio":     round(self.diff_ratio, 4),
            "syntax_language": self.syntax_language,
            "hunks": [
                {
                    "original_start": h.original_start,
                    "original_count": h.original_count,
                    "modified_start": h.modified_start,
                    "modified_count": h.modified_count,
                    "lines": [
                        {
                            "type":             l.type,
                            "content":          l.content,
                            "original_lineno":  l.original_lineno,
                            "modified_lineno":  l.modified_lineno,
                            "tokens":           l.tokens,
                        }
                        for l in h.lines
                    ],
                }
                for h in self.hunks
            ],
        }


# ── Pygments helpers (optional) ────────────────────────────────────────────────

_TOKEN_CSS: dict = {}  # populated lazily


def _css_class(ttype) -> str:
    """Map a Pygments token type to a CSS class string, or empty string."""
    if not _TOKEN_CSS:
        try:
            from pygments.token import Token
            _TOKEN_CSS.update({
                Token.Keyword:              "keyword",
                Token.Keyword.Type:         "type",
                Token.Name.Decorator:       "decorator",
                Token.Name.Builtin:         "keyword",
                Token.Literal.String:       "string",
                Token.Literal.String.Doc:   "comment",
                Token.Literal.Number:       "number",
                Token.Comment:              "comment",
                Token.Comment.Single:       "comment",
                Token.Comment.Multiline:    "comment",
                Token.Operator:             "operator",
                Token.Punctuation:          "operator",
            })
        except ImportError:
            pass
    for k, v in _TOKEN_CSS.items():
        if ttype in k:
            return v
    return ""


def _build_lexer(ext: str):
    try:
        from pygments.lexers import get_lexer_for_filename
        from pygments.util import ClassNotFound
        return get_lexer_for_filename(f"_f{ext}", stripnl=False)
    except Exception:
        return None


def _syntax_name(ext: str) -> str:
    try:
        from pygments.lexers import get_lexer_for_filename
        from pygments.util import ClassNotFound
        lex = get_lexer_for_filename(f"_f{ext}")
        return lex.aliases[0] if lex.aliases else lex.name.lower()
    except Exception:
        return ""


def _tokenize(line: str, lexer) -> list[tuple[str, str]]:
    """Return (css_class, text) pairs for a single line using Pygments."""
    if lexer is None:
        return []
    try:
        from pygments import lex
        result = []
        for ttype, value in lex(line, lexer):
            result.append((_css_class(ttype), value))
        return result
    except Exception:
        return []


# ── Main engine ────────────────────────────────────────────────────────────────

class DiffEngine:
    """
    Compute diffs using Myers algorithm (difflib) for code and
    diff-match-patch for prose files.
    """

    def compute_diff(
        self,
        original: str,
        modified: str,
        filename: str,
        context_lines: int = 3,
        add_tokens: bool = True,
    ) -> DiffResult:
        """
        Compute a structured diff between *original* and *modified* content.

        Args:
            filename:      Used to detect file type and choose lexer.
            context_lines: Unchanged lines kept around each hunk.
            add_tokens:    Attach Pygments token data to each DiffLine.
        """
        ext = Path(filename).suffix.lower()
        is_code = ext in _CODE_EXTS
        is_text = ext in _TEXT_EXTS
        is_binary = not (is_code or is_text)

        orig_bytes = original.encode("utf-8", errors="replace")
        mod_bytes  = modified.encode("utf-8", errors="replace")

        if is_binary:
            return DiffResult(
                filename=filename,
                is_binary=True,
                original_size=len(orig_bytes),
                modified_size=len(mod_bytes),
            )

        partial = len(orig_bytes) > _LARGE_BYTES
        orig_lines = original.splitlines()
        mod_lines  = modified.splitlines()

        t0 = time.monotonic()

        if is_text:
            result = self._prose_diff(
                original, modified, filename, orig_lines, mod_lines, context_lines
            )
        else:
            lexer  = _build_lexer(ext) if add_tokens else None
            syntax = _syntax_name(ext)
            result = self._code_diff(
                orig_lines, mod_lines, filename, context_lines, lexer, syntax
            )

        elapsed = time.monotonic() - t0
        if elapsed > _DIFF_TIMEOUT:
            result.simplified = True
            result.hunks = []

        result.partial       = partial
        result.original_size = len(orig_bytes)
        result.modified_size = len(mod_bytes)
        return result

    # ── Code diff (line-level Myers via difflib) ───────────────────────────────

    def _code_diff(
        self,
        orig_lines: list[str],
        mod_lines:  list[str],
        filename:   str,
        context_lines: int,
        lexer,
        syntax_language: str,
    ) -> DiffResult:
        matcher = difflib.SequenceMatcher(
            isjunk=None,
            a=orig_lines,
            b=mod_lines,
            autojunk=False,   # never skip lines as junk — cleaner code diffs
        )
        ratio = matcher.ratio()
        hunks: list[DiffHunk] = []
        additions = deletions = 0

        for group in matcher.get_grouped_opcodes(context_lines):
            i_start = group[0][1]
            j_start = group[0][3]
            i_end   = group[-1][2]
            j_end   = group[-1][4]

            hunk = DiffHunk(
                original_start = i_start + 1,
                original_count = i_end - i_start,
                modified_start = j_start + 1,
                modified_count = j_end - j_start,
            )

            for tag, i1, i2, j1, j2 in group:
                if tag == "equal":
                    for k in range(i2 - i1):
                        text = orig_lines[i1 + k]
                        hunk.lines.append(DiffLine(
                            type="context",
                            content=text,
                            original_lineno=i1 + k + 1,
                            modified_lineno=j1 + k + 1,
                            tokens=_tokenize(text, lexer),
                        ))
                elif tag in ("replace", "delete"):
                    for k in range(i2 - i1):
                        text = orig_lines[i1 + k]
                        hunk.lines.append(DiffLine(
                            type="delete",
                            content=text,
                            original_lineno=i1 + k + 1,
                            modified_lineno=None,
                            tokens=_tokenize(text, lexer),
                        ))
                        deletions += 1
                    if tag == "replace":
                        for k in range(j2 - j1):
                            text = mod_lines[j1 + k]
                            hunk.lines.append(DiffLine(
                                type="insert",
                                content=text,
                                original_lineno=None,
                                modified_lineno=j1 + k + 1,
                                tokens=_tokenize(text, lexer),
                            ))
                            additions += 1
                elif tag == "insert":
                    for k in range(j2 - j1):
                        text = mod_lines[j1 + k]
                        hunk.lines.append(DiffLine(
                            type="insert",
                            content=text,
                            original_lineno=None,
                            modified_lineno=j1 + k + 1,
                            tokens=_tokenize(text, lexer),
                        ))
                        additions += 1

            hunks.append(hunk)

        return DiffResult(
            filename=filename,
            hunks=hunks,
            additions=additions,
            deletions=deletions,
            original_lines=len(orig_lines),
            modified_lines=len(mod_lines),
            diff_ratio=ratio,
            syntax_language=syntax_language,
        )

    # ── Prose diff (diff-match-patch, word/char level) ─────────────────────────

    def _prose_diff(
        self,
        original: str, modified: str,
        filename: str,
        orig_lines: list[str], mod_lines: list[str],
        context_lines: int,
    ) -> DiffResult:
        try:
            import diff_match_patch as dmp_lib
            dmp = dmp_lib.diff_match_patch()
            dmp.Diff_Timeout = _DIFF_TIMEOUT
            raw_diffs = dmp.diff_main(original, modified)
            dmp.diff_cleanupSemantic(raw_diffs)

            additions = sum(len(t) for op, t in raw_diffs if op ==  1)
            deletions = sum(len(t) for op, t in raw_diffs if op == -1)

            hunk = DiffHunk(
                original_start=1,
                original_count=len(orig_lines),
                modified_start=1,
                modified_count=len(mod_lines),
            )
            for op, text in raw_diffs:
                dl_type = {0: "context", 1: "insert", -1: "delete"}[op]
                # Each DMP segment can span multiple lines
                for segment_line in (text.splitlines() or [""]):
                    hunk.lines.append(DiffLine(
                        type=dl_type,
                        content=segment_line,
                        original_lineno=None,
                        modified_lineno=None,
                    ))

            ratio = difflib.SequenceMatcher(None, original, modified).ratio()
            return DiffResult(
                filename=filename,
                hunks=[hunk],
                additions=additions,
                deletions=deletions,
                original_lines=len(orig_lines),
                modified_lines=len(mod_lines),
                diff_ratio=ratio,
            )
        except ImportError:
            # DMP not installed — fall back to line-level code diff
            return self._code_diff(
                orig_lines, mod_lines, filename, context_lines, None, ""
            )

    # ── Multi-file parallel diff ────────────────────────────────────────────────

    def compute_multi_diff(
        self,
        operations: list[tuple[str, str, str]],
        context_lines: int = 3,
    ) -> list[DiffResult]:
        """
        Diff multiple (original, modified, filename) tuples in parallel.
        Results are returned in the same order as *operations*.
        """
        n = len(operations)
        results: list[DiffResult | None] = [None] * n
        with ThreadPoolExecutor(max_workers=min(4, n)) as pool:
            futures = {
                pool.submit(self.compute_diff, orig, mod, fn, context_lines): i
                for i, (orig, mod, fn) in enumerate(operations)
            }
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception:
                    results[idx] = DiffResult(
                        filename=operations[idx][2], simplified=True
                    )
        return results  # type: ignore[return-value]
