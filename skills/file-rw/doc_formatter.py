"""
doc_formatter.py — converts Markdown content into richly formatted documents.

Dispatch via:  render_document(ext, markdown_content, output_path)

Supported output formats
------------------------
docx  — python-docx  (headings, paragraphs, lists, tables, code blocks,
                       bold / italic / inline-code, blockquotes, HR)
pdf   — reportlab    (same elements, A4, matching accent colour)
html  — standalone   (embedded CSS, responsive, automatic dark-mode)

All renderers share the same block-level Markdown parser so the output
is visually consistent across formats.
"""
from __future__ import annotations

import re
from pathlib import Path

# Shared accent colour (professional blue) used across every format
_ACCENT_HEX = "#2E74B5"
_ACCENT_RGB = (0x2E, 0x74, 0xB5)


# ══════════════════════════════════════════════════════════════════════════════
# Shared: block-level Markdown parser
# ══════════════════════════════════════════════════════════════════════════════

def _parse_blocks(content: str) -> list[dict]:
    """
    Parse Markdown into a flat list of typed block dicts.

    Block types
    -----------
    heading   : {type, level: int, text: str}
    paragraph : {type, text: str}
    bullet    : {type, text: str, depth: int}
    numbered  : {type, text: str, depth: int}
    quote     : {type, text: str}
    code      : {type, lang: str, lines: list[str]}
    hr        : {type}
    table     : {type, rows: list[list[str]]}  — separator rows excluded
    blank     : {type}
    """
    blocks: list[dict] = []
    lines = content.splitlines()
    i = 0

    while i < len(lines):
        raw = lines[i]

        # blank
        if not raw.strip():
            blocks.append({"type": "blank"})
            i += 1
            continue

        # fenced code block
        if raw.lstrip().startswith("```"):
            lang = raw.strip().lstrip("`").strip()
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                body.append(lines[i])
                i += 1
            blocks.append({"type": "code", "lang": lang, "lines": body})
            i += 1  # skip closing ```
            continue

        # horizontal rule
        if re.match(r"^\s*[-*_]{3,}\s*$", raw):
            blocks.append({"type": "hr"})
            i += 1
            continue

        # ATX heading
        m = re.match(r"^(#{1,6})\s+(.*)", raw)
        if m:
            blocks.append({"type": "heading", "level": len(m.group(1)), "text": m.group(2).strip()})
            i += 1
            continue

        # table
        if "|" in raw and raw.strip().startswith("|"):
            table_raw: list[str] = []
            while i < len(lines) and "|" in lines[i]:
                table_raw.append(lines[i])
                i += 1
            rows = []
            for row_line in table_raw:
                if re.match(r"^\|[\s\-:|]+\|$", row_line.strip()):
                    continue  # separator row
                cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
                rows.append(cells)
            if rows:
                blocks.append({"type": "table", "rows": rows})
            continue

        # bullet list
        m = re.match(r"^(\s*)[-*+]\s+(.*)", raw)
        if m:
            depth = len(m.group(1)) // 2
            blocks.append({"type": "bullet", "text": m.group(2), "depth": depth})
            i += 1
            continue

        # numbered list
        m = re.match(r"^(\s*)\d+\.\s+(.*)", raw)
        if m:
            depth = len(m.group(1)) // 2
            blocks.append({"type": "numbered", "text": m.group(2), "depth": depth})
            i += 1
            continue

        # blockquote
        m = re.match(r"^>\s?(.*)", raw)
        if m:
            blocks.append({"type": "quote", "text": m.group(1)})
            i += 1
            continue

        # paragraph
        blocks.append({"type": "paragraph", "text": raw.rstrip()})
        i += 1

    return blocks


# ══════════════════════════════════════════════════════════════════════════════
# Shared: inline Markdown → spans  (for docx)
# ══════════════════════════════════════════════════════════════════════════════

_INLINE_RE = re.compile(
    r"(\*\*\*(?P<biu>[^*]+)\*\*\*"
    r"|\*\*(?P<bi>[^*]+)\*\*"
    r"|\*(?P<i>[^*]+)\*"
    r"|__(?P<b2>[^_]+)__"
    r"|_(?P<i2>[^_]+)_"
    r"|`(?P<code>[^`]+)`)"
)

def _inline_spans(text: str) -> list[dict]:
    """Return a list of {text, bold, italic, code} dicts."""
    spans: list[dict] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            spans.append({"text": text[pos:m.start()], "bold": False, "italic": False, "code": False})
        if m.group("biu"):
            spans.append({"text": m.group("biu"),          "bold": True,  "italic": True,  "code": False})
        elif m.group("bi"):
            spans.append({"text": m.group("bi"),           "bold": True,  "italic": False, "code": False})
        elif m.group("i") or m.group("i2"):
            spans.append({"text": m.group("i") or m.group("i2"), "bold": False, "italic": True,  "code": False})
        elif m.group("b2"):
            spans.append({"text": m.group("b2"),           "bold": True,  "italic": False, "code": False})
        elif m.group("code"):
            spans.append({"text": m.group("code"),         "bold": False, "italic": False, "code": True})
        pos = m.end()
    if pos < len(text):
        spans.append({"text": text[pos:], "bold": False, "italic": False, "code": False})
    return spans or [{"text": text, "bold": False, "italic": False, "code": False}]


# ══════════════════════════════════════════════════════════════════════════════
# DOCX renderer  (python-docx)
# ══════════════════════════════════════════════════════════════════════════════

def markdown_to_docx(content: str, path: str) -> None:
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor, Inches
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
    except ImportError:
        raise ImportError("python-docx not installed — run: uv add python-docx")

    doc = Document()

    # Page margins
    for sec in doc.sections:
        sec.top_margin    = Inches(1.0)
        sec.bottom_margin = Inches(1.0)
        sec.left_margin   = Inches(1.2)
        sec.right_margin  = Inches(1.2)

    # Base styles
    accent = RGBColor(*_ACCENT_RGB)
    _docx_set_style(doc.styles["Normal"], "Calibri", Pt(11))
    for level, size in ((1, Pt(20)), (2, Pt(16)), (3, Pt(14)), (4, Pt(13))):
        sname = f"Heading {level}"
        if sname in doc.styles:
            _docx_set_style(doc.styles[sname], "Calibri", size, bold=True, colour=accent)

    # Render blocks
    for blk in _parse_blocks(content):
        t = blk["type"]

        if t == "blank":
            continue

        elif t == "heading":
            lvl  = min(blk["level"], 4)
            para = doc.add_heading("", level=lvl)
            para.clear()
            _docx_inline_runs(para, blk["text"])

        elif t == "paragraph":
            para = doc.add_paragraph()
            _docx_inline_runs(para, blk["text"])

        elif t == "quote":
            para = doc.add_paragraph()
            _docx_inline_runs(para, blk["text"])
            para.paragraph_format.left_indent = Inches(0.4)
            for run in para.runs:
                run.italic = True

        elif t == "bullet":
            style = "List Bullet 2" if blk.get("depth", 0) else "List Bullet"
            para  = doc.add_paragraph(style=style)
            _docx_inline_runs(para, blk["text"])

        elif t == "numbered":
            style = "List Number 2" if blk.get("depth", 0) else "List Number"
            para  = doc.add_paragraph(style=style)
            _docx_inline_runs(para, blk["text"])

        elif t == "code":
            code_text = "\n".join(blk["lines"])
            para = doc.add_paragraph()
            run  = para.add_run(code_text)
            run.font.name = "Courier New"
            run.font.size = Pt(9)
            # grey background shading
            pPr = para._p.get_or_add_pPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"),   "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"),  "F2F2F2")
            pPr.append(shd)
            para.paragraph_format.left_indent  = Inches(0.3)
            para.paragraph_format.right_indent = Inches(0.3)
            para.paragraph_format.space_before = Pt(4)
            para.paragraph_format.space_after  = Pt(4)

        elif t == "hr":
            para = doc.add_paragraph()
            pPr  = para._p.get_or_add_pPr()
            pBdr = OxmlElement("w:pBdr")
            bot  = OxmlElement("w:bottom")
            bot.set(qn("w:val"),   "single")
            bot.set(qn("w:sz"),    "6")
            bot.set(qn("w:space"), "1")
            bot.set(qn("w:color"), "AAAAAA")
            pBdr.append(bot)
            pPr.append(pBdr)

        elif t == "table":
            rows = blk["rows"]
            if not rows:
                continue
            ncols = max(len(r) for r in rows)
            tbl   = doc.add_table(rows=len(rows), cols=ncols)
            tbl.style = "Table Grid"
            for ri, row in enumerate(rows):
                for ci in range(ncols):
                    cell_text = row[ci] if ci < len(row) else ""
                    cell      = tbl.cell(ri, ci)
                    cell.text = ""
                    para      = cell.paragraphs[0]
                    _docx_inline_runs(para, cell_text)
                    if ri == 0:
                        for run in para.runs:
                            run.bold = True
                            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                        tcPr = cell._tc.get_or_add_tcPr()
                        shd  = OxmlElement("w:shd")
                        shd.set(qn("w:val"),   "clear")
                        shd.set(qn("w:color"), "auto")
                        shd.set(qn("w:fill"),  "2E74B5")
                        tcPr.append(shd)

    doc.save(path)


def _docx_set_style(style, font_name: str, size, bold: bool = False, colour=None) -> None:
    style.font.name = font_name
    style.font.size = size
    if bold:
        style.font.bold = True
    if colour is not None:
        style.font.color.rgb = colour


def _docx_inline_runs(para, text: str) -> None:
    """Add inline-formatted runs to a python-docx paragraph."""
    from docx.shared import Pt
    for span in _inline_spans(text):
        run = para.add_run(span["text"])
        if span["bold"]:
            run.bold = True
        if span["italic"]:
            run.italic = True
        if span["code"]:
            run.font.name = "Courier New"
            run.font.size = Pt(9)


# ══════════════════════════════════════════════════════════════════════════════
# PDF renderer  (reportlab)
# ══════════════════════════════════════════════════════════════════════════════

def markdown_to_pdf(content: str, path: str) -> None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Preformatted,
            Table, TableStyle, HRFlowable,
        )
    except ImportError:
        raise ImportError("reportlab not installed — run: uv add reportlab")

    accent = colors.HexColor(_ACCENT_HEX)
    grey_bg = colors.HexColor("#F2F2F2")
    grey_alt = colors.HexColor("#FAFAFA")

    base = ParagraphStyle(
        "RDBase", fontName="Helvetica", fontSize=11,
        leading=17, spaceAfter=6, alignment=TA_JUSTIFY,
    )
    h_common = dict(alignment=TA_LEFT, textColor=accent, fontName="Helvetica-Bold")
    styles = {
        "h1":       ParagraphStyle("H1",  parent=base, fontSize=22, spaceAfter=10, spaceBefore=14, **h_common),
        "h2":       ParagraphStyle("H2",  parent=base, fontSize=17, spaceAfter=8,  spaceBefore=10, **h_common),
        "h3":       ParagraphStyle("H3",  parent=base, fontSize=14, spaceAfter=6,  spaceBefore=8,  **h_common),
        "h4":       ParagraphStyle("H4",  parent=base, fontSize=12, spaceAfter=4,  spaceBefore=6,  **h_common),
        "para":     base,
        "quote":    ParagraphStyle("Quote",    parent=base, leftIndent=24, rightIndent=24,
                                   fontName="Helvetica-Oblique", textColor=colors.grey),
        "bullet":   ParagraphStyle("Bullet",   parent=base, leftIndent=20, bulletIndent=8, spaceAfter=3),
        "numbered": ParagraphStyle("Numbered", parent=base, leftIndent=20, bulletIndent=8, spaceAfter=3),
        "code":     ParagraphStyle("Code", fontName="Courier", fontSize=9, leading=13,
                                   backColor=grey_bg, leftIndent=16, rightIndent=16,
                                   spaceAfter=8, spaceBefore=4, borderPad=6),
        "cell":     ParagraphStyle("Cell", parent=base, fontSize=10, spaceAfter=0),
    }

    story = []
    num_counters: dict[int, int] = {}

    for blk in _parse_blocks(content):
        t = blk["type"]

        if t == "blank":
            story.append(Spacer(1, 4))

        elif t == "heading":
            lvl = min(blk["level"], 4)
            story.append(Paragraph(_inline_pdf(blk["text"]), styles[f"h{lvl}"]))

        elif t == "paragraph":
            story.append(Paragraph(_inline_pdf(blk["text"]), styles["para"]))

        elif t == "quote":
            story.append(Paragraph(_inline_pdf(blk["text"]), styles["quote"]))

        elif t == "bullet":
            story.append(Paragraph("• " + _inline_pdf(blk["text"]), styles["bullet"]))

        elif t == "numbered":
            depth = blk.get("depth", 0)
            num_counters[depth] = num_counters.get(depth, 0) + 1
            for k in [k for k in num_counters if k > depth]:
                del num_counters[k]
            story.append(Paragraph(f"{num_counters[depth]}. " + _inline_pdf(blk["text"]), styles["numbered"]))

        elif t == "code":
            story.append(Spacer(1, 4))
            story.append(Preformatted("\n".join(blk["lines"]), styles["code"]))

        elif t == "hr":
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
            story.append(Spacer(1, 6))

        elif t == "table":
            rows = blk["rows"]
            if not rows:
                continue
            ncols = max(len(r) for r in rows)
            data  = []
            for ri, row in enumerate(rows):
                data_row = []
                for ci in range(ncols):
                    raw_text = row[ci] if ci < len(row) else ""
                    cell_markup = (
                        f"<b>{_escape_pdf(raw_text)}</b>"
                        if ri == 0
                        else _inline_pdf(raw_text)
                    )
                    data_row.append(Paragraph(cell_markup, styles["cell"]))
                data.append(data_row)

            tbl = Table(data, hAlign="LEFT", repeatRows=1)
            tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1,  0), accent),
                ("TEXTCOLOR",     (0, 0), (-1,  0), colors.white),
                ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, grey_alt]),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ]))
            story.append(Spacer(1, 8))
            story.append(tbl)
            story.append(Spacer(1, 8))

    SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=1.2 * inch, rightMargin=1.2 * inch,
        topMargin=1.0 * inch,  bottomMargin=1.0 * inch,
    ).build(story)


def _escape_pdf(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline_pdf(text: str) -> str:
    """Convert inline Markdown to reportlab XML markup."""
    t = _escape_pdf(text)
    t = re.sub(r"\*\*\*([^*]+)\*\*\*", r"<b><i>\1</i></b>", t)
    t = re.sub(r"\*\*([^*]+)\*\*",     r"<b>\1</b>",         t)
    t = re.sub(r"__([^_]+)__",         r"<b>\1</b>",         t)
    t = re.sub(r"\*([^*]+)\*",         r"<i>\1</i>",         t)
    t = re.sub(r"_([^_]+)_",           r"<i>\1</i>",         t)
    t = re.sub(r"`([^`]+)`",           r'<font name="Courier">\1</font>', t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)  # strip link markup
    return t


# ══════════════════════════════════════════════════════════════════════════════
# HTML renderer
# ══════════════════════════════════════════════════════════════════════════════

def markdown_to_html(content: str, path: str) -> None:
    """Render Markdown to a self-contained, responsive HTML file."""

    def _inline_html(text: str) -> str:
        t = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        t = re.sub(r"\*\*\*([^*]+)\*\*\*", r"<strong><em>\1</em></strong>", t)
        t = re.sub(r"\*\*([^*]+)\*\*",     r"<strong>\1</strong>",           t)
        t = re.sub(r"__([^_]+)__",         r"<strong>\1</strong>",           t)
        t = re.sub(r"\*([^*]+)\*",         r"<em>\1</em>",                   t)
        t = re.sub(r"_([^_]+)_",           r"<em>\1</em>",                   t)
        t = re.sub(r"`([^`]+)`",           r"<code>\1</code>",               t)
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>',       t)
        return t

    def _block_to_html(blk: dict) -> str:
        t = blk["type"]
        if   t == "blank":     return ""
        elif t == "heading":
            lvl = min(blk["level"], 6)
            return f"<h{lvl}>{_inline_html(blk['text'])}</h{lvl}>"
        elif t == "paragraph": return f"<p>{_inline_html(blk['text'])}</p>"
        elif t == "quote":     return f"<blockquote><p>{_inline_html(blk['text'])}</p></blockquote>"
        elif t in ("bullet", "numbered"):
            return f"<li>{_inline_html(blk['text'])}</li>"
        elif t == "code":
            lang = blk.get("lang", "")
            cls  = f' class="language-{lang}"' if lang else ""
            body = "\n".join(blk["lines"]).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            return f"<pre><code{cls}>{body}</code></pre>"
        elif t == "hr":   return "<hr>"
        elif t == "table":
            rows  = blk["rows"]
            ncols = max(len(r) for r in rows)
            parts = ["<table>"]
            for ri, row in enumerate(rows):
                parts.append("<tr>")
                for ci in range(ncols):
                    raw_cell = row[ci] if ci < len(row) else ""
                    tag = "th" if ri == 0 else "td"
                    parts.append(f"<{tag}>{_inline_html(raw_cell)}</{tag}>")
                parts.append("</tr>")
            parts.append("</table>")
            return "\n".join(parts)
        return ""

    # Wrap consecutive list items in <ul>/<ol>
    blocks   = _parse_blocks(content)
    parts: list[str] = []
    in_ul = in_ol = False

    for blk in blocks:
        if blk["type"] == "bullet":
            if not in_ul: parts.append("<ul>"); in_ul = True
            if in_ol:     parts.append("</ol>"); in_ol = False
        elif blk["type"] == "numbered":
            if not in_ol: parts.append("<ol>"); in_ol = True
            if in_ul:     parts.append("</ul>"); in_ul = False
        else:
            if in_ul: parts.append("</ul>"); in_ul = False
            if in_ol: parts.append("</ol>"); in_ol = False
        html_chunk = _block_to_html(blk)
        if html_chunk:
            parts.append(html_chunk)

    if in_ul: parts.append("</ul>")
    if in_ol: parts.append("</ol>")

    title = Path(path).stem
    body  = "\n".join(parts)

    Path(path).write_text(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
{_HTML_CSS}
</style>
</head>
<body>
<article>
{body}
</article>
</body>
</html>""",
        encoding="utf-8",
    )


_HTML_CSS = """
/* RAGdoll generated document */
*, *::before, *::after { box-sizing: border-box; }

:root {
  --accent:   #2E74B5;
  --accent2:  #1A4F8A;
  --bg:       #ffffff;
  --text:     #1a1a1a;
  --muted:    #555555;
  --code-bg:  #f4f4f4;
  --border:   #dde1e7;
  --th-bg:    #2E74B5;
  --th-text:  #ffffff;
  --tr-alt:   #f8fafd;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg:      #0d1117;
    --text:    #e6edf3;
    --muted:   #8b949e;
    --code-bg: #161b22;
    --border:  #30363d;
    --th-bg:   #1A4F8A;
    --tr-alt:  #161b22;
  }
}

body {
  font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
  font-size: 16px;
  line-height: 1.7;
  color: var(--text);
  background: var(--bg);
  margin: 0;
  padding: 0;
}

article {
  max-width: 780px;
  margin: 2.5rem auto;
  padding: 0 1.5rem 4rem;
}

h1, h2, h3, h4, h5, h6 {
  color: var(--accent);
  font-weight: 700;
  line-height: 1.3;
  margin-top: 1.8em;
  margin-bottom: 0.5em;
}
h1 { font-size: 2.0em;  border-bottom: 2px solid var(--border); padding-bottom: .35em; }
h2 { font-size: 1.55em; border-bottom: 1px solid var(--border); padding-bottom: .25em; }
h3 { font-size: 1.25em; }
h4 { font-size: 1.1em; }

p  { margin: 0.75em 0; }

a           { color: var(--accent); text-decoration: underline; }
a:hover     { color: var(--accent2); }
strong      { font-weight: 700; }
em          { font-style: italic; }

code {
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  font-size: .875em;
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: .1em .4em;
}

pre {
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  overflow-x: auto;
  margin: 1.25em 0;
}
pre code { background: none; border: none; padding: 0; font-size: .875em; line-height: 1.6; }

blockquote {
  border-left: 4px solid var(--accent);
  margin: 1.25em 0;
  padding: .5em 1em;
  color: var(--muted);
  font-style: italic;
}
blockquote p { margin: 0; }

ul, ol { padding-left: 1.6em; margin: .75em 0; }
li     { margin: .3em 0; }

hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 2em 0;
}

table {
  width: 100%;
  border-collapse: collapse;
  margin: 1.5em 0;
  font-size: .95em;
}
th, td { border: 1px solid var(--border); padding: .6em .9em; text-align: left; }
th     { background: var(--th-bg); color: var(--th-text); font-weight: 600; }
tr:nth-child(even) td { background: var(--tr-alt); }
"""


# ══════════════════════════════════════════════════════════════════════════════
# Dispatcher
# ══════════════════════════════════════════════════════════════════════════════

#: Extensions handled by this module (all others fall back to plain-text write)
FORMATTED_EXTS: frozenset[str] = frozenset({"docx", "doc", "pdf", "html", "htm"})


def render_document(ext: str, content: str, path: str) -> None:
    """Route Markdown content to the correct format renderer."""
    ext = ext.lower()
    if ext in ("docx", "doc"):
        markdown_to_docx(content, path)
    elif ext == "pdf":
        markdown_to_pdf(content, path)
    elif ext in ("html", "htm"):
        markdown_to_html(content, path)
    else:
        raise ValueError(f"No rich renderer for '.{ext}'. Supported: docx, pdf, html.")
