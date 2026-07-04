#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Schema-driven sample-style article writer for AnQiCMS markdown output.

The AI no longer writes final Markdown. It only returns strict JSON content blocks.
This module owns the frontmatter, body structure, media placeholders, references,
AI disclosure, and final Markdown assembly so batch output stays import-safe.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import argparse
import json
import re
from typing import Any

from article_type_router import route_article_type
from intent_classifier import classify_keyword
from keyword_cleaner import clean_keyword
from pipeline_controller import PipelineController, PipelineResult
from preview_renderer import render_preview_html
from publish_articles import load_article


FORBIDDEN_STYLE_PHRASES = [
    "sounds easy until real life starts testing it",
    "promise meets real life",
    "someone starts",
    "ordinary life returns",
    "a realistic composite scenario looks like this",
    "the promise behind",
    "the moment the promise meets real life",
    "the first result is not the whole story",
]

BAD_MEDIA_TOKENS = ["sample123", "dqw4w9wgxcq", "youtube.com", "youtu.be", "http://", "https://"]

REFERENCE_POOLS: dict[str, list[tuple[str, str]]] = {
    "top_10_listicle": [
        ("NIH Office of Dietary Supplements — Weight Loss Supplements", "https://ods.od.nih.gov/factsheets/WeightLoss-Consumer/"),
        ("NCCIH — Green Tea", "https://www.nccih.nih.gov/health/green-tea"),
        ("MedlinePlus — Weight Control", "https://medlineplus.gov/weightcontrol.html"),
    ],
    "evidence_review": [
        ("NIDDK — Weight Management", "https://www.niddk.nih.gov/health-information/weight-management"),
        ("CDC — Healthy Weight", "https://www.cdc.gov/healthy-weight-growth/"),
        ("NIH Office of Dietary Supplements — Weight Loss Supplements", "https://ods.od.nih.gov/factsheets/WeightLoss-Consumer/"),
        ("MedlinePlus — Weight Control", "https://medlineplus.gov/weightcontrol.html"),
    ],
    "process_explainer": [
        ("Academy of Nutrition and Dietetics — Find a Nutrition Expert", "https://www.eatright.org/find-a-nutrition-expert"),
        ("Medicare — Medical Nutrition Therapy Services", "https://www.medicare.gov/coverage/medical-nutrition-therapy-services"),
        ("CDC — Healthy Weight", "https://www.cdc.gov/healthy-weight-growth/"),
        ("MedlinePlus — Weight Control", "https://medlineplus.gov/weightcontrol.html"),
    ],
    "comparison_decision": [
        ("MedlinePlus", "https://medlineplus.gov/"),
        ("NIH Office of Dietary Supplements", "https://ods.od.nih.gov/"),
        ("CDC — Healthy Weight", "https://www.cdc.gov/healthy-weight-growth/"),
    ],
    "side_effect_safety": [
        ("MedlinePlus", "https://medlineplus.gov/"),
        ("FDA — Dietary Supplements", "https://www.fda.gov/food/dietary-supplements"),
        ("NIH Office of Dietary Supplements", "https://ods.od.nih.gov/"),
    ],
    "generic_editorial": [
        ("CDC — Healthy Weight", "https://www.cdc.gov/healthy-weight-growth/"),
        ("MedlinePlus", "https://medlineplus.gov/"),
        ("NIDDK — Weight Management", "https://www.niddk.nih.gov/health-information/weight-management"),
    ],
}

STYLE_GUIDE = """
Write like a health SEO editor creating a high-information feature, not a generic template page.
The target feel is: strong search-confusion opening, editorial judgment, practical tradeoffs,
concrete examples, evidence-aware language, useful tables, FAQ, and a next-step protocol.
Do not invent private trials, named patients, clinic data, measured lab outcomes, or client results.
Allowed: published evidence suggests, practical tracking framework, illustrative comparison, composite scenario.
Forbidden: fake experiments, fake URLs, fake DOIs, fake YouTube URLs, fake client stories.
""".strip()

ARTICLE_TYPE_GUIDES = {
    "top_10_listicle": """
The reader expects a real listicle. Provide ranked or clearly enumerated options.
The JSON must include exactly 10 items in the items array. Each item needs name, summary, best_for, and watch_out.
""".strip(),
    "evidence_review": """
Use an evidence-review / tracking-framework style. Discuss what helps, what under-delivers,
and what a reader could track over 30/60/90 days without pretending you ran a private study.
""".strip(),
    "process_explainer": """
Explain a professional process step by step. The reader should understand what happens first,
what data is gathered, how decisions are made, and what changes over follow-up.
""".strip(),
    "comparison_decision": """
Make the decision practical. Clarify where each option wins, where it disappoints,
and how a reader should choose based on constraints.
""".strip(),
    "side_effect_safety": """
Write a safety-aware guide. Cover common effects, warning signs, who should be careful,
interaction questions, and what to ask a qualified professional.
""".strip(),
    "generic_editorial": """
Write a useful editorial guide with a clear search-intent opening, specific examples,
a table, FAQ, and next steps. Avoid vague lifestyle filler.
""".strip(),
}


class ArticleSchemaError(RuntimeError):
    """Raised when the AI JSON cannot be used for safe article assembly."""


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "article"


def compact(text: Any) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = value.replace("```", "").strip()
    return value


def strip_markdown_link(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    return compact(text)


def strip_code_fences(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|markdown|md)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = strip_code_fences(text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        raise ArticleSchemaError("AI response did not contain a JSON object")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        ch = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start:index + 1]
                data = json.loads(candidate)
                if not isinstance(data, dict):
                    raise ArticleSchemaError("JSON root is not an object")
                return data
    raise ArticleSchemaError("AI response JSON object was not closed")


def title_case_keyword(keyword: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9]+", " ", keyword).split()
    minor = {"a", "an", "and", "as", "at", "by", "for", "in", "is", "of", "on", "or", "the", "to", "vs", "with"}
    output: list[str] = []
    for i, word in enumerate(words):
        lower = word.lower()
        output.append(lower if i and lower in minor else lower[:1].upper() + lower[1:])
    return " ".join(output) or "Article"


def clean_title(title: str, keyword: str) -> str:
    title = strip_markdown_link(title)
    title = re.sub(r"^title\s*:\s*", "", title, flags=re.I).strip(" -")
    if not title or len(title.split()) < 4:
        title = title_case_keyword(keyword)
    for phrase in FORBIDDEN_STYLE_PHRASES:
        title = re.sub(re.escape(phrase), "", title, flags=re.I).strip(" -:—")
    return title[:95].rstrip(" ,;:-")


def clean_description(description: str, keyword: str) -> str:
    description = strip_markdown_link(description)
    description = re.sub(r"^description\s*:\s*", "", description, flags=re.I).strip()
    if not description:
        description = f"A practical, evidence-aware guide to {keyword}, including what matters, what falls short, and what to do next."
    return description[:155].rstrip(" ,;:-")


def require_list(value: Any, name: str, min_len: int = 1) -> list[Any]:
    if not isinstance(value, list):
        raise ArticleSchemaError(f"{name} must be a list")
    cleaned = [item for item in value if item not in (None, "")]
    if len(cleaned) < min_len:
        raise ArticleSchemaError(f"{name} must contain at least {min_len} items")
    return cleaned


def normalize_paragraphs(value: Any, min_len: int = 1) -> list[str]:
    if isinstance(value, str):
        parts = [value]
    elif isinstance(value, list):
        parts = [compact(item) for item in value]
    else:
        parts = []
    result = [p for p in parts if p]
    if len(result) < min_len:
        raise ArticleSchemaError("paragraph list too short")
    return result


def normalize_section(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ArticleSchemaError("section must be an object")
    heading = compact(raw.get("heading"))
    if not heading:
        raise ArticleSchemaError("section missing heading")
    paragraphs = normalize_paragraphs(raw.get("paragraphs") or raw.get("body"), min_len=1)
    bullets_raw = raw.get("bullets") or []
    bullets = [compact(item) for item in bullets_raw if compact(item)] if isinstance(bullets_raw, list) else []
    return {"heading": heading, "paragraphs": paragraphs, "bullets": bullets}


def normalize_table(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ArticleSchemaError("table must be an object")
    heading = compact(raw.get("heading") or "Comparison Table")
    columns = [compact(x) for x in require_list(raw.get("columns"), "table.columns", 3)]
    rows_raw = require_list(raw.get("rows"), "table.rows", 3)
    rows: list[list[str]] = []
    for row in rows_raw:
        if isinstance(row, dict):
            row_values = [compact(row.get(col)) for col in columns]
        elif isinstance(row, list):
            row_values = [compact(x) for x in row]
        else:
            continue
        while len(row_values) < len(columns):
            row_values.append("")
        rows.append(row_values[:len(columns)])
    if len(rows) < 3:
        raise ArticleSchemaError("table.rows must contain at least 3 usable rows")
    return {"heading": heading, "columns": columns, "rows": rows}


def normalize_faq(raw: Any) -> list[dict[str, str]]:
    items = require_list(raw, "faq", 4)
    faqs: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        question = compact(item.get("question"))
        answer = compact(item.get("answer"))
        if question and answer:
            faqs.append({"question": question.rstrip("?"), "answer": answer})
    if len(faqs) < 4:
        raise ArticleSchemaError("faq must contain at least 4 usable Q&A items")
    return faqs[:6]


def normalize_items(raw: Any, article_type: str) -> list[dict[str, str]]:
    if article_type != "top_10_listicle":
        return []
    items = require_list(raw, "items", 10)
    normalized: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = compact(item.get("name"))
        summary = compact(item.get("summary"))
        best_for = compact(item.get("best_for"))
        watch_out = compact(item.get("watch_out"))
        if name and summary:
            normalized.append({
                "name": name,
                "summary": summary,
                "best_for": best_for or "readers comparing practical fit",
                "watch_out": watch_out or "quality, tolerance, and dosage claims",
            })
    if len(normalized) < 10:
        raise ArticleSchemaError("top_10_listicle requires at least 10 usable items")
    return normalized[:10]


def normalize_article_json(data: dict[str, Any], keyword: str, category_id: int, article_type: str) -> dict[str, Any]:
    title = clean_title(compact(data.get("title")), keyword)
    description = clean_description(compact(data.get("description")), keyword)
    opening = normalize_paragraphs(data.get("opening"), min_len=2)
    sections = [normalize_section(item) for item in require_list(data.get("sections"), "sections", 4)]
    table = normalize_table(data.get("table"))
    faq = normalize_faq(data.get("faq"))
    next_steps = [compact(x) for x in require_list(data.get("next_steps"), "next_steps", 3)]
    next_steps = [x for x in next_steps if x][:6]
    items = normalize_items(data.get("items"), article_type)
    keywords = [keyword, article_type.replace("_", " "), "evidence aware guide"]
    extra_keywords = data.get("keywords")
    if isinstance(extra_keywords, list):
        keywords.extend(compact(x) for x in extra_keywords[:6] if compact(x))
    return {
        "title": title,
        "description": description,
        "keywords": list(dict.fromkeys([k for k in keywords if k])),
        "category_id": category_id,
        "article_type": article_type,
        "opening": opening,
        "sections": sections,
        "table": table,
        "faq": faq,
        "next_steps": next_steps,
        "items": items,
    }


def markdown_escape_table_cell(value: str) -> str:
    return compact(value).replace("|", "/")


def render_paragraphs(paragraphs: list[str]) -> str:
    return "\n\n".join(compact(p) for p in paragraphs if compact(p))


def render_section(section: dict[str, Any]) -> str:
    parts = [f"## {section['heading']}", "", render_paragraphs(section["paragraphs"])]
    bullets = section.get("bullets") or []
    if bullets:
        parts.extend(["", *[f"- {bullet}" for bullet in bullets]])
    return "\n".join(part for part in parts if part != "")


def render_table(table: dict[str, Any]) -> str:
    columns = table["columns"]
    lines = [f"## {table['heading']}", ""]
    lines.append("| " + " | ".join(markdown_escape_table_cell(c) for c in columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in table["rows"]:
        lines.append("| " + " | ".join(markdown_escape_table_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_items(items: list[dict[str, str]]) -> str:
    if not items:
        return ""
    lines = ["## The 10 Options People Usually Compare", ""]
    for index, item in enumerate(items, start=1):
        lines.append(f"### {index}. {item['name']}")
        lines.append(item["summary"])
        lines.append("")
        lines.append(f"- **Best for:** {item['best_for']}")
        lines.append(f"- **Watch out for:** {item['watch_out']}")
        lines.append("")
    return "\n".join(lines).strip()


def render_faq(faq: list[dict[str, str]]) -> str:
    lines = ["## Frequently Asked Questions", ""]
    for item in faq:
        lines.append(f"### {item['question']}?")
        lines.append(item["answer"])
        lines.append("")
    return "\n".join(lines).strip()


def render_next_steps(steps: list[str]) -> str:
    lines = ["## The Next Step Without Guesswork", ""]
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. {step}")
    return "\n".join(lines)


def build_image_query(keyword: str, article_type: str) -> str:
    if article_type == "process_explainer":
        return f"{keyword} professional consultation planning notes"
    if article_type == "top_10_listicle":
        return f"{keyword} comparison ingredients lifestyle"
    if article_type == "side_effect_safety":
        return f"{keyword} safety checklist health notes"
    return f"{keyword} evidence based wellness guide"


def build_youtube_query(keyword: str, article_type: str) -> str:
    if article_type == "process_explainer":
        return f"registered dietitian weight loss consultation explained"
    if article_type == "top_10_listicle":
        return f"{keyword} evidence explained"
    if article_type == "side_effect_safety":
        return f"{keyword} side effects safety explained"
    if article_type == "comparison_decision":
        return f"{keyword} comparison explained"
    return f"{keyword} evidence explained"


def reference_pool(article_type: str, classification: dict[str, Any]) -> list[tuple[str, str]]:
    entity = str(classification.get("entity") or "").lower()
    if "cbd" in entity:
        return [
            ("FDA — Cannabis and Cannabis-Derived Products", "https://www.fda.gov/news-events/public-health-focus/fda-regulation-cannabis-and-cannabis-derived-products-including-cannabidiol-cbd"),
            ("NCCIH — Cannabis and Cannabinoids", "https://www.nccih.nih.gov/health/cannabis-marijuana-and-cannabinoids-what-you-need-to-know"),
            ("MedlinePlus", "https://medlineplus.gov/"),
        ]
    return REFERENCE_POOLS.get(article_type, REFERENCE_POOLS["generic_editorial"])


def assemble_markdown(article: dict[str, Any], keyword: str, category_id: int, classification: dict[str, Any]) -> str:
    article_type = article["article_type"]
    today = datetime.now().strftime("%A, %B %d, %Y")
    frontmatter = [
        "---",
        f"title: {article['title']}",
        f"description: {article['description']}",
        f"keywords: {', '.join(article['keywords'])}",
        f"category_id: {category_id}",
        "tag: ymyl content, evidence aware guide",
        "country: US",
        "region:",
        "locality:",
        "---",
        "",
    ]
    body: list[str] = [
        f"Last updated: {today}",
        "",
        "> **Disclaimer:** This content is for general educational purposes only and does not replace individualized professional advice.",
        "",
        render_paragraphs(article["opening"]),
        "",
        f"[IMAGE: {build_image_query(keyword, article_type)}]",
        "",
    ]

    used_item_section = False
    for section in article["sections"]:
        heading_lower = section["heading"].lower()
        if article_type == "top_10_listicle" and any(token in heading_lower for token in ("10 option", "options people", "top 10")):
            if not used_item_section:
                body.append(render_items(article["items"]))
                body.append("")
                used_item_section = True
            continue
        if heading_lower in {article["table"]["heading"].lower(), "comparison table"}:
            continue
        body.append(render_section(section))
        body.append("")

    if article_type == "top_10_listicle" and not used_item_section:
        body.append(render_items(article["items"]))
        body.append("")

    body.append(render_table(article["table"]))
    body.append("")
    body.append(f"[YOUTUBE_VIDEO: {build_youtube_query(keyword, article_type)}]")
    body.append("")
    body.append(render_faq(article["faq"]))
    body.append("")
    body.append(render_next_steps(article["next_steps"]))
    body.append("")
    body.append("## AI Disclosure")
    body.append("This article draft was prepared with AI assistance and assembled through a structured editorial workflow.")
    body.append("")
    body.append("## References")
    for name, url in reference_pool(article_type, classification):
        body.append(f"- [{name}]({url})")
    body.append("")
    body.append("## Author")
    body.append("**Evidence-Aware Wellness Editor**")

    markdown = "\n".join(frontmatter + body).strip() + "\n"
    return sanitize_final_markdown(markdown)


def strip_body_metadata(markdown: str) -> str:
    if not markdown.startswith("---"):
        return markdown
    parts = markdown.split("---", 2)
    if len(parts) < 3:
        return markdown
    frontmatter = "---" + parts[1] + "---\n"
    body = parts[2]
    cleaned_lines: list[str] = []
    for line in body.splitlines():
        if re.match(r"^(title|description|keywords|category_id|tag|country|region|locality)\s*:", line.strip(), flags=re.I):
            continue
        if line.strip() == "---":
            continue
        cleaned_lines.append(line)
    return frontmatter + "\n".join(cleaned_lines).strip() + "\n"


def sanitize_final_markdown(markdown: str) -> str:
    markdown = strip_body_metadata(markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = re.sub(r"\[YOUTUBE_VIDEO:\s*\[([^\]]+)\]\([^)]+\)\s*\]", r"[YOUTUBE_VIDEO: \1]", markdown, flags=re.I)
    markdown = re.sub(r"\[YOUTUBE_VIDEO:\s*https?://[^\]]+\]", "[YOUTUBE_VIDEO: related health explainer]", markdown, flags=re.I)
    return markdown.strip() + "\n"


def validate_final_markdown(markdown: str, article_type: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    lower = markdown.lower()
    body = markdown.split("---", 2)[-1] if markdown.startswith("---") else markdown
    if markdown.count("---") != 2:
        issues.append("frontmatter delimiter count is not exactly 2")
    if re.search(r"(?im)^(title|description|keywords|category_id|tag|country|region|locality)\s*:", body):
        issues.append("body contains leaked metadata fields")
    if "\n---\n" in body:
        issues.append("body contains markdown separator ---")
    for phrase in FORBIDDEN_STYLE_PHRASES:
        if phrase in lower:
            issues.append(f"forbidden phrase: {phrase}")
    if any(token in lower for token in ("sample123", "dqw4w9wgxcq")):
        issues.append("fake media token found")
    yt_matches = re.findall(r"\[YOUTUBE_VIDEO:\s*([^\]]+)\]", markdown, flags=re.I)
    if len(yt_matches) != 1:
        issues.append("must contain exactly one YouTube query placeholder")
    else:
        yt_lower = yt_matches[0].lower()
        if any(token in yt_lower for token in BAD_MEDIA_TOKENS):
            issues.append("YouTube placeholder must be a query, not a URL or fake ID")
    if markdown.count("[IMAGE:") != 1:
        issues.append("must contain exactly one image placeholder")
    if markdown.count("## Frequently Asked Questions") != 1:
        issues.append("FAQ section must appear exactly once")
    if markdown.count("## AI Disclosure") != 1:
        issues.append("AI Disclosure must appear exactly once")
    if markdown.count("## References") != 1:
        issues.append("References must appear exactly once")
    if markdown.count("## Author") != 1:
        issues.append("Author must appear exactly once")
    if markdown.count("### ") < 4:
        issues.append("FAQ must contain at least four H3 questions")
    if "|" not in markdown:
        issues.append("missing markdown table")
    if markdown.count("## ") < 6:
        issues.append("fewer than 6 H2 sections")
    if article_type == "top_10_listicle":
        numbered = len(re.findall(r"^###\s+\d+\.\s+", markdown, flags=re.M))
        if numbered < 10:
            issues.append("top_10_listicle must contain at least 10 numbered H3 options")
    return not issues, issues


def build_writer_prompt(keyword: str, category_id: int, article_type: str, route: dict[str, Any], classification: dict[str, Any], secondary_keywords: list[str] | None = None, retry_notes: list[str] | None = None) -> str:
    secondary_keywords = secondary_keywords or []
    secondary_text = "\n".join(f"- {item}" for item in secondary_keywords[:20]) or "- none provided"
    retry_text = "\n".join(f"- {item}" for item in (retry_notes or [])) or "- none"
    item_rule = "If article_type is top_10_listicle, items must contain exactly 10 objects." if article_type == "top_10_listicle" else "If article_type is not top_10_listicle, items may be an empty array."
    return f"""You are a senior YMYL-aware health SEO editor.

Return STRICT JSON only. Do not return Markdown. Do not include code fences. Do not include frontmatter. Do not include references. Do not include YouTube URLs. Do not include image placeholders.

Primary keyword: {keyword}
Category ID: {category_id}
Article type: {article_type}
Classification: {classification}
Route reason: {route.get('reason')}
Title style: {route.get('title_style')}
Secondary keywords to cover naturally:
{secondary_text}

Style guide:
{STYLE_GUIDE}

Article-type guide:
{ARTICLE_TYPE_GUIDES.get(article_type, ARTICLE_TYPE_GUIDES['generic_editorial'])}

Retry / failure notes to fix:
{retry_text}

Required JSON schema:
{{
  "title": "clickable but safe article title, no fake experiment claims",
  "description": "meta description under 155 characters",
  "keywords": ["natural secondary keyword 1", "natural secondary keyword 2"],
  "opening": ["paragraph 1: search confusion and stakes", "paragraph 2: what the article will clarify"],
  "sections": [
    {{"heading": "H2 heading", "paragraphs": ["paragraph", "paragraph"], "bullets": ["optional bullet"]}}
  ],
  "items": [
    {{"name": "option name", "summary": "specific explanation", "best_for": "who it fits", "watch_out": "main caution"}}
  ],
  "table": {{"heading": "specific comparison table heading", "columns": ["Column 1", "Column 2", "Column 3"], "rows": [["cell", "cell", "cell"], ["cell", "cell", "cell"], ["cell", "cell", "cell"]]}},
  "faq": [{{"question": "real search question", "answer": "answer"}}, {{"question": "real search question", "answer": "answer"}}, {{"question": "real search question", "answer": "answer"}}, {{"question": "real search question", "answer": "answer"}}],
  "next_steps": ["step 1", "step 2", "step 3"]
}}

Hard rules:
- sections must contain at least 5 objects.
- opening must contain exactly 2 to 3 paragraphs.
- table must contain at least 3 rows.
- faq must contain at least 4 questions.
- next_steps must contain at least 3 steps.
- {item_rule}
- Never claim you personally tracked, tested, treated, coached, or measured people unless real data was provided.
- Use evidence-aware language without inventing study titles, DOIs, internal tests, private patients, or fake citations.
- Do not use these phrases: {', '.join(FORBIDDEN_STYLE_PHRASES)}.
- Do not output `title:`, `description:`, YAML, `---`, Markdown tables, `[IMAGE:]`, `[YOUTUBE_VIDEO:]`, URLs, References, AI Disclosure, or Author.
- JSON only."""


def build_repair_prompt(markdown: str, issues: list[str], keyword: str, category_id: int, article_type: str) -> str:
    issue_text = "\n".join(f"- {issue}" for issue in issues)
    return build_writer_prompt(
        keyword=keyword,
        category_id=category_id,
        article_type=article_type,
        route={"reason": "repair failed markdown", "title_style": "sample-style safe headline", "required_structure": []},
        classification={},
        secondary_keywords=[],
        retry_notes=["Previous markdown failed final validation", *issues, "Return JSON only; the program will assemble Markdown"],
    ) + f"\n\nFailed markdown for context only, do not copy formatting:\n{markdown[:5000]}"


def normalize_markdown(markdown: str, keyword: str, category_id: int, article_type: str) -> str:
    """Compatibility sanitizer for external callers; new generation uses JSON assembly."""
    return sanitize_final_markdown(markdown)


def generate_article_json(controller: PipelineController, prompt: str) -> dict[str, Any]:
    text = controller._call_gemini_with_retry(prompt, attempts=2)
    if not text:
        raise RuntimeError("Sample-style Gemini writer failed; check GEMINI_API_KEY and GEMINI_BASE_URL in local_api_keys.json")
    return extract_json_object(text)


def generate_sample_style_article(
    keyword: str,
    workspace_root: Path,
    output_root: Path,
    category_id: int,
    keyword_id: int | None = None,
    secondary_keywords: list[str] | None = None,
    progress=None,
) -> PipelineResult:
    clean = clean_keyword(keyword)
    if clean.keyword_status == "skip":
        raise RuntimeError(f"Skipped keyword: {keyword} ({clean.reason})")
    clean_keyword_value = clean.clean_keyword
    classification_obj = classify_keyword(clean_keyword_value)
    classification = asdict(classification_obj)
    route_obj = route_article_type(clean_keyword_value, classification)
    route = asdict(route_obj)
    article_type = route_obj.article_type

    if progress:
        progress("Classifying", 12, f"{clean.keyword_status}: {clean_keyword_value} · {article_type}")

    controller = PipelineController(workspace_root, output_root=output_root)
    retry_notes: list[str] = []
    last_error: Exception | None = None
    markdown = ""
    article_data: dict[str, Any] | None = None

    for attempt in range(1, 4):
        if progress:
            progress("Writing", 25 + attempt * 12, f"Generating JSON article blocks attempt {attempt}: {clean_keyword_value}")
        prompt = build_writer_prompt(clean_keyword_value, category_id, article_type, route, classification, secondary_keywords, retry_notes)
        try:
            raw_json = generate_article_json(controller, prompt)
            article_data = normalize_article_json(raw_json, clean_keyword_value, category_id, article_type)
            markdown = assemble_markdown(article_data, clean_keyword_value, category_id, classification)
            ok, issues = validate_final_markdown(markdown, article_type)
            if ok:
                break
            retry_notes = issues
            last_error = ArticleSchemaError("; ".join(issues))
        except Exception as error:
            retry_notes = [str(error)]
            last_error = error
    else:
        raise RuntimeError(f"Sample-style JSON writer failed final validation: {last_error}")

    if not markdown or article_data is None:
        raise RuntimeError("Sample-style JSON writer did not produce usable markdown")

    output_root.mkdir(parents=True, exist_ok=True)
    slug = slugify(clean_keyword_value)
    markdown_path = output_root / f"ui_{slug}.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    preview_path = render_preview_html(markdown_path)
    article = load_article(markdown_path)
    if progress:
        progress("Ready_to_Publish", 90, f"Schema-assembled article ready: {markdown_path.name}")
    return PipelineResult(
        keyword=clean_keyword_value,
        stage1_1_path=markdown_path,
        stage1_2_path=markdown_path,
        markdown_path=markdown_path,
        preview_path=preview_path,
        title=str(article.get("title", clean_keyword_value)),
        description=str(article.get("description", "")),
        publish_result=None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate one schema-driven sample-style AnQiCMS article.")
    parser.add_argument("keyword", nargs="+")
    parser.add_argument("--category", type=int, default=1)
    parser.add_argument("--workspace", default="/Users/hjg/Documents/anqicms-writer")
    args = parser.parse_args()
    root = Path(args.workspace)
    result = generate_sample_style_article(" ".join(args.keyword), root, root, args.category)
    print(result.markdown_path)


if __name__ == "__main__":
    main()
