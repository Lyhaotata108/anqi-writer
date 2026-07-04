#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch-safe schema writer for AnQiCMS markdown output.

The AI returns compact JSON content blocks. This module owns final Markdown
assembly, media placeholders, references, and validation. If the model returns
bad JSON, a safe structured fallback is generated so the batch still produces a
reviewable article instead of an empty result.
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
    "the moment the promise meets real life",
]

BAD_MEDIA_TOKENS = ["sample123", "dqw4w9wgxcq", "youtube.com", "youtu.be", "http://", "https://"]

REFERENCE_POOLS: dict[str, list[tuple[str, str]]] = {
    "top_10_listicle": [
        ("NIH Office of Dietary Supplements — Weight Loss Supplements", "https://ods.od.nih.gov/factsheets/WeightLoss-Consumer/"),
        ("MedlinePlus — Weight Control", "https://medlineplus.gov/weightcontrol.html"),
        ("CDC — Healthy Weight", "https://www.cdc.gov/healthy-weight-growth/"),
    ],
    "process_explainer": [
        ("Academy of Nutrition and Dietetics — Find a Nutrition Expert", "https://www.eatright.org/find-a-nutrition-expert"),
        ("Medicare — Medical Nutrition Therapy Services", "https://www.medicare.gov/coverage/medical-nutrition-therapy-services"),
        ("CDC — Healthy Weight", "https://www.cdc.gov/healthy-weight-growth/"),
    ],
    "side_effect_safety": [
        ("MedlinePlus", "https://medlineplus.gov/"),
        ("FDA — Dietary Supplements", "https://www.fda.gov/food/dietary-supplements"),
        ("NIH Office of Dietary Supplements", "https://ods.od.nih.gov/"),
    ],
    "default": [
        ("NIDDK — Weight Management", "https://www.niddk.nih.gov/health-information/weight-management"),
        ("CDC — Healthy Weight", "https://www.cdc.gov/healthy-weight-growth/"),
        ("MedlinePlus — Weight Control", "https://medlineplus.gov/weightcontrol.html"),
    ],
}


class ArticleSchemaError(RuntimeError):
    pass


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "article"


def compact(text: Any, max_len: int | None = None) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).replace("```", "").strip()
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", value)
    value = re.sub(r"https?://\S+", "", value).strip()
    return value[:max_len].rstrip(" ,;:-") if max_len else value


def title_case_keyword(keyword: str) -> str:
    minor = {"a", "an", "and", "as", "at", "by", "for", "in", "is", "of", "on", "or", "the", "to", "vs", "with"}
    out: list[str] = []
    for i, word in enumerate(re.sub(r"[^a-zA-Z0-9]+", " ", keyword).split()):
        lower = word.lower()
        out.append(lower if i and lower in minor else lower[:1].upper() + lower[1:])
    return " ".join(out) or "Article"


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
                data = json.loads(cleaned[start:index + 1])
                if isinstance(data, dict):
                    return data
    raise ArticleSchemaError("AI response JSON object was not closed")


def frontmatter_delimiter_count(markdown: str) -> int:
    return sum(1 for line in markdown.splitlines() if line.strip() == "---")


def list_from(value: Any, min_len: int, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ArticleSchemaError(f"{name} must be a list")
    result = [item for item in value if item not in (None, "")]
    if len(result) < min_len:
        raise ArticleSchemaError(f"{name} needs at least {min_len} items")
    return result


def paragraphs(value: Any, min_len: int = 1) -> list[str]:
    raw = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    result = [compact(x) for x in raw if compact(x)]
    if len(result) < min_len:
        raise ArticleSchemaError("paragraphs too short")
    return result


def normalize_section(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ArticleSchemaError("section must be object")
    heading = compact(raw.get("heading"), 80)
    body = paragraphs(raw.get("paragraphs") or raw.get("body"), 1)
    bullets = [compact(x, 140) for x in raw.get("bullets", []) if compact(x)] if isinstance(raw.get("bullets", []), list) else []
    if not heading:
        raise ArticleSchemaError("section missing heading")
    return {"heading": heading, "paragraphs": body[:3], "bullets": bullets[:5]}


def normalize_table(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ArticleSchemaError("table must be object")
    columns = [compact(x, 40) for x in list_from(raw.get("columns"), 3, "table.columns")][:5]
    rows: list[list[str]] = []
    for row in list_from(raw.get("rows"), 3, "table.rows")[:6]:
        if isinstance(row, dict):
            cells = [compact(row.get(col), 95) for col in columns]
        elif isinstance(row, list):
            cells = [compact(x, 95) for x in row]
        else:
            continue
        while len(cells) < len(columns):
            cells.append("")
        rows.append(cells[:len(columns)])
    if len(rows) < 3:
        raise ArticleSchemaError("table has too few usable rows")
    return {"heading": compact(raw.get("heading") or "Comparison Table", 90), "columns": columns, "rows": rows}


def normalize_faq(raw: Any) -> list[dict[str, str]]:
    faqs: list[dict[str, str]] = []
    for item in list_from(raw, 4, "faq")[:6]:
        if isinstance(item, dict):
            q = compact(item.get("question"), 120).rstrip("?")
            a = compact(item.get("answer"), 360)
            if q and a:
                faqs.append({"question": q, "answer": a})
    if len(faqs) < 4:
        raise ArticleSchemaError("faq has too few usable questions")
    return faqs


def normalize_items(raw: Any, article_type: str) -> list[dict[str, str]]:
    if article_type != "top_10_listicle":
        return []
    items: list[dict[str, str]] = []
    for item in list_from(raw, 10, "items")[:10]:
        if isinstance(item, dict):
            name = compact(item.get("name"), 70)
            summary = compact(item.get("summary"), 260)
            if name and summary:
                items.append({
                    "name": name,
                    "summary": summary,
                    "best_for": compact(item.get("best_for"), 120) or "readers comparing practical fit",
                    "watch_out": compact(item.get("watch_out"), 120) or "quality, tolerance, and claim strength",
                })
    if len(items) < 10:
        raise ArticleSchemaError("top_10_listicle requires 10 usable items")
    return items


def normalize_article_json(data: dict[str, Any], keyword: str, category_id: int, article_type: str) -> dict[str, Any]:
    title = compact(data.get("title"), 95) or title_case_keyword(keyword)
    for phrase in FORBIDDEN_STYLE_PHRASES:
        title = re.sub(re.escape(phrase), "", title, flags=re.I).strip(" -:—")
    description = compact(data.get("description"), 155) or f"A practical, evidence-aware guide to {keyword}, including what matters, what falls short, and what to do next."
    sections = [normalize_section(x) for x in list_from(data.get("sections"), 4, "sections")[:7]]
    return {
        "title": title or title_case_keyword(keyword),
        "description": description,
        "keywords": list(dict.fromkeys([keyword, article_type.replace("_", " "), "evidence aware guide"] + [compact(x, 50) for x in data.get("keywords", [])[:6] if compact(x)])) if isinstance(data.get("keywords", []), list) else [keyword, article_type.replace("_", " "), "evidence aware guide"],
        "category_id": category_id,
        "article_type": article_type,
        "opening": paragraphs(data.get("opening"), 2)[:3],
        "sections": sections,
        "items": normalize_items(data.get("items", []), article_type),
        "table": normalize_table(data.get("table")),
        "faq": normalize_faq(data.get("faq")),
        "next_steps": [compact(x, 180) for x in list_from(data.get("next_steps"), 3, "next_steps")[:5] if compact(x)],
        "fallback_used": False,
    }


def fallback_article_json(keyword: str, category_id: int, article_type: str, classification: dict[str, Any]) -> dict[str, Any]:
    topic = title_case_keyword(keyword)
    title_prefix = {
        "top_10_listicle": f"Best Options for {topic}: What to Compare Before You Choose",
        "comparison_decision": f"{topic}: How to Compare the Real Tradeoffs",
        "side_effect_safety": f"{topic}: Safety Questions, Red Flags, and Next Steps",
        "dosage_guide": f"{topic}: Practical Amounts, Safety Boundaries, and Mistakes to Avoid",
        "timing_guide": f"{topic}: Best Timing, Realistic Timelines, and Common Mistakes",
        "symptom_explainer": f"{topic}: What It Can Mean and What to Track",
        "cost_review": f"{topic}: Cost, Value, and When It May Be Worth It",
        "process_explainer": f"{topic}: What Actually Happens Step by Step",
    }.get(article_type, f"{topic}: What Matters, What Does Not, and What To Do Next")
    opening = [
        f"People searching for {keyword} usually want a clear answer, but the results often mix marketing claims, personal stories, and medical-sounding advice without explaining what should actually guide a decision.",
        "This guide uses a practical editorial framework: what the question really means, what evidence-aware readers should compare, what can go wrong, and what to track before taking action.",
    ]
    sections = [
        {"heading": "Why This Search Gets Confusing", "paragraphs": [f"The phrase {keyword} can point to several different concerns at once: expected results, safety, cost, timing, and whether the advice applies to a real person rather than a headline."], "bullets": []},
        {"heading": "What Actually Matters", "paragraphs": ["The useful answer usually depends on the reader's baseline health, current medications, tolerance for side effects, budget, consistency, and whether a qualified professional should be involved."], "bullets": []},
        {"heading": "What Can Under-Deliver", "paragraphs": ["Generic claims under-deliver when they skip context. A strategy that sounds simple may be irrelevant if it ignores appetite, sleep, glucose control, medication history, or daily adherence."], "bullets": []},
        {"heading": "Who Should Be More Careful", "paragraphs": ["People with chronic conditions, pregnancy concerns, medication use, disordered eating history, or unusual symptoms should treat online guidance as a starting point rather than a personal plan."], "bullets": []},
        {"heading": "What To Track Before Deciding", "paragraphs": ["Track the variables that change the decision: symptoms, timing, dose or amount, food intake, sleep, energy, lab markers where relevant, and any side effects that appear after a change."], "bullets": []},
    ]
    items = []
    if article_type == "top_10_listicle":
        items = [{"name": f"Option {i}", "summary": f"A practical option to compare for {keyword}. Evaluate claim strength, ingredient quality, safety, and whether it fits the reader's routine.", "best_for": "comparison shoppers", "watch_out": "overstated results or weak evidence"} for i in range(1, 11)]
    table = {
        "heading": "Decision Framework Table",
        "columns": ["Factor", "Why It Matters", "What To Check"],
        "rows": [
            ["Evidence", "Stronger evidence lowers guesswork", "Look for reputable medical or public-health sources"],
            ["Safety", "YMYL topics can affect health decisions", "Check medications, conditions, pregnancy, and symptoms"],
            ["Adherence", "A plan only works if it fits daily life", "Match cost, timing, taste, and routine"],
            ["Expectations", "Overpromising leads to poor decisions", "Separate short-term signals from sustainable outcomes"],
        ],
    }
    faq = [
        {"question": f"Is {keyword} enough on its own", "answer": "Usually no. Most health and weight-related outcomes depend on the broader context: baseline habits, medical history, consistency, and whether the approach is appropriate for the individual."},
        {"question": "What should I check first", "answer": "Start with safety, current medications, symptoms, realistic expectations, and whether the topic requires a qualified clinician or registered dietitian."},
        {"question": "How do I know if a claim is exaggerated", "answer": "Be cautious when a page promises fast results, ignores risks, does not explain tradeoffs, or relies only on anecdotes instead of credible evidence."},
        {"question": "When should I ask a professional", "answer": "Ask a qualified professional if you have a medical condition, take medication, are pregnant or breastfeeding, have abnormal symptoms, or plan to make a major diet, supplement, or medication change."},
    ]
    return {
        "title": title_prefix,
        "description": f"A practical, evidence-aware guide to {keyword}, including what to compare, what to avoid, and what to do next."[:155],
        "keywords": [keyword, article_type.replace("_", " "), "evidence aware guide"],
        "category_id": category_id,
        "article_type": article_type,
        "opening": opening,
        "sections": sections,
        "items": items,
        "table": table,
        "faq": faq,
        "next_steps": [
            "Clarify the exact decision you are trying to make before reading more advice.",
            "Check safety constraints such as medications, symptoms, pregnancy, or chronic conditions.",
            "Track one or two measurable signals for two to four weeks instead of chasing every claim.",
        ],
        "fallback_used": True,
    }


def render_paragraphs(items: list[str]) -> str:
    return "\n\n".join(compact(x) for x in items if compact(x))


def render_section(section: dict[str, Any]) -> str:
    lines = [f"## {section['heading']}", "", render_paragraphs(section["paragraphs"])]
    for bullet in section.get("bullets", []):
        lines.append(f"- {bullet}")
    return "\n".join(lines).strip()


def render_items(items: list[dict[str, str]]) -> str:
    if not items:
        return ""
    lines = ["## The 10 Options People Usually Compare", ""]
    for i, item in enumerate(items, 1):
        lines.extend([f"### {i}. {item['name']}", item["summary"], "", f"- **Best for:** {item['best_for']}", f"- **Watch out for:** {item['watch_out']}", ""])
    return "\n".join(lines).strip()


def render_table(table: dict[str, Any]) -> str:
    cols = table["columns"]
    lines = [f"## {table['heading']}", "", "| " + " | ".join(c.replace("|", "/") for c in cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in table["rows"]:
        lines.append("| " + " | ".join(compact(cell).replace("|", "/") for cell in row) + " |")
    return "\n".join(lines)


def render_faq(faq: list[dict[str, str]]) -> str:
    lines = ["## Frequently Asked Questions", ""]
    for item in faq:
        lines.extend([f"### {item['question']}?", item["answer"], ""])
    return "\n".join(lines).strip()


def reference_pool(article_type: str, classification: dict[str, Any]) -> list[tuple[str, str]]:
    entity = str(classification.get("entity") or "").lower()
    if "cbd" in entity:
        return [
            ("FDA — Cannabis and Cannabis-Derived Products", "https://www.fda.gov/news-events/public-health-focus/fda-regulation-cannabis-and-cannabis-derived-products-including-cannabidiol-cbd"),
            ("NCCIH — Cannabis and Cannabinoids", "https://www.nccih.nih.gov/health/cannabis-marijuana-and-cannabinoids-what-you-need-to-know"),
            ("MedlinePlus", "https://medlineplus.gov/"),
        ]
    return REFERENCE_POOLS.get(article_type, REFERENCE_POOLS["default"])


def image_query(keyword: str, article_type: str) -> str:
    return f"{keyword} {article_type.replace('_', ' ')} editorial guide"


def youtube_query(keyword: str, article_type: str) -> str:
    return f"{keyword} {article_type.replace('_', ' ')} explained"


def sanitize_final_markdown(markdown: str) -> str:
    # Preserve only line-level frontmatter delimiters; remove body separators and leaked metadata.
    lines = markdown.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            second = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
            front = lines[:second + 1]
            body = lines[second + 1:]
        except StopIteration:
            front, body = [], lines
    else:
        front, body = [], lines
    cleaned_body: list[str] = []
    for line in body:
        stripped = line.strip()
        if stripped == "---":
            continue
        if re.match(r"^(title|description|keywords|category_id|tag|country|region|locality)\s*:", stripped, flags=re.I):
            continue
        cleaned_body.append(line)
    markdown = "\n".join(front + [""] + cleaned_body).strip() + "\n"
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown


def assemble_markdown(article: dict[str, Any], keyword: str, category_id: int, classification: dict[str, Any]) -> str:
    article_type = article["article_type"]
    today = datetime.now().strftime("%A, %B %d, %Y")
    parts: list[str] = [
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
        f"Last updated: {today}",
        "",
        "> **Disclaimer:** This content is for general educational purposes only and does not replace individualized professional advice.",
        "",
        render_paragraphs(article["opening"]),
        "",
        f"[IMAGE: {image_query(keyword, article_type)}]",
        "",
    ]
    used_items = False
    for section in article["sections"]:
        heading_lower = section["heading"].lower()
        if article_type == "top_10_listicle" and any(t in heading_lower for t in ["10 option", "top 10", "options people"]):
            if not used_items:
                parts.extend([render_items(article["items"]), ""])
                used_items = True
            continue
        if heading_lower == article["table"]["heading"].lower():
            continue
        parts.extend([render_section(section), ""])
    if article_type == "top_10_listicle" and not used_items:
        parts.extend([render_items(article["items"]), ""])
    parts.extend([
        render_table(article["table"]),
        "",
        f"[YOUTUBE_VIDEO: {youtube_query(keyword, article_type)}]",
        "",
        render_faq(article["faq"]),
        "",
        "## The Next Step Without Guesswork",
        "",
    ])
    for i, step in enumerate(article["next_steps"], 1):
        parts.append(f"{i}. {step}")
    parts.extend(["", "## AI Disclosure", "This article draft was prepared with AI assistance and assembled through a structured editorial workflow.", "", "## References"])
    for name, url in reference_pool(article_type, classification):
        parts.append(f"- [{name}]({url})")
    if article.get("fallback_used"):
        parts.append("- Internal fallback note: the AI JSON response was not usable, so this reviewable draft was assembled from the safe batch template.")
    parts.extend(["", "## Author", "**Evidence-Aware Wellness Editor**"])
    return sanitize_final_markdown("\n".join(parts))


def validate_final_markdown(markdown: str, article_type: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    lower = markdown.lower()
    body = markdown.split("---", 2)[-1] if markdown.startswith("---") else markdown
    if frontmatter_delimiter_count(markdown) != 2:
        issues.append("frontmatter line delimiter count is not exactly 2")
    if re.search(r"(?im)^(title|description|keywords|category_id|tag|country|region|locality)\s*:", body):
        issues.append("body contains leaked metadata fields")
    if "\n---\n" in body:
        issues.append("body contains markdown separator ---")
    for phrase in FORBIDDEN_STYLE_PHRASES:
        if phrase in lower:
            issues.append(f"forbidden phrase: {phrase}")
    yt = re.findall(r"\[YOUTUBE_VIDEO:\s*([^\]]+)\]", markdown, flags=re.I)
    if len(yt) != 1:
        issues.append("must contain exactly one YouTube query placeholder")
    elif any(token in yt[0].lower() for token in BAD_MEDIA_TOKENS):
        issues.append("YouTube placeholder must be a query, not a URL or fake ID")
    if markdown.count("[IMAGE:") != 1:
        issues.append("must contain exactly one image placeholder")
    for section in ["## Frequently Asked Questions", "## AI Disclosure", "## References", "## Author"]:
        if markdown.count(section) != 1:
            issues.append(f"{section} must appear exactly once")
    if markdown.count("### ") < 4:
        issues.append("FAQ must contain at least four H3 questions")
    if "|" not in markdown:
        issues.append("missing markdown table")
    if markdown.count("## ") < 6:
        issues.append("fewer than 6 H2 sections")
    if article_type == "top_10_listicle" and len(re.findall(r"^###\s+\d+\.\s+", markdown, flags=re.M)) < 10:
        issues.append("top_10_listicle must contain at least 10 numbered H3 options")
    return not issues, issues


def build_writer_prompt(keyword: str, category_id: int, article_type: str, route: dict[str, Any], classification: dict[str, Any], secondary_keywords: list[str] | None = None, retry_notes: list[str] | None = None) -> str:
    secondary_keywords = secondary_keywords or []
    retry_notes = retry_notes or []
    item_rule = "items must contain exactly 10 objects" if article_type == "top_10_listicle" else "items must be []"
    return f"""Return ONLY valid compact JSON. No Markdown. No code fences. No URLs. No frontmatter.
Keyword: {keyword}
Category: {category_id}
Article type: {article_type}
Classification: {classification}
Route reason: {route.get('reason')}
Secondary keywords: {secondary_keywords[:12]}
Retry notes: {retry_notes[:5]}
Rules:
- Keep it compact enough that the JSON completes.
- opening: exactly 2 paragraphs, 45-80 words each.
- sections: exactly 5 objects. Each section has heading, paragraphs array with 1-2 paragraphs, optional bullets array.
- table: 3-4 columns and exactly 4 rows.
- faq: exactly 4 question/answer objects.
- next_steps: exactly 3 strings.
- {item_rule}.
- No fake studies, fake patients, fake clinical data, fake YouTube links, or fake citations.
- Do not use: {FORBIDDEN_STYLE_PHRASES}.
Schema:
{{"title":"","description":"","keywords":[],"opening":[],"sections":[{{"heading":"","paragraphs":[],"bullets":[]}}],"items":[],"table":{{"heading":"","columns":[],"rows":[]}},"faq":[{{"question":"","answer":""}}],"next_steps":[]}}
"""


def generate_article_json(controller: PipelineController, prompt: str) -> dict[str, Any]:
    text = controller._call_gemini_with_retry(prompt, attempts=2)
    if not text:
        raise RuntimeError("Sample-style writer failed; check GEMINI_API_KEY and GEMINI_BASE_URL in local_api_keys.json")
    return extract_json_object(text)


def generate_sample_style_article(keyword: str, workspace_root: Path, output_root: Path, category_id: int, keyword_id: int | None = None, secondary_keywords: list[str] | None = None, progress=None) -> PipelineResult:
    clean = clean_keyword(keyword)
    if clean.keyword_status == "skip":
        raise RuntimeError(f"Skipped keyword: {keyword} ({clean.reason})")
    clean_keyword_value = clean.clean_keyword
    classification = asdict(classify_keyword(clean_keyword_value))
    route_obj = route_article_type(clean_keyword_value, classification)
    route = asdict(route_obj)
    article_type = route_obj.article_type
    if progress:
        progress("Classifying", 12, f"{clean.keyword_status}: {clean_keyword_value} · {article_type}")

    controller = PipelineController(workspace_root, output_root=output_root)
    retry_notes: list[str] = []
    last_error: Exception | None = None
    article_data: dict[str, Any] | None = None

    for attempt in range(1, 4):
        if progress:
            progress("Writing", 25 + attempt * 12, f"Generating compact JSON attempt {attempt}: {clean_keyword_value}")
        try:
            prompt = build_writer_prompt(clean_keyword_value, category_id, article_type, route, classification, secondary_keywords, retry_notes)
            raw_json = generate_article_json(controller, prompt)
            article_data = normalize_article_json(raw_json, clean_keyword_value, category_id, article_type)
            markdown = assemble_markdown(article_data, clean_keyword_value, category_id, classification)
            ok, issues = validate_final_markdown(markdown, article_type)
            if ok:
                break
            retry_notes = issues
            last_error = ArticleSchemaError("; ".join(issues))
            article_data = None
        except Exception as error:
            retry_notes = [str(error)]
            last_error = error
    if article_data is None:
        if progress:
            progress("Fallback", 70, f"AI JSON failed; assembling safe fallback draft: {clean_keyword_value}")
        article_data = fallback_article_json(clean_keyword_value, category_id, article_type, classification)
        markdown = assemble_markdown(article_data, clean_keyword_value, category_id, classification)
        ok, issues = validate_final_markdown(markdown, article_type)
        if not ok:
            raise RuntimeError(f"Fallback markdown failed validation after AI error {last_error}: {issues}")

    output_root.mkdir(parents=True, exist_ok=True)
    markdown_path = output_root / f"ui_{slugify(clean_keyword_value)}.md"
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


def normalize_markdown(markdown: str, keyword: str, category_id: int, article_type: str) -> str:
    return sanitize_final_markdown(markdown)


def build_repair_prompt(markdown: str, issues: list[str], keyword: str, category_id: int, article_type: str) -> str:
    return build_writer_prompt(keyword, category_id, article_type, {}, {}, retry_notes=issues)


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
