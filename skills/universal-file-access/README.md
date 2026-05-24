# Universal File Access

**Find any file on your computer using plain English.**

> "Where's that physics assignment I worked on last week?"  
> "Find my Q3 budget spreadsheet"  
> "Show me the PDF I downloaded about machine learning"

RAGdoll will search your local files, ask your permission, and return the
exact matches — without ever leaving your machine.

---

## How it works

### 1. Indexer

On first install (or when you click **Rebuild index**), the plugin scans your
standard user directories and builds a fast local index stored as a compact
msgpack file. Typical build time:

| Files | Time |
|-------|------|
| ~10,000 | 2–5 s |
| ~50,000 | 10–25 s |
| ~100,000 | 30–60 s |

A **live file-system watcher** (watchdog) keeps the index current as you
create, move, or delete files — no manual rebuild needed day-to-day.

### 2. Search engine

Search uses a multi-stage pipeline:

1. **Exact name match** — direct substring match on filename (score 1.0)
2. **BM25 token search** — tokenises filenames (splits CamelCase, separators) and scores with BM25Okapi
3. **Trigram fuzzy match** — character n-gram overlap + rapidfuzz token sort ratio for typos
4. **Extension boost** — matches words like "pdf", "spreadsheet", "photo" to file types
5. **Recency boost** — files modified in the last 7/30/90 days score higher
6. **Depth penalty** — shallower files are slightly preferred

### 3. Permission system

The plugin **always** asks your permission before reporting any file paths.
A dialog appears inline in the chat — you never have to leave the
conversation to approve or deny.

- All files are bundled into **one** permission request per search turn.
- If you deny, the skill stops and won't retry without you asking again.
- The request expires automatically after 60 seconds if you don't respond.

---

## Privacy

- The index is stored entirely on your local machine (never uploaded).
- File *contents* are never read or sent anywhere — only paths, names, sizes, and modification dates are indexed.
- To read a file's contents, use the **File R/W** skill (separate plugin).

---

## Directories searched

| Platform | Directories |
|----------|-------------|
| **Windows** | Documents, Desktop, Downloads, OneDrive (including corporate variants), Pictures, Music, Videos |
| **macOS** | Documents, Desktop, Downloads, Library/CloudStorage (iCloud Drive), Pictures, Music, Movies |
| **Linux** | Documents, Desktop, Downloads, Pictures, Music, Videos |

System directories (C:\Windows, /System, /usr, etc.) are **never** indexed
automatically. If the search happens to request access to a critical path,
the permission dialog shows an additional warning.

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| **Search give-up condition** | `files` | What triggers RAGdoll to stop searching and ask for more context |
| **Threshold value** | `20` | Stop after this many files / seconds / characters (see above) |
| **Index rebuild interval (hours)** | `24` | Full rebuild frequency. Lower = fresher, higher = less startup CPU |
| **Include hidden files** | Off | Include dot-files (Unix) or hidden-attribute files (Windows) |
| **Minimum match score (0–100)** | `40` | Files below this score are excluded from results |

---

## Actions

Available in **Settings > Plugins > Universal File Access**:

- **Rebuild file index** — Force a full directory rescan (useful after large moves or installs)
- **Clear index** — Delete the cached index from disk (it will be rebuilt on the next search)

---

## Limitations

- Only searches user directories by default (system paths require explicit permission).
- Does **not** read file contents — use the File R/W skill for that.
- Index build takes up to 60 s on very large file systems (100,000+ files).
- The live watcher does not start on systems where `watchdog` is unavailable; the index is rebuilt on startup instead.

---

## Troubleshooting

**"No files found" for something you know exists**  
→ Rebuild the index: Settings > Plugins > Universal File Access > Rebuild file index.

**Search feels slow**  
→ Reduce `index_rebuild_hours` so the index stays warmer, or check that `watchdog` is installed (`uv add watchdog` in the sidecar).

**"watchdog not installed" in sidecar logs**  
→ Run `uv add watchdog` from the `sidecar/` directory and restart RAGdoll.
