"""
Multi-stage search engine for Universal File Access skill.

Pipeline:
  1. Query preprocessing — extract terms and extension hints
  2. Exact name substring match (score 0.85–1.0)
  3. BM25 token search (rank_bm25)
  4. Trigram fuzzy match (rapidfuzz)
  5. Extension boost / strict filter
  6. Recency boost
  7. Depth penalty
  → Merge, deduplicate, rank, return top-N
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

# ── Stop words ────────────────────────────────────────────────────────────────

_STOP_WORDS = frozenset({
    "the", "a", "an", "my", "i", "was", "where", "is", "for", "about",
    "in", "on", "at", "to", "of", "and", "or", "not", "me", "find",
    "show", "get", "look", "search", "what", "can", "you", "please",
    "file", "folder", "document", "help",
})

# ── Extension aliases (natural language → list[ext]) ─────────────────────────

_EXT_MAP: dict[str, list[str]] = {
    "document":     ["docx", "doc"],
    "doc":          ["docx", "doc"],
    "word":         ["docx", "doc"],
    "pdf":          ["pdf"],
    "spreadsheet":  ["xlsx", "xls", "csv"],
    "excel":        ["xlsx", "xls"],
    "csv":          ["csv"],
    "presentation": ["pptx", "ppt"],
    "slides":       ["pptx", "ppt"],
    "powerpoint":   ["pptx", "ppt"],
    "image":        ["jpg", "png", "jpeg", "webp", "gif"],
    "photo":        ["jpg", "png", "jpeg", "webp"],
    "picture":      ["jpg", "png", "jpeg", "webp"],
    "pictures":     ["jpg", "png", "jpeg", "webp"],
    "video":        ["mp4", "mov", "avi", "mkv"],
    "code":         ["py", "js", "ts", "rs", "cpp", "c", "java", "go"],
    "script":       ["py", "js", "ts", "sh", "bat", "ps1"],
    "text":         ["txt", "md"],
    "note":         ["txt", "md"],
    "notes":        ["txt", "md"],
    "readme":       ["md", "txt"],
    "zip":          ["zip", "7z", "tar", "gz", "rar"],
    "archive":      ["zip", "7z", "tar", "gz", "rar"],
}

# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    path: str
    name: str
    extension: str
    score: float
    modified_at: float
    size_bytes: int
    match_reason: str  # "exact_name" | "fuzzy_name" | "bm25" | "recent"


# ── Query preprocessing ───────────────────────────────────────────────────────

def _preprocess_query(query: str) -> tuple[list[str], list[str]]:
    """
    Returns (terms, extension_hints).
    Strips stop words, extracts quoted literals, maps type words to extensions.
    """
    q = query.lower()

    # Pull quoted strings first (they become exact terms)
    quoted = re.findall(r'"([^"]+)"', q)
    q = re.sub(r'"[^"]+"', " ", q)

    ext_hints: list[str] = []
    terms: list[str] = list(quoted)

    for word in re.split(r"[\s_\-\.]+", q):
        word = word.strip()
        if not word or len(word) < 2:
            continue
        if word in _STOP_WORDS:
            continue
        if word in _EXT_MAP:
            ext_hints.extend(_EXT_MAP[word])
        else:
            terms.append(word)

    return terms, list(dict.fromkeys(ext_hints))  # dedup, preserve order


# ── Main search ───────────────────────────────────────────────────────────────

async def search_files(
    query: str,
    config: dict,
    limit: int = 20,
) -> list[SearchResult]:
    from indexer import get_index, _trigrams

    idx = get_index()
    if not idx.records:
        return []

    terms, ext_hints = _preprocess_query(query)
    if not terms and not ext_hints:
        return []

    min_score = float(config.get("min_match_score", 40)) / 100.0
    scores: dict[int, float] = {}
    reasons: dict[int, str] = {}

    # ── Stage 2: Exact name substring ────────────────────────────────────────
    for term in terms:
        for i, rec in enumerate(idx.records):
            lname = (rec.name + "." + rec.extension).lower()
            if term in lname:
                score = 1.0 if rec.name.lower() == term else 0.85
                if scores.get(i, 0.0) < score:
                    scores[i] = score
                    reasons[i] = "exact_name"

    # ── Stage 3: BM25 ────────────────────────────────────────────────────────
    try:
        from rank_bm25 import BM25Okapi

        # Lazily rebuild BM25 corpus when the index was mutated by watchdog
        if idx.bm25_dirty:
            idx.bm25_corpus = [r.name_tokens for r in idx.records]
            idx.bm25_dirty = False

        if idx.bm25_corpus and terms:
            bm25 = BM25Okapi(idx.bm25_corpus)
            bm25_scores = bm25.get_scores(terms)
            max_s = float(bm25_scores.max()) if len(bm25_scores) > 0 else 0.0
            if max_s > 0:
                for i, s in enumerate(bm25_scores):
                    if s <= 0:
                        continue
                    norm = float(s) / max_s
                    if norm > 0.05 and scores.get(i, 0.0) < norm:
                        scores[i] = norm
                        reasons[i] = "bm25"
    except (ImportError, Exception):
        pass

    # ── Stage 4: Trigram fuzzy ────────────────────────────────────────────────
    try:
        from rapidfuzz import fuzz

        for term in terms:
            term_tris = set(_trigrams(term))
            if not term_tris:
                continue
            for i, rec in enumerate(idx.records):
                rec_tris = set(rec.name_trigrams)
                if not rec_tris:
                    continue
                overlap = len(term_tris & rec_tris) / max(len(term_tris), 1)
                if overlap >= 0.6:
                    ratio = fuzz.token_sort_ratio(term, rec.name.lower()) / 100.0
                    if ratio >= 0.65:
                        fuzz_score = ratio * 0.9
                        if scores.get(i, 0.0) < fuzz_score:
                            scores[i] = fuzz_score
                            reasons[i] = "fuzzy_name"
    except (ImportError, Exception):
        pass

    if not scores:
        return []

    # ── Stage 5: Extension boost / filter ────────────────────────────────────
    if ext_hints:
        strict = bool(config.get("strict_extension_match", False))
        for i in list(scores.keys()):
            rec = idx.records[i]
            if rec.extension in ext_hints:
                scores[i] = min(1.0, scores[i] + 0.3)
            elif strict:
                del scores[i]
                reasons.pop(i, None)

    # ── Stage 6: Recency boost ────────────────────────────────────────────────
    now = time.time()
    for i in scores:
        age_days = (now - idx.records[i].modified_at) / 86400
        if age_days <= 7:
            scores[i] = min(1.0, scores[i] + 0.15)
        elif age_days <= 30:
            scores[i] = min(1.0, scores[i] + 0.08)
        elif age_days <= 90:
            scores[i] = min(1.0, scores[i] + 0.03)

    # ── Stage 7: Depth penalty ────────────────────────────────────────────────
    for i in scores:
        depth = idx.records[i].depth
        if depth > 5:
            penalty = min(0.1, (depth - 5) * 0.02)
            scores[i] = max(0.0, scores[i] - penalty)

    # ── Merge, filter, sort ───────────────────────────────────────────────────
    results: list[SearchResult] = []
    for i, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        if score < min_score:
            continue
        rec = idx.records[i]
        results.append(SearchResult(
            path=rec.path,
            name=rec.name,
            extension=rec.extension,
            score=round(score, 3),
            modified_at=rec.modified_at,
            size_bytes=rec.size_bytes,
            match_reason=reasons.get(i, "bm25"),
        ))
        if len(results) >= limit:
            break

    return results


async def search_recent_documents(limit: int = 30) -> list[SearchResult]:
    """Return recently modified document-like files from the index."""
    from indexer import get_index

    _DOC_EXTS = frozenset({
        "pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt",
        "txt", "md", "csv", "odt", "rtf", "pages", "numbers", "key",
    })

    idx = get_index()
    results: list[SearchResult] = []
    for i in idx.modified_sorted:
        rec = idx.records[i]
        if rec.extension in _DOC_EXTS:
            results.append(SearchResult(
                path=rec.path,
                name=rec.name,
                extension=rec.extension,
                score=0.5,
                modified_at=rec.modified_at,
                size_bytes=rec.size_bytes,
                match_reason="recent",
            ))
        if len(results) >= limit:
            break

    return results
