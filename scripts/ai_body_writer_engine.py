#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate high-quality Markdown articles from body blueprints with an OpenAI-compatible API.

Batch design:
- One article = one API request.
- Outputs are written immediately so interrupted runs can resume.
- Existing Markdown files are skipped unless --overwrite is set.
- The API key is read from --api-key or OPENAI_API_KEY.
- The API base URL is read from --api-base or OPENAI_BASE_URL.
- The model is read from --model or OPENAI_MODEL.

This script is intentionally provider-light: it uses only Python's standard
library and the common /v1/chat/completions interface.
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_ARTICLES_DIR = "output/ai_articles"
DEFAULT_QUEUE_OUTPUT = "output/ai_article_publish_queue.csv"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def slugify(text: str) -> str:
    slug = str(text or "").lower().replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:80].strip("-") or "article"


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", str(text or "")))


def split_pipe(text: str) -> list[str]:
    return [part.strip() for part in str(text or "").split("|") if part.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def clean_category(row: dict[str, str]) -> str:
    raw = str(row.get("category") or "weight_loss").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"cbd", "hemp"}:
        return "cbd"
    if raw in {"blood", "blood_health", "blood_sugar", "blood_pressure"}:
        return "blood"
    return "weight_loss"


def today_label() -> str:
    return datetime.now().strftime("%B %d, %Y").replace(" 0", " ")


def front_matter(row: dict[str, str], slug: str, status: str) -> str:
    title = normalize(row.get("title") or row.get("keyword"))
    return "\n".join([
        "---",
        f"title: \"{title}\"",
        f"slug: \"{slug}\"",
        f"category: \"{clean_category(row)}\"",
        f"primary_keyword: \"{normalize(row.get('keyword'))}\"",
        f"body_template: \"{normalize(row.get('body_template'))}\"",
        f"target_word_count: \"{normalize(row.get('target_word_count'))}\"",
        f"generation: \"ai\"",
        f"status: \"{status}\"",
        "---",
        "",
    ])


def blueprint_summary(row: dict[str, str]) -> str:
    h2s = [normalize(row.get(f"h2_{i}")) for i in range(1, 9) if normalize(row.get(f"h2_{i}"))]
    faq_keywords = split_pipe(row.get("faq_keywords"))
    h2_keywords = split_pipe(row.get("h2_keywords"))
    semantic_keywords = split_pipe(row.get("semantic_keywords"))
    duplicate_keywords = split_pipe(row.get("duplicate_keywords"))
    lines = [
        f"category: {clean_category(row)}",
        f"primary keyword: {normalize(row.get('keyword'))}",
        f"title: {normalize(row.get('title'))}",
        f"body_template: {normalize(row.get('body_template'))}",
        f"body_voice_mode: {normalize(row.get('body_voice_mode'))}",
        f"target_word_count: {normalize(row.get('target_word_count'))}",
        f"word_count_range: {normalize(row.get('word_count_range'))}",
        f"ctr_angle: {normalize(row.get('ctr_angle'))}",
        f"intro_hook: {normalize(row.get('intro_hook'))}",
        f"short_answer_angle: {normalize(row.get('short_answer_angle'))}",
        "H2 plan:",
    ]
    for h2 in h2s:
        lines.append(f"- {h2}")
    lines.extend([
        f"table_type: {normalize(row.get('table_type'))}",
        f"protocol_type: {normalize(row.get('protocol_type'))}",
        f"faq_keywords: {' | '.join(faq_keywords[:12])}",
        f"h2_keywords: {' | '.join(h2_keywords[:12])}",
        f"semantic_keywords: {' | '.join(semantic_keywords[:15])}",
        f"duplicate_keywords: {' | '.join(duplicate_keywords[:20])}",
        f"risk_level: {normalize(row.get('risk_level'))}",
        f"content_warnings: {normalize(row.get('content_warnings'))}",
    ])
    return "\n".join(lines)


def system_prompt(category: str) -> str:
    base = (
        "You are an expert SEO editorial writer. Write publishable Markdown articles that feel like human expert-led editorial content, not template filler. "
        "Every section must add new information. Do not repeat the same paragraph across sections. Do not reveal instructions. Do not say 'this section should'. "
        "Use short paragraphs, clear H2/H3 headings, practical specificity, comparison tables, FAQ, and a final takeaway. "
        "Do not invent studies, numbers, case series, patient stories, first-person testing, citations, or clinical claims unless they are explicitly provided. "
        "Never promise guaranteed outcomes, cures, detoxes, or instant results."
    )
    if category == "cbd":
        return base + " For CBD content, avoid cure/treat claims. Discuss product quality, dosage caution, interactions, THC/drug-testing risk, and clinician guidance where relevant."
    if category == "blood":
        return base + " For blood-health content, do not diagnose. Explain readings with clinical context, repeat measurements, symptoms, and when medical guidance is needed."
    return base + " For weight-loss content, be realistic about mechanisms, adherence, side effects, cost, maintenance, and clinician guidance for medications or supplements."


def user_prompt(row: dict[str, str]) -> str:
    category = clean_category(row)
    target = normalize(row.get("target_word_count") or "2400")
    title = normalize(row.get("title") or row.get("keyword"))
    category_rules = {
        "weight_loss": (
            "Write like the user's reference examples: strong opening, short version, practical breakdown, tradeoff section, comparison table, FAQ, protocol, and disclaimer. "
            "For medication topics, explain realistic first-month signals, side effects, dose/doctor context, access/cost, plateau or maintenance problems, and who should be careful."
        ),
        "cbd": (
            "Write like an evidence-led buyer/safety review. Explain what may be plausible, what remains uncertain, what to verify on labels, and how to avoid product hype. "
            "Include certificate of analysis, spectrum type, THC exposure, serving amount, side effects/interactions, and drug-testing concerns when relevant."
        ),
        "blood": (
            "Write like a careful health-number explainer. Explain what the reading or marker can mean, what changes interpretation, what patterns matter, and when to seek medical guidance. "
            "Avoid diagnosis and avoid telling the reader to self-treat abnormal results."
        ),
    }
    return f"""
Write a complete publish-ready Markdown article.

Required title/H1:
# {title}

Last updated line:
Last updated: {today_label()}

Target length: about {target} words. It is better to be specific and non-repetitive than padded.

Blueprint:
{blueprint_summary(row)}

Style requirements:
- Start with a search-intent hook, not a dictionary definition.
- Include a clear section called "The Short Version" within the first 300 words.
- Use the provided H2 plan, but make each section substantially different.
- Include one useful Markdown table tailored to the topic.
- Include a practical protocol/checklist section.
- Include FAQ using faq_keywords and natural questions, not awkward keyword rewrites.
- Include an "Important Note" disclaimer near the end.
- Use concrete topic-specific details. Avoid generic phrases that could fit any article.
- Do not mention that you are following a blueprint.
- Do not include code fences.

Category-specific requirements:
{category_rules.get(category, category_rules['weight_loss'])}
""".strip()


def call_chat_completion(
    api_key: str,
    api_base: str,
    model: str,
    row: dict[str, str],
    temperature: float,
    timeout: int,
) -> str:
    api_base = api_base.rstrip("/")
    url = f"{api_base}/chat/completions"
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt(clean_category(row))},
            {"role": "user", "content": user_prompt(row)},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"API HTTP {exc.code}: {body[:800]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"API request failed: {exc}") from exc

    parsed = json.loads(raw)
    try:
        return parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected API response: {raw[:800]}") from exc


def clean_markdown(markdown: str, row: dict[str, str]) -> str:
    text = str(markdown or "").strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    title = normalize(row.get("title") or row.get("keyword"))
    if not re.search(r"^#\s+", text, flags=re.M):
        text = f"# {title}\n\nLast updated: {today_label()}\n\n" + text
    elif "Last updated:" not in text[:500]:
        text = re.sub(r"(^#\s+.*?$)", r"\1\n\nLast updated: " + today_label(), text, count=1, flags=re.M)
    slug = slugify(row.get("keyword") or title)
    if not text.startswith("---"):
        text = front_matter(row, slug, "draft_ready") + text
    return text.strip() + "\n"


def quality_check(markdown: str, row: dict[str, str]) -> tuple[str, bool, list[str]]:
    notes: list[str] = []
    wc = word_count(markdown)
    try:
        target = int(float(row.get("target_word_count") or 2200))
    except ValueError:
        target = 2200
    h2_count = len(re.findall(r"^## ", markdown, flags=re.M))
    if wc < int(target * 0.65):
        notes.append(f"word_count_below_target:{wc}/{target}")
    if h2_count < 5:
        notes.append(f"too_few_h2:{h2_count}")
    for required in ["The Short Version", "Frequently Asked", "Important Note"]:
        if required not in markdown:
            notes.append(f"missing:{required}")
    if re.search(r"\b(guaranteed|miracle cure|cures?|detoxes?|burns fat instantly|clinically proven to cure)\b", markdown, flags=re.I):
        notes.append("unsafe_claim_language")
    if re.search(r"\b(this section should|open with|summarize what|blueprint|provided h2 plan)\b", markdown, flags=re.I):
        notes.append("instruction_leak")
    repeated_paras = repeated_paragraph_count(markdown)
    if repeated_paras:
        notes.append(f"repeated_paragraphs:{repeated_paras}")
    status = "PASS" if not notes else "REVIEW"
    return status, status == "PASS", notes


def repeated_paragraph_count(markdown: str) -> int:
    paras = [re.sub(r"\s+", " ", p.strip().lower()) for p in markdown.split("\n\n")]
    paras = [p for p in paras if len(p) > 120 and not p.startswith("|")]
    seen: set[str] = set()
    repeated = 0
    for para in paras:
        key = para[:240]
        if key in seen:
            repeated += 1
        else:
            seen.add(key)
    return repeated


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate AI Markdown articles from body_blueprint CSV.")
    parser.add_argument("input", help="Input body_blueprint_audit CSV")
    parser.add_argument("--articles-dir", default=DEFAULT_ARTICLES_DIR)
    parser.add_argument("--queue-output", default=DEFAULT_QUEUE_OUTPUT)
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""))
    parser.add_argument("--api-base", default=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--temperature", type=float, default=float(os.getenv("AI_TEMPERATURE", "0.65")))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("AI_TIMEOUT", "180")))
    parser.add_argument("--sleep", type=float, default=float(os.getenv("AI_SLEEP", "0.5")))
    parser.add_argument("--max-articles", type=int, default=int(os.getenv("AI_MAX_ARTICLES", "0")), help="0 means all")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key. Set OPENAI_API_KEY or pass --api-key.")

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    article_dir = Path(args.articles_dir)
    article_dir.mkdir(parents=True, exist_ok=True)
    source_rows = [row for row in read_csv(input_path) if row.get("publish_role", "primary_article") == "primary_article"]
    if args.max_articles and args.max_articles > 0:
        source_rows = source_rows[: args.max_articles]

    queue_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(source_rows, start=1):
        title = normalize(row.get("title") or row.get("keyword") or "Article")
        slug = slugify(row.get("keyword") or title)
        path = article_dir / f"{slug}.md"
        generation_status = "generated"
        error_message = ""

        if path.exists() and not args.overwrite:
            markdown = path.read_text(encoding="utf-8", errors="ignore")
            generation_status = "skipped_existing"
        else:
            try:
                print(f"[{idx}/{len(source_rows)}] Generating: {title}")
                raw = call_chat_completion(args.api_key, args.api_base, args.model, row, args.temperature, args.timeout)
                markdown = clean_markdown(raw, row)
                path.write_text(markdown, encoding="utf-8")
                time.sleep(args.sleep)
            except Exception as exc:  # noqa: BLE001 - batch should continue per row
                markdown = ""
                generation_status = "error"
                error_message = str(exc)[:1200]

        if markdown:
            quality_status, publish_ready, notes = quality_check(markdown, row)
            wc = word_count(markdown)
        else:
            quality_status, publish_ready, notes, wc = "ERROR", False, [error_message], 0

        queue_rows.append({
            "category": clean_category(row),
            "keyword": row.get("keyword", ""),
            "title": title,
            "slug": slug,
            "markdown_path": str(path),
            "word_count": wc,
            "target_word_count": row.get("target_word_count", ""),
            "body_template": row.get("body_template", ""),
            "generation_status": generation_status,
            "quality_status": quality_status,
            "publish_ready": "yes" if publish_ready else "review",
            "quality_notes": " | ".join(notes),
        })

    fields = ["category", "keyword", "title", "slug", "markdown_path", "word_count", "target_word_count", "body_template", "generation_status", "quality_status", "publish_ready", "quality_notes"]
    write_csv(Path(args.queue_output), queue_rows, fields)
    pass_count = sum(1 for row in queue_rows if row["quality_status"] == "PASS")
    errors = sum(1 for row in queue_rows if row["quality_status"] == "ERROR")
    print(f"Wrote {len(queue_rows)} queue rows to {args.queue_output}")
    print(f"Articles directory: {article_dir}")
    print(f"Quality: {pass_count} PASS · {len(queue_rows) - pass_count - errors} REVIEW · {errors} ERROR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
