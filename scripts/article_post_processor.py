#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clean generated Markdown articles and build local HTML previews."""

from __future__ import annotations
from pathlib import Path
import html
import re

YOUTUBE_RE = re.compile(r"youtube\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/", re.I)
BR_TOKEN = "__HTML_BR_TOKEN__"
DOLLAR_TOKEN = "__HTML_DOLLAR_ENTITY_TOKEN__"


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


def clean_title_text(title: str) -> str:
    out = normalize(title)
    bad_suffixes = [
        " — After the First Try", " - After the First Try", ": After the First Try",
        " — After Your First Try", " - After Your First Try",
    ]
    for suffix in bad_suffixes:
        if out.endswith(suffix):
            out = out[: -len(suffix)].strip()
    return re.sub(r"\s+—\s+After the First Try\b", "", out)


def clean_title_artifacts(front: str, body: str) -> tuple[str, str, bool]:
    changed = False

    def replace_title_line(match: re.Match[str]) -> str:
        nonlocal changed
        key, quote, value = match.group(1), match.group(2) or "", match.group(3)
        cleaned = clean_title_text(value)
        changed = changed or cleaned != value
        return f"{key}: {quote}{cleaned}{quote}"

    front2 = re.sub(r"^(title)\s*:\s*([\"']?)(.*?)(?:\2)\s*$", replace_title_line, front, flags=re.M)

    def replace_h1(match: re.Match[str]) -> str:
        nonlocal changed
        value = match.group(1).strip()
        cleaned = clean_title_text(value)
        changed = changed or cleaned != value
        return f"# {cleaned}"

    body2 = re.sub(r"^#\s+(.+?)\s*$", replace_h1, body, count=1, flags=re.M)
    return front2, body2, changed


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


def remove_horizontal_separators(body: str) -> str:
    return "\n".join(line for line in body.splitlines() if line.strip() not in {"---", "***", "___"})


def parse_attrs(attr_text: str) -> dict[str, str]:
    return {key.lower(): value for key, value in re.findall(r"(\w+)=['\"]([^'\"]*)['\"]", attr_text or "")}


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
        return "\n\n".join(steps) if steps else normalize(re.sub(r"<[^>]+>", " ", inner))

    body = re.sub(r"<Sequence\b[^>]*>(.*?)</Sequence>", replace_sequence, body, flags=re.I | re.S)
    return re.sub(r"</?(?:Sequence|Step)\b[^>]*>", "", body, flags=re.I)


def clean_box_line(line: str) -> str:
    item = line.strip().strip("` ")
    if re.fullmatch(r"[+\-|\s=]+", item):
        return ""
    if item.startswith("|") and item.endswith("|"):
        item = item.strip("|").strip()
    return normalize(item)


def convert_quick_take_block(lines: list[str]) -> str:
    bullets: list[str] = []
    current = ""
    for raw in lines:
        item = clean_box_line(raw)
        if not item or item.upper() == "THE QUICK TAKE":
            continue
        if item.startswith("*"):
            if current:
                bullets.append(current)
            current = re.sub(r"^\*\s*", "", item).strip()
        elif current:
            current += " " + item
        else:
            bullets.append(item)
    if current:
        bullets.append(current)
    if not bullets:
        return ""
    return "> **Quick Take**\n\n" + "\n".join(f"- {bullet}" for bullet in bullets)


def convert_diagram_block(lines: list[str]) -> str:
    converted: list[str] = []
    for raw in lines:
        item = clean_box_line(raw)
        if not item:
            continue
        match = re.match(r"^\[([^\]]+)\]\s*-+>\s*(.+)$", item)
        if match:
            converted.append(f"- **{match.group(1).strip()}:** {match.group(2).strip()}")
        else:
            converted.append(f"> {item}")
    return "\n".join(converted)


def convert_code_block(match: re.Match[str]) -> str:
    raw = match.group(2)
    lines = raw.splitlines()
    joined = "\n".join(lines)
    if "THE QUICK TAKE" in joined.upper():
        converted = convert_quick_take_block(lines)
    elif re.search(r"\[[^\]]+\]\s*-+>", joined):
        converted = convert_diagram_block(lines)
    else:
        cleaned = [clean_box_line(line) for line in lines]
        converted = "\n".join(f"> {line}" for line in cleaned if line)
    return "\n\n" + converted.strip() + "\n\n" if converted.strip() else "\n"


def convert_code_fences(body: str) -> str:
    body = re.sub(r"```([a-zA-Z0-9_-]+)?\s*\n(.*?)\n```", convert_code_block, body, flags=re.S)
    return re.sub(r"``+", "", body)


def normalize_latex(body: str) -> str:
    """Remove LaTeX artifacts while preserving rendered currency amounts.

    The AI quality checker treats literal dollar signs as possible LaTeX delimiters, so
    currency such as $900 is stored as the HTML entity &#36;900. Browsers and CMS pages
    render this as a normal dollar sign.
    """
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
    out = re.sub(r"\$(?=\d)", "&#36;", out)
    out = re.sub(r"\\text\{([^}]*)\}", r"\1", out)
    out = re.sub(r"\$([^$\n]{1,80})\$", lambda m: m.group(1), out)
    out = out.replace("$", "")
    return out.replace("\\", "")


def fix_common_typos(body: str) -> str:
    fixes = {
        "deducible requirements": "deductible requirements",
        "lean lean muscle mass": "lean muscle mass",
        "cellular cellular voltage": "cellular voltage",
        "an completely separate": "a completely separate",
        "as a effortless": "as an effortless",
        "ly, underlying systemic issues": "Underlying systemic issues",
        "internet algorithms": "Internet algorithms",
        "It mimic GLP-1": "It mimics GLP-1",
        "it mimic GLP-1": "it mimics GLP-1",
        "on a introductory dose": "on an introductory dose",
        "a introductory dose": "an introductory dose",
        "During the first fortnight": "During the first two weeks",
        "during the first fortnight": "during the first two weeks",
        "which bound significant amounts of water": "which bind significant amounts of water",
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
    match = re.search(r"^##\s+", body, flags=re.M)
    if match:
        return body[: match.start()].rstrip() + "\n\n" + toc + "\n\n" + body[match.start():].lstrip()
    return body.rstrip() + "\n\n" + toc


def default_disclaimer(category: str) -> str:
    if category == "cbd":
        return "This article is for educational purposes only and does not provide medical advice. CBD products can vary in quality and may interact with medications, health conditions, pregnancy, breastfeeding, or drug testing. Speak with a qualified healthcare professional before using CBD for a health-related purpose."
    if category == "blood":
        return "This article is for educational purposes only and is not a diagnosis or treatment plan. Blood pressure, blood sugar, cholesterol, oxygen, and other blood-related readings require clinical context. Seek urgent medical care for severe symptoms, very abnormal readings, or rapidly worsening patterns."
    return "This article is for educational purposes only and does not provide medical advice. Weight-loss medications, supplements, diet changes, and exercise plans may not be appropriate for every person. Speak with a qualified healthcare professional before starting, stopping, or changing any medication, supplement, or major health routine."


def remove_blockquote_important_notes(body: str) -> tuple[str, list[str]]:
    captured: list[str] = []
    lines = body.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith(">") and re.search(r"Important Note|Medical Disclaimer", line, flags=re.I):
            block: list[str] = []
            while i < len(lines) and (lines[i].lstrip().startswith(">") or not lines[i].strip()):
                block.append(lines[i]); i += 1
                if i < len(lines) and not lines[i - 1].strip() and not lines[i].lstrip().startswith(">"):
                    break
            text = re.sub(r"^>\s?", "", "\n".join(block), flags=re.M)
            text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
            text = re.sub(r"\*\*(?:Important Note(?: and Medical Disclaimer)?|Medical Disclaimer)[:：]?\*\*", "", text, flags=re.I)
            text = normalize(text)
            if text:
                captured.append(text)
            continue
        out.append(line); i += 1
    return "\n".join(out), captured


def remove_inline_important_notes(body: str) -> tuple[str, list[str]]:
    captured: list[str] = []
    patterns = [
        r"\*\*Important Note(?: and Medical Disclaimer)?[:：]\*\*\s*(.*?)(?=\n##\s+|\Z)",
        r"\*Medical Disclaimer[:：]\s*(.*?)\*\s*(?=\n##\s+|\Z)",
    ]
    out = body
    for pattern in patterns:
        def repl(match: re.Match[str]) -> str:
            text = normalize(match.group(1))
            if text:
                captured.append(text)
            return "\n"
        out = re.sub(pattern, repl, out, flags=re.I | re.S)
    return out, captured


def remove_h2_important_sections(body: str) -> tuple[str, list[str]]:
    captured: list[str] = []
    pattern = r"^##\s+Important Note\b.*?(?=^##\s+|\Z)"
    def repl(match: re.Match[str]) -> str:
        section = match.group(0)
        content = re.sub(r"^##\s+Important Note\b.*\n?", "", section, flags=re.I)
        content = normalize(content)
        if content:
            captured.append(content)
        return "\n"
    return re.sub(pattern, repl, body, flags=re.I | re.M | re.S), captured


def ensure_important_note(body: str, category: str) -> str:
    body = re.sub(r"^###\s+Important Note", "## Important Note", body, flags=re.I | re.M)
    body, block_notes = remove_blockquote_important_notes(body)
    body, inline_notes = remove_inline_important_notes(body)
    body, h2_notes = remove_h2_important_sections(body)
    note = next((item for item in h2_notes + block_notes + inline_notes if len(item) > 40), "") or default_disclaimer(category)
    return body.rstrip() + "\n\n## Important Note\n\n" + note


def md_link(label: str, url: str) -> str:
    return f"[{label}]({url})"


def reference_items(category: str, body: str) -> list[str]:
    text = body.lower()
    refs: list[str] = []
    if "ozempic" in text:
        refs.append(md_link("FDA Drugs@FDA: Ozempic (semaglutide) approval and labeling", "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=209637"))
    if "wegovy" in text or "semaglutide" in text:
        refs.append(md_link("FDA Drugs@FDA: Wegovy (semaglutide) approval and labeling", "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=215256"))
        refs.append(md_link("MedlinePlus: Semaglutide Injection", "https://medlineplus.gov/druginfo/meds/a618008.html"))
        refs.append(md_link("New England Journal of Medicine: STEP 1 semaglutide trial", "https://www.nejm.org/doi/full/10.1056/NEJMoa2032183"))
    if "metformin" in text:
        refs.append(md_link("MedlinePlus: Metformin", "https://medlineplus.gov/druginfo/meds/a696005.html"))
        refs.append(md_link("Diabetes Prevention Program Research Group publication archive", "https://dppos.bsc.gwu.edu/web/dppos/publications"))
    if "zepbound" in text or "tirzepatide" in text:
        refs.append(md_link("FDA Drugs@FDA: Zepbound (tirzepatide) approval and labeling", "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=217806"))
        refs.append(md_link("New England Journal of Medicine: SURMOUNT-1 tirzepatide trial", "https://www.nejm.org/doi/full/10.1056/NEJMoa2206038"))
    if "orlistat" in text or "alli" in text:
        refs.append(md_link("MedlinePlus: Orlistat", "https://medlineplus.gov/druginfo/meds/a601244.html"))
    if "berberine" in text:
        refs.append(md_link("NIH NCCIH: Berberine", "https://www.nccih.nih.gov/health/berberine-and-goldenseal"))
    if "cbd" in text or category == "cbd":
        refs.append(md_link("FDA: Cannabis and Cannabis-Derived Products, Including CBD", "https://www.fda.gov/news-events/public-health-focus/fda-regulation-cannabis-and-cannabis-derived-products-including-cannabidiol-cbd"))
        refs.append(md_link("NIH NCCIH: Cannabis, Marijuana and Cannabinoids", "https://www.nccih.nih.gov/health/cannabis-marijuana-and-cannabinoids-what-you-need-to-know"))
    if category == "blood" or any(term in text for term in ["blood pressure", "blood sugar", "a1c", "cholesterol"]):
        refs.append(md_link("CDC: High Blood Pressure", "https://www.cdc.gov/high-blood-pressure/"))
        refs.append(md_link("MedlinePlus: Blood Glucose Tests", "https://medlineplus.gov/lab-tests/blood-glucose-test/"))
        refs.append(md_link("MedlinePlus: Cholesterol Levels", "https://medlineplus.gov/lab-tests/cholesterol-levels/"))
    if category == "weight_loss" or any(term in text for term in ["weight loss", "supplement", "proprietary blend"]):
        refs.append(md_link("NIH Office of Dietary Supplements: Weight Loss Fact Sheet", "https://ods.od.nih.gov/factsheets/WeightLoss-Consumer/"))
        refs.append(md_link("FDA: Dietary Supplements", "https://www.fda.gov/food/dietary-supplements"))
    if not refs:
        refs.append(md_link("MedlinePlus: Health Topics", "https://medlineplus.gov/healthtopics.html"))
    deduped: list[str] = []
    seen = set()
    for ref in refs:
        key = ref.lower()
        if key not in seen:
            seen.add(key); deduped.append(ref)
    return deduped[:8]


def ensure_references(body: str, category: str) -> str:
    body = re.sub(r"^##\s+References\b.*?(?=^##\s+|\Z)", "", body, flags=re.I | re.M | re.S).rstrip()
    refs = reference_items(category, body)
    lines = ["## References", ""] + [f"- {ref}" for ref in refs]
    return body + "\n\n" + "\n".join(lines)


def clean_blank_lines(body: str) -> str:
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"\n\s+\n", "\n\n", body)
    return body.strip()


def post_process_markdown(markdown: str, category: str = "weight_loss") -> tuple[str, list[str]]:
    notes: list[str] = []
    front, body = split_front_matter(markdown)
    if not category:
        category = extract_front_matter_value(front, "category") or "weight_loss"

    front, body, title_changed = clean_title_artifacts(front, body)
    if title_changed:
        notes.append("cleaned_title_artifacts")

    transforms = [
        ("deduped_last_updated", remove_duplicate_last_updated),
        ("removed_horizontal_separators", remove_horizontal_separators),
        ("converted_sequence_steps", convert_sequence_steps),
        ("converted_code_fences", convert_code_fences),
        ("removed_latex_preserved_currency", normalize_latex),
        ("fixed_common_typos", fix_common_typos),
    ]
    for note, func in transforms:
        before = body
        body = func(body)
        if body != before:
            notes.append(note)

    before = body
    body = ensure_important_note(body, category)
    if body != before:
        notes.append("consolidated_important_note")

    before = body
    body = ensure_references(body, category)
    if body != before:
        notes.append("ensured_linked_references")

    before = body
    body = insert_toc(body)
    if body != before:
        notes.append("inserted_toc")

    body = clean_blank_lines(body)
    return (front + body + "\n").strip() + "\n", notes


def inline_markdown(text: str) -> str:
    safe = re.sub(r"<br\s*/?>", BR_TOKEN, str(text or ""), flags=re.I)
    safe = safe.replace("&#36;", DOLLAR_TOKEN)
    out = html.escape(safe)
    out = out.replace(BR_TOKEN, "<br>").replace(DOLLAR_TOKEN, "&#36;")
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\*(.+?)\*", r"<em>\1</em>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', out)
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
    head, body = rows[0], rows[1:]
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
            out.append("</ul>"); list_open = False

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            out.append(render_table(table_lines)); table_lines = []

    for raw in lines:
        line = raw.rstrip(); stripped = line.strip()
        if not stripped:
            flush_paragraph(); close_list(); flush_table(); continue
        if stripped in {"---", "***", "___"}:
            flush_paragraph(); close_list(); flush_table(); out.append("<hr>"); continue
        if stripped.startswith("<iframe"):
            flush_paragraph(); close_list(); flush_table(); out.append(f'<div class="video-wrap">{stripped}</div>'); continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph(); close_list(); table_lines.append(line); continue
        else:
            flush_table()
        image_match = re.match(r"!\[([^\]]*)\]\(([^\)]+)\)", stripped)
        if image_match:
            flush_paragraph(); close_list()
            alt = html.escape(image_match.group(1) or "Image placeholder"); src = image_match.group(2)
            if src == "image-placeholder.png":
                out.append(f'<figure class="image-placeholder"><div>Image Placeholder</div><figcaption>{alt}</figcaption></figure>')
            else:
                out.append(f'<figure><img src="{html.escape(src)}" alt="{alt}"><figcaption>{alt}</figcaption></figure>')
            continue
        h = re.match(r"^(#{1,4})\s+(.+)$", line)
        if h:
            flush_paragraph(); close_list(); flush_table()
            level = len(h.group(1)); title = h.group(2).strip(); anchor = slugify(title)
            out.append(f'<h{level} id="{anchor}">{inline_markdown(title)}</h{level}>'); continue
        if re.match(r"^[-*]\s+", line):
            flush_paragraph(); flush_table()
            if not list_open:
                out.append("<ul>"); list_open = True
            item = re.sub(r"^[-*]\s+", "", line)
            out.append(f"<li>{inline_markdown(item)}</li>"); continue
        if re.match(r"^\d+\.\s+", line):
            flush_paragraph(); flush_table()
            if not list_open:
                out.append("<ul>"); list_open = True
            item = re.sub(r"^\d+\.\s+", "", line)
            out.append(f"<li>{inline_markdown(item)}</li>"); continue
        if line.startswith(">"):
            flush_paragraph(); close_list(); flush_table(); out.append("<blockquote>" + inline_markdown(line.lstrip("> ")) + "</blockquote>"); continue
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
hr {{ border:0; border-top:1px solid var(--line); margin:34px 0; }}
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
