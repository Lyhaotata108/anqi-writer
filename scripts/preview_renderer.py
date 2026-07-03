#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML preview renderer for generated markdown articles."""

from __future__ import annotations

import html
from pathlib import Path
import re
from typing import Any

from publish_articles import parse_mdx_frontmatter, enrich_article_content


HTML_STYLE = """:root{--bg:#f6f8fb;--card:#fff;--text:#1f2937;--muted:#6b7280;--border:#dbe3ee;--accent:#2563eb;--warning-bg:#fff7ed;--warning-border:#fdba74;--caption:#475569;--quote-bg:#f8fafc;}*{box-sizing:border-box;}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif;background:var(--bg);color:var(--text);line-height:1.75;}.wrap{max-width:920px;margin:40px auto;padding:0 20px 48px;}.article{background:var(--card);border:1px solid var(--border);border-radius:18px;padding:32px;box-shadow:0 12px 32px rgba(15,23,42,.06);}h1,h2{line-height:1.25;color:#111827;}h1{font-size:2rem;margin:0 0 12px;}h2{font-size:1.35rem;margin-top:38px;padding-top:10px;border-top:1px solid var(--border);}.meta{color:var(--muted);font-size:.95rem;margin-bottom:24px;}.box{border-radius:14px;padding:16px 18px;margin:22px 0;border:1px solid var(--border);}.disclaimer{background:var(--warning-bg);border-color:var(--warning-border);}a{color:var(--accent);text-decoration:none;}a:hover{text-decoration:underline;}iframe{border-radius:12px;margin-top:8px;width:100%;max-width:100%;}table{width:100%;border-collapse:collapse;margin:18px 0;border:1px solid var(--border);}th,td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--border);vertical-align:top;}th{background:#f8fafc;}ul{padding-left:22px;}figure.media-block{margin:20px 0 22px;}figure.media-block img{width:100%;display:block;border-radius:12px;max-height:420px;object-fit:cover;}.media-caption{margin-top:8px;color:var(--caption);font-size:.95rem;}.editor-commentary{margin:12px 0 0;padding:14px 16px;border-left:4px solid var(--accent);background:var(--quote-bg);border-radius:10px;}.disclaimer-box{background:var(--warning-bg);border:1px solid var(--warning-border);border-radius:14px;padding:16px 18px;margin:22px 0;}"""


def markdown_to_preview_html(content: str) -> str:
    """Render enriched markdown-like content into preview HTML fragments.

    Args:
        content: Enriched markdown-like content.

    Returns:
        HTML fragment.
    """
    lines = content.splitlines()
    output: list[str] = []
    in_list = False
    in_table = False
    table_rows: list[list[str]] = []

    def flush_list() -> None:
        nonlocal in_list
        if in_list:
            output.append("</ul>")
            in_list = False

    def flush_table() -> None:
        nonlocal in_table, table_rows
        if not in_table:
            return
        header = table_rows[0]
        body_rows = table_rows[1:]
        output.append("<table><thead><tr>" + "".join(f"<th>{html.escape(cell.strip())}</th>" for cell in header) + "</tr></thead><tbody>")
        for row in body_rows:
            output.append("<tr>" + "".join(f"<td>{html.escape(cell.strip())}</td>" for cell in row) + "</tr>")
        output.append("</tbody></table>")
        in_table = False
        table_rows = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_list()
            cells = [cell for cell in stripped.strip("|").split("|")]
            if all(re.fullmatch(r"\s*:?-+:?\s*", cell) for cell in cells):
                continue
            in_table = True
            table_rows.append(cells)
            continue
        flush_table()
        if not stripped:
            flush_list()
            output.append("")
            continue
        if stripped.startswith("<div") or stripped.startswith("</div") or stripped.startswith("<iframe") or stripped.startswith("<a ") or stripped.startswith("<img ") or stripped.startswith("<figure") or stripped.startswith("</figure") or stripped.startswith("<figcaption") or stripped.startswith("<blockquote") or stripped.startswith("</blockquote") or stripped.startswith("<p>"):
            flush_list()
            output.append(line)
            continue
        if stripped.startswith("> **Disclaimer:**"):
            flush_list()
            output.append(f'<div class="box disclaimer"><strong>Disclaimer:</strong> {html.escape(stripped.replace("> **Disclaimer:**", "").strip())}</div>')
            continue
        if stripped.startswith("> **Editor’s note:**") or stripped.startswith("> **Editor's note:**"):
            flush_list()
            note = stripped.split(':', 1)[1].strip() if ':' in stripped else stripped
            note = re.sub(r'^\*\*\s*', '', note)
            output.append(f'<blockquote class="editor-commentary"><strong>Editor’s note:</strong> {html.escape(note)}</blockquote>')
            continue
        if stripped.startswith("## "):
            flush_list()
            title = stripped[3:]
            anchor = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            output.append(f'<h2 id="{anchor}">{html.escape(title)}</h2>')
            continue
        if re.fullmatch(r"(?:[-*])\s+.+", stripped):
            if not in_list:
                output.append("<ul>")
                in_list = True
            item = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', stripped[2:])
            output.append(f"<li>{item}</li>")
            continue
        if re.fullmatch(r"\d+\.\s+.+", stripped):
            flush_list()
            item = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', re.sub(r"^\d+\.\s+", "", stripped))
            output.append(f"<p>{item}</p>")
            continue
        line_html = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', stripped)
        if not line_html.startswith("<"):
            line_html = f"<p>{line_html}</p>"
        output.append(line_html)

    flush_list()
    flush_table()
    return "\n".join(output)


def render_preview_html(markdown_path: Path, output_path: Path | None = None) -> Path:
    """Create a real-media preview HTML file for an article markdown file.

    Args:
        markdown_path: Source markdown file.
        output_path: Optional output HTML path.

    Returns:
        Generated HTML path.
    """
    raw = markdown_path.read_text(encoding="utf-8")
    metadata, body = parse_mdx_frontmatter(raw)
    title = str(metadata.get("title", "Preview"))
    description = str(metadata.get("description", ""))
    enriched = enrich_article_content(markdown_path, body, article_title=title)
    body_html = markdown_to_preview_html(enriched)
    html_doc = f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>{html.escape(title)}</title><meta name="description" content="{html.escape(description)}" /><style>{HTML_STYLE}</style></head><body><div class="wrap"><article class="article"><h1>{html.escape(title)}</h1><div class="meta">Preview article · YMYL layout · real media test</div>{body_html}</article></div></body></html>'''
    target = output_path or markdown_path.with_suffix('.html')
    target.write_text(html_doc, encoding='utf-8')
    return target
