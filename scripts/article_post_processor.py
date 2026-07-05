#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clean generated Markdown articles and build local HTML previews.

Post-processing goals:
- Add a stable H2 Table of Contents.
- Remove duplicate Last updated lines.
- Convert AI-only XML-ish blocks such as <Sequence>/<Step> to Markdown.
- Remove CMS-unfriendly LaTeX fragments.
- Ensure a final ## Important Note section exists.
- Keep image-placeholder.png for CMS image replacement.
- Preserve real YouTube embeds when present.
"""

from __future__ import annotations
from pathlib import Path
import html
import re
from typing import Any

YOUTUBE_RE = re.compile(r"youtube\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/", re.I)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def slugify(text: str) -> str:
    slug = str(text or "").lower().strip()
    slug = re.sub(r"[`*_~<>\[\](){}:;,.!?$\\/]+", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "section"


def split_front_matter(markdown: str) -> tuple[str, str]:
    text = str(markdown or "").strip()
    match = re.match(r"^(---\s*\n.*?\n---\s*\n)(.*)$", text, flags=re.S)
    if match:
        return match.group(1).strip() + "\n", match.group(2).strip()
    return "", text


def extract_front_matter_value(front_matter: str, key: str) -> str:
    pattern = rf"^{re.escape(key)}:\s*[\"']?(.*?)[\"']?\s*$"
    match = re.search(pattern, front_matter, flags=re.M)
    return normalize(match.group(1)) if match else ""


def remove_duplicate_last_updated(body: str) -> str:
    lines = body.splitlines()
    seen = False
    out: list[str] = []
    for line in lines:
        plain = line.strip().strip("*").strip()
        if plain.lower().startswith("last updated:"):
            if seen:
                continue
            seen = True
            out.append(plain)
        else:
            out.append(line)
    return "\n".join(out)


def parse_attrs(attr_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for key, value in re.findall(r"(\w+)=['\"]([^'\"]*)['\"]", attr_text or ""):
        attrs[key.lower()] = value
    return attrs


def convert_sequence_steps(body: str) -> str:
    def replace_sequence(match: re.Match[str]) -> str:
        inner = match.group(1)
        steps: list[str] = []
        for i, step_match in enumerate(re.finditer(r"<Step\b([^>]*)>(.*?)</Step>", inner, flags=re.I | re.S), start=1):
            attrs = parse_attrs(step_match.group(1))
            title = normalize(attrs.get("title") or f"Step {i}")
            subtitle = normalize(attrs.get("subtitle", ""))
            content = normalize(re.sub(r"<[^>]+>", " ", step_match.group(2)))
            heading = f"{i}. **{title}**"
            if subtitle:
                heading += f" — {subtitle}"
            if content:
                heading += f"\n   {content}"
            steps.append(heading)
        if not steps:
            return normalize(re.sub(r"<[^>]+>", " ", inner))
        return "\n\n".join(steps)

    body = re.sub(r"<Sequence\b[^>]*>(.*?)</Sequence>", replace_sequence, body, flags=re.I | re.S)
    body = re.sub(r"</?(?:Sequence|Step)\b[^>]*>", "", body, flags=re.I)
    return body


def normalize_latex(body: str) -> str:
    replacements = {
        r"\$\\text\{kg/m\}\^2\$": "kg/m²",
        r"\$\\text\{kg/m\^2\}\$": "kg/m²",
        r"\\text\{kg/m\}\^2": "kg/m²",
        r"\\text\{kg/m\^2\}": "kg/m²",
        r"\\geq": "≥",
        r"\\ge": "≥",
        r"\\leq": "≤",
        r"\\le": "≤",
    }
    out = body
    for pattern, value in replacements.items():
        out = re.sub(pattern, value, out)
    out = re.sub(r"\\text\{([^}]*)\}", r"\1", out)
    out = out.replace("$", "")
    out = out.replace("\\", "")
    return out


def fix_common_typos(body: str) -> str:
    fixes = {
        "deducible requirements": "deductible requirements",
        "lean lean muscle mass": "lean muscle mass",
        "clear-cutting glucose": "clearing glucose",
        "Internet": "internet",
    }
    out = body
    for wrong, right in fixes.items():
        out = re.sub(re.escape(wrong), right, out, flags=re.I)
    return out


def heading_lines(body: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for line in body.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if not match:
            continue
        title = normalize(match.group(1))
        if title.lower() == "table of contents":
            continue
        items.append((title, slugify(title)))
    return items


def remove_existing_toc(body: str) -> str:
    pattern = r"\n?##\s+Table of Contents\s*\n(?:\s*[-*]\s+\[[^\]]+\]\([^\)]+\)\s*\n?)+"
    return re.sub(pattern, "\n", body, flags=re.I).strip()


def build_toc(body: str) -> str:
    items = heading_lines(body)
    if not items:
        return ""
    lines = ["## Table of Contents", ""]
    for title, anchor in items:
        lines.append(f"- [{title}](#{anchor})")
    return "\n".join(lines).strip()


def insert_toc(body: str) -> str:
    body = remove_existing_toc(body)
    toc = build_toc(body)
    if not toc:
        return body
    marker = "## The Short Version"
    idx = body.find(marker)
    if idx >= 0:
        return body[:idx].rstrip() + "\n\n" + toc + "\n\n" + body[idx:].lstrip()
    lines = body.split("\n\n")
    insert_at = min(3, max(1, len(lines)))
    lines.insert(insert_at, toc)
    return "\n\n".join(lines)


def default_disclaimer(category: str) -> str:
    if category == "cbd":
        return (
            "This article is for educational purposes only and does not provide medical advice. CBD products can vary in quality and may interact with medications, health conditions, pregnancy, breastfeeding, or drug testing. Speak with a qualified healthcare professional before using CBD for a health-related purpose."
        )
    if category == "blood":
        return (
            "This article is for educational purposes only and is not a diagnosis or treatment plan. Blood pressure, blood sugar, cholesterol, oxygen, and other blood-related readings require clinical context. Seek urgent medical care for severe symptoms, very abnormal readings, or rapidly worsening patterns."
        )
    return (
        "This article is for educational purposes only and does not provide medical advice. Weight-loss medications, supplements, diet changes, and exercise plans may not be appropriate for every person. Speak with a qualified healthcare professional before starting, stopping, or changing any medication, supplement, or major health routine."
    )


def ensure_important_note(body: str, category: str) -> str:
    body = re.sub(r"^###\s+Important Note", "## Important Note", body, flags=re.I | re.M)
    if re.search(r"^##\s+Important Note\b", body, flags=re.I | re.M):
        return body

    patterns = [
        r"\*\*Important Note(?: and Medical Disclaimer)?[:：]\*\*\s*(.*)$",
        r"\*Medical Disclaimer[:：]\s*(.*?)\*\s*$",
        r">\s*\*\*Medical Disclaimer[:：]\*\*\s*(.*)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, flags=re.I | re.S)
        if match:
            note = normalize(match.group(1))
            body = body[: match.start()].rstrip()
            return body + "\n\n## Important Note\n\n" + (note or default_disclaimer(category))
    return body.rstrip() + "\n\n## Important Note\n\n" + default_disclaimer(category)


def clean_blank_lines(body: str) -> str:
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"\n\s+\n", "\n\n", body)
    return body.strip()


def post_process_markdown(markdown: str, category: str = "weight_loss") -> tuple[str, list[str]]:
    notes: list[str] = []
    front, body = split_front_matter(markdown)
    if not category:
        category = extract_front_matter_value(front, "category") or "weight_loss"

    before = body
    body = remove_duplicate_last_updated(body)
    if body != before:
        notes.append("deduped_last_updated")

    before = body
    body = convert_sequence_steps(body)
    if body != before:
        notes.append("converted_sequence_steps")

    before = body
    body = normalize_latex(body)
    if body != before:
        notes.append("removed_latex")

    before = body
    body = fix_common_typos(body)
    if body != before:
        notes.append("fixed_common_typos")

    before = body
    body = ensure_important_note(body, category)
    if body != before:
        notes.append("ensured_important_note")

    before = body
    body = insert_toc(body)
    if body != before:
        notes.append("inserted_toc")

    body = clean_blank_lines(body)
    return (front + body + "\n").strip() + "\n", notes


def inline_markdown(text: str) -> str:
    out = html.escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\*(.+?)\*", r"<em>\1</em>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r'<a href="\2">\1</a>', out)
    return out


def render_table(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.match(r"^:?-{3,}:?$", cell) for cell in cells):
            continue
        rows.append(cells)
    if not rows:
        return ""
    head = rows[0]
    body = rows[1:]
    html_rows = ["<table><thead><tr>" + "".join(f"<th>{inline_markdown(c)}</th>" for c in head) + "</tr></thead><tbody>"]
    for row in body:
        html_rows.append("<tr>" + "".join(f"<td>{inline_markdown(c)}</td>" for c in row) + "</tr>")
    html_rows.append("</tbody></table>")
    return "\n".join(html_rows)


def markdown_body_to_html(body: str) -> str:
    lines = body.splitlines()
    out: list[str] = []
    paragraph: list[str] = []
    list_open = False
    table_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + inline_markdown(" ".join(paragraph)) + "</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            out.append(render_table(table_lines))
            table_lines = []

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph(); close_list(); flush_table()
            continue
        if line.strip().startswith("<iframe"):
            flush_paragraph(); close_list(); flush_table()
            out.append(f'<div class="video-wrap">{line.strip()}</div>')
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph(); close_list()
            table_lines.append(line)
            continue
        else:
            flush_table()
        image_match = re.match(r"!\[([^\]]*)\]\(([^\)]+)\)", line.strip())
        if image_match:
            flush_paragraph(); close_list()
            alt = html.escape(image_match.group(1) or "Image placeholder")
            src = image_match.group(2)
            if src == "image-placeholder.png":
                out.append(f'<figure class="image-placeholder"><div>Image Placeholder</div><figcaption>{alt}</figcaption></figure>')
            else:
                out.append(f'<figure><img src="{html.escape(src)}" alt="{alt}"><figcaption>{alt}</figcaption></figure>')
            continue
        h = re.match(r"^(#{1,4})\s+(.+)$", line)
        if h:
            flush_paragraph(); close_list(); flush_table()
            level = len(h.group(1))
            title = h.group(2).strip()
            anchor = slugify(title)
            out.append(f'<h{level} id="{anchor}">{inline_markdown(title)}</h{level}>')
            continue
        if re.match(r"^[-*]\s+", line):
            flush_paragraph(); flush_table()
            if not list_open:
                out.append("<ul>")
                list_open = True
            item = re.sub(r"^[-*]\s+", "", line)
            out.append(f"<li>{inline_markdown(item)}</li>")
            continue
        if re.match(r"^\d+\.\s+", line):
            flush_paragraph(); flush_table()
            if not list_open:
                out.append("<ul>")
                list_open = True
            item = re.sub(r"^\d+\.\s+", "", line)
            out.append(f"<li>{inline_markdown(item)}</li>")
            continue
        if line.startswith(">"):
            flush_paragraph(); close_list(); flush_table()
            out.append("<blockquote>" + inline_markdown(line.lstrip("> ")) + "</blockquote>")
            continue
        paragraph.append(line)

    flush_paragraph(); close_list(); flush_table()
    return "\n".join(out)


def build_preview_html(markdown: str) -> str:
    front, body = split_front_matter(markdown)
    title = extract_front_matter_value(front, "title") or "Article Preview"
    content = markdown_body_to_html(body)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ --text:#1f2937; --muted:#6b7280; --line:#e5e7eb; --accent:#0f766e; --bg:#f8fafc; --card:#ffffff; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; line-height:1.75; }}
.article-shell {{ max-width: 920px; margin: 0 auto; padding: 48px 22px 80px; }}
.article-card {{ background:var(--card); border:1px solid var(--line); border-radius:24px; padding:48px; box-shadow:0 18px 60px rgba(15,23,42,.08); }}
h1 {{ font-size: clamp(34px, 5vw, 56px); line-height:1.05; letter-spacing:-.045em; margin:0 0 22px; }}
h2 {{ font-size: clamp(24px, 3vw, 34px); line-height:1.18; letter-spacing:-.025em; margin:52px 0 16px; padding-top:8px; }}
h3 {{ font-size:22px; margin:34px 0 12px; }}
p {{ margin: 0 0 18px; font-size: 18px; }}
a {{ color:var(--accent); text-decoration:none; }}
ul {{ padding-left: 24px; margin: 0 0 24px; }}
li {{ margin: 8px 0; font-size: 18px; }}
blockquote {{ border-left:4px solid var(--accent); background:#ecfdf5; padding:16px 20px; margin:24px 0; border-radius:12px; }}
table {{ width:100%; border-collapse: collapse; margin:28px 0; overflow:hidden; border-radius:16px; font-size:16px; }}
th, td {{ border:1px solid var(--line); padding:14px 16px; vertical-align:top; }}
th {{ background:#f1f5f9; text-align:left; }}
.image-placeholder {{ border:2px dashed #cbd5e1; background:#f8fafc; border-radius:22px; min-height:260px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:var(--muted); margin:32px 0; text-align:center; }}
.image-placeholder div {{ font-size:22px; font-weight:700; }}
.image-placeholder figcaption {{ max-width:680px; margin-top:10px; padding:0 20px; }}
.video-wrap {{ position:relative; padding-bottom:56.25%; height:0; overflow:hidden; border-radius:22px; margin:34px 0; background:#111827; }}
.video-wrap iframe {{ position:absolute; top:0; left:0; width:100%; height:100%; border:0; }}
#table-of-contents + ul {{ background:#f8fafc; border:1px solid var(--line); border-radius:18px; padding:22px 22px 22px 44px; }}
@media (max-width: 700px) {{ .article-card {{ padding:28px 18px; border-radius:18px; }} p, li {{ font-size:16px; }} }}
</style>
</head>
<body>
<main class="article-shell"><article class="article-card">
{content}
</article></main>
</body>
</html>
"""


def write_preview_html(markdown: str, html_path: str | Path) -> None:
    path = Path(html_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_preview_html(markdown), encoding="utf-8")
