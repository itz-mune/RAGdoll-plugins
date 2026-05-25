# File R/W Skill

Read, write, patch, delete, rename, copy, move, and stat files on the local filesystem — with diffs, backups, and per-operation permission dialogs.

## Requirements

- **RAGdoll ≥ 0.3.0**
- **Universal File Access** skill must be installed and enabled (provides the file index)

## Features

| Operation | Description |
|-----------|-------------|
| `read`    | Read a file. Large files are truncated at the configured limit. |
| `write`   | Overwrite a file. Shows a unified diff and prompts for approval before writing. |
| `patch`   | Apply targeted find→replace edits. Supports first, last, or all occurrences. |
| `create`  | Create a new file or directory. |
| `delete`  | Send to Recycle Bin / Trash (default) or delete permanently. Prompts for approval. |
| `rename`  | Rename a file or directory in-place. |
| `copy`    | Copy a file or directory to a destination. |
| `move`    | Move a file or directory to a destination. |
| `stats`   | Show full file metadata (size, dates, permissions, owner, child count). |
| `list`    | List directory contents with metadata, sorting, and hidden file control. |

## Safety

- **Approval dialogs** appear before every write, patch, and delete. The dialog shows the full unified diff (for writes/patches) or target info (for deletes) and a 60-second countdown. Deny closes the dialog and the operation is cancelled.
- **Automatic backups** — before every write, the original is saved to `<file>.ragdoll_backup`. Use the **Undo** button in the result card or say *"undo that"* to restore.
- **Recycle Bin by default** — deleted files go to the OS recycle bin / Trash, not permanent deletion, unless you configure or request otherwise.
- **Atomic writes** — all writes go through a temp file + `os.replace()` so the original is never left in a partial state.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Default delete mode | `trash` | `trash` = Recycle Bin, `permanent` = bypass Trash |
| Create backups | `true` | Save `.ragdoll_backup` before every write |
| Max read size (MB) | `1` | Files larger than this are truncated |
| Diff context lines | `3` | Lines of context around each changed hunk |
| Show character-level diff | `true` | Highlight exact changed characters within lines |

## Example prompts

```
Read my notes at ~/Documents/notes.md
Write a Python hello-world to ~/Desktop/hello.py
Patch the README: replace "v1.0" with "v1.1"
Delete ~/Downloads/old-setup.exe
Show stats for ~/Documents/report.pdf
List ~/Projects sorted by size
```

## Undo

After any write or patch, the result card shows an **Undo** button. Clicking it restores the `.ragdoll_backup` file atomically. The backup persists until the next write to the same path, at which point it is overwritten with the newest pre-write snapshot.

You can also clear all backups from the plugin settings drawer (Actions → Clear backups).

## Document creation (DOCX / PDF / HTML)

When creating `.docx`, `.pdf`, or `.html` files, write the `content` as **Markdown** — headings, bold, italic, tables, code blocks, lists, and blockquotes are all converted into native document formatting automatically.

PDF output uses **WeasyPrint** as the primary renderer (full CSS, A4 page layout, styled title block, page numbers). **reportlab** is used as a pure-Python fallback if WeasyPrint is unavailable.

> **Windows note:** WeasyPrint requires the **GTK3 runtime** to render fonts and graphics.
> Without it WeasyPrint will silently fall back to the reportlab renderer at runtime — nothing breaks, but the output will be less polished.
> Install from: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer

## Diff view

The inline diff viewer supports:

- Collapsed summary (filename, `+N / -N` badges) — always visible
- Expanded full diff with syntax-token coloring (Pygments)
- Character-level highlight for changed chars within similar lines
- Copy-to-clipboard button
