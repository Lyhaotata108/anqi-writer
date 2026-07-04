#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI sample-style article writer for AnQiCMS markdown output.

This writer replaces deterministic paragraph assembly for the main batch flow.
It asks the configured Gemini-compatible endpoint to produce a complete importable
Markdown article with AnQiCMS frontmatter, then validates and saves it.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import argparse
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
]


STYLE_GUIDE = """
Gold sample target:
- Write like a health SEO editor creating a high-information feature, not a template page.
- Use the feel of these sample forms: tracking-style evidence review and professional process explainer.
- Strong opening: search confusion, why current SERP advice is messy, what this article will clarify.
- Include mechanism, evidence, practical tradeoffs, concrete examples, comparison tables, FAQ, and a next-step protocol.
- Use data-like structure only when framed safely. Do not invent a real internal trial, patient roster, clinic, or measured outcome.
- Allowed phrasing: published evidence suggests, practical tracking framework, illustrative comparison, composite coaching scenario.
- Not allowed: we tracked 11 people, our clinical study found, in my practice, my client, medically cleared participants, unless the user provided that real dataset.
""".strip()


ARTICLE_TYPE_GUIDES = {
    "top_10_listicle": """
Build a real listicle/review article. The user expects ranked options, evaluation criteria, and buying/avoidance guidance.
Required sections: Quick Verdict; How We Evaluated These Options; The 10 Options People Usually Compare; comparison table; What Actually Helps; Red Flags; Who Should Be Careful; FAQ; Next Steps Without the Guesswork.
The article must actually list options or types. Do not write a generic promise/tradeoff essay.
""".strip(),
    "evidence_review": """
Build an evidence-review article with the energy of a tracked experiment, but without inventing private data.
Use an illustrative 30/60/90-day tracking framework, published-evidence interpretation, a measurable-outcomes table, what worked, what under-delivered, FAQ, and a practical daily protocol.
""".strip(),
    "process_explainer": """
Build a professional process explainer. Use step-by-step structure, real-world decision flow, a comparison table, composite examples, FAQ, and a next action section.
It should feel like a knowledgeable editor walking the reader through what actually happens.
""".strip(),
    "comparison_decision": """
Build a decision comparison. Include a quick verdict, side-by-side table, where each option fits, where each disappoints, who should choose which, FAQ, and next steps.
""".strip(),
    "side_effect_safety": """
Build a YMYL-safe safety/side-effect decision guide. Include common effects, warning signs, who should be careful, interaction questions, what to ask a qualified professional, FAQ, and next steps.
Do not diagnose or prescribe.
""".strip(),
    "generic_editorial": """
Build a high-information editorial guide. It still needs a strong opening, specific examples, a comparison table, FAQ, and next steps. Avoid generic filler.
""".strip(),
}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "article"


def strip_code_fences(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def ensure_frontmatter(markdown: str, keyword: str, category_id: int, article_type: str) -> str:
    markdown = strip_code_fences(markdown)
    if markdown.startswith("---"):
        return markdown.strip() + "\n"
    title = keyword.title()
    description = f"A sample-style editorial guide to {keyword}, including evidence, tradeoffs, FAQ, and next steps."
    return f"""---
title: {title}
description: {description[:155]}
keywords: {keyword}, {article_type.replace('_', ' ')}, evidence aware guide
category_id: {category_id}
tag: ymyl content, evidence aware guide
country: US
region:
locality:
---

{markdown.strip()}
"""


def normalize_markdown(markdown: str, keyword: str, category_id: int, article_type: str) -> str:
    markdown = ensure_frontmatter(markdown, keyword, category_id, article_type)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = re.sub(r"(?im)^last updated:\s*.*$", f"Last updated: {datetime.now().strftime('%A, %B %d, %Y')}", markdown)
    if "Last updated:" not in markdown.split("---", 2)[-1][:500]:
        markdown = markdown.replace("---\n\n", f"---\n\nLast updated: {datetime.now().strftime('%A, %B %d, %Y')}\n\n", 1)
    if "[YOUTUBE_VIDEO:" not in markdown and "<iframe" not in markdown:
        markdown = markdown.rstrip() + f"\n\n[YOUTUBE_VIDEO: {keyword} evidence explained]\n"
    if "[IMAGE:" not in markdown and "<img" not in markdown:
        body_start = markdown.find("\n\n")
        if body_start != -1:
            markdown = markdown[:body_start + 2] + f"\n[IMAGE: {keyword} evidence based weight loss guide]\n" + markdown[body_start + 2:]
    return markdown.strip() + "\n"


def build_writer_prompt(keyword: str, category_id: int, article_type: str, route: dict[str, Any], classification: dict[str, Any], secondary_keywords: list[str] | None = None) -> str:
    secondary_keywords = secondary_keywords or []
    type_guide = ARTICLE_TYPE_GUIDES.get(article_type, ARTICLE_TYPE_GUIDES["generic_editorial"])
    required_structure = "\n".join(f"- {item}" for item in route.get("required_structure", []))
    secondary_text = "\n".join(f"- {item}" for item in secondary_keywords[:20]) or "- none provided"
    forbidden = "\n".join(f"- {phrase}" for phrase in FORBIDDEN_STYLE_PHRASES)
    return f"""You are a senior YMYL-aware health SEO editor.

Task: Generate ONE complete, import-ready AnQiCMS Markdown article.
Return plain Markdown only. Do not wrap it in a code fence. Do not add explanations outside the article.

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
{type_guide}

Required structure signals:
{required_structure}

Hard output requirements:
- Start with AnQiCMS frontmatter exactly like this pattern: title, description, keywords, category_id, tag, country, region, locality.
- category_id must be {category_id}.
- Include Last updated line after frontmatter.
- Include a disclaimer near the top.
- Include a strong search-intent opening. The first 180 words must show why the searcher is confused and what the article will clarify.
- Include at least 6 meaningful H2 sections.
- Include at least one markdown comparison/data table.
- Include at least four FAQ questions using ### headings.
- Include one actionable protocol or next-step plan.
- Include exactly one [IMAGE: ...] placeholder and exactly one [YOUTUBE_VIDEO: ...] placeholder.
- Include AI Disclosure, References, and Author sections.
- References should be credible public-source profiles such as NIH, CDC, MedlinePlus, FDA, NCCIH, Johns Hopkins, Mayo Clinic, Cleveland Clinic, or Academy of Nutrition and Dietetics where relevant.
- Do not invent real internal experiments, clinical participants, named patients, private client results, measured lab data, or unpublished case series.
- You may use composite examples if clearly framed as composite.
- You may use published-evidence language without fabricating paper titles, DOIs, or exact trial numbers unless you are certain.
- Keep paragraphs mobile-friendly: usually 2-4 sentences.

Forbidden phrases and structures:
{forbidden}

Write the article now."""


def local_quality_gate(markdown: str) -> tuple[bool, list[str]]:
    lower = markdown.lower()
    issues: list[str] = []
    for phrase in FORBIDDEN_STYLE_PHRASES:
        if phrase in lower:
            issues.append(f"forbidden phrase: {phrase}")
    if not markdown.startswith("---"):
        issues.append("missing frontmatter")
    if markdown.count("## ") < 6:
        issues.append("fewer than 6 H2 sections")
    if markdown.count("### ") < 4:
        issues.append("fewer than 4 FAQ-style H3 questions")
    if "|" not in markdown:
        issues.append("missing markdown table")
    if "[YOUTUBE_VIDEO:" not in markdown and "<iframe" not in markdown:
        issues.append("missing YouTube placeholder")
    return not issues, issues


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
    prompt = build_writer_prompt(clean_keyword_value, category_id, article_type, route, classification, secondary_keywords)
    if progress:
        progress("Writing", 30, f"Generating sample-style article: {clean_keyword_value}")
    text = controller._call_gemini_with_retry(prompt, attempts=2)
    if not text:
        raise RuntimeError("Sample-style Gemini writer failed; check GEMINI_API_KEY and GEMINI_BASE_URL in local_api_keys.json")

    markdown = normalize_markdown(text, clean_keyword_value, category_id, article_type)
    ok, issues = local_quality_gate(markdown)
    if not ok:
        repair_prompt = build_repair_prompt(markdown, issues, clean_keyword_value, category_id, article_type)
        if progress:
            progress("Repairing", 52, "Primary draft missed sample-style guard; repairing once")
        repaired = controller._call_gemini_with_retry(repair_prompt, attempts=1)
        if repaired:
            markdown = normalize_markdown(repaired, clean_keyword_value, category_id, article_type)

    output_root.mkdir(parents=True, exist_ok=True)
    slug = slugify(clean_keyword_value)
    markdown_path = output_root / f"ui_{slug}.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    preview_path = render_preview_html(markdown_path)
    article = load_article(markdown_path)
    if progress:
        progress("Ready_to_Publish", 90, f"Sample-style article ready: {markdown_path.name}")
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


def build_repair_prompt(markdown: str, issues: list[str], keyword: str, category_id: int, article_type: str) -> str:
    issue_text = "\n".join(f"- {issue}" for issue in issues)
    forbidden = "\n".join(f"- {phrase}" for phrase in FORBIDDEN_STYLE_PHRASES)
    return f"""Repair this AnQiCMS Markdown article so it matches the gold sample style.
Return the full corrected Markdown only. No code fences. Keep category_id {category_id}.

Keyword: {keyword}
Article type: {article_type}
Failed checks:
{issue_text}

Forbidden phrases:
{forbidden}

Requirements:
- Keep valid frontmatter.
- Add or repair a search-confusion opening.
- Include at least 6 H2 sections.
- Include at least one table.
- Include at least 4 FAQ H3 questions.
- Include one action protocol / Next Steps section.
- Include exactly one [IMAGE: ...] and one [YOUTUBE_VIDEO: ...].
- Do not fabricate private experiments, real clients, or clinical measurements.

Original Markdown:
{markdown}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate one sample-style AnQiCMS article.")
    parser.add_argument("keyword", nargs="+")
    parser.add_argument("--category", type=int, default=1)
    parser.add_argument("--workspace", default="/Users/hjg/Documents/anqicms-writer")
    args = parser.parse_args()
    root = Path(args.workspace)
    result = generate_sample_style_article(" ".join(args.keyword), root, root, args.category)
    print(result.markdown_path)


if __name__ == "__main__":
    main()
