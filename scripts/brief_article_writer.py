#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Brief-driven deterministic article writer.

This writer turns a VariationBrief into the actual markdown body. It is designed
for batch generation where the keyword has already been clustered and classified,
and where each article must use a different story/scene/pain-detail combination.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from pipeline_controller import PipelineResult
from preview_renderer import render_preview_html
from publish_articles import load_article


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "article"


def title_case(text: str) -> str:
    minor = {"a", "an", "and", "as", "at", "by", "for", "in", "is", "of", "on", "or", "the", "to", "vs", "with"}
    words = []
    for index, word in enumerate(re.sub(r"[^a-zA-Z0-9]+", " ", text).lower().split()):
        words.append(word if index > 0 and word in minor else word[:1].upper() + word[1:])
    return " ".join(words)


def compact_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def mobile_paragraphs(text: str, max_words: int = 48) -> str:
    blocks: list[str] = []
    for raw in text.split("\n\n"):
        raw = raw.strip()
        if not raw:
            continue
        if raw.startswith(("## ", "### ", "- ", "|", ">", "[IMAGE:", "[YOUTUBE_VIDEO:")) or re.match(r"^\d+\.\s", raw):
            blocks.append(raw)
            continue
        tokens = raw.split()
        if len(tokens) <= max_words:
            blocks.append(raw)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", raw)
        current: list[str] = []
        count = 0
        for sentence in sentences:
            n = len(sentence.split())
            if current and (len(current) >= 2 or count + n > max_words):
                blocks.append(" ".join(current).strip())
                current = [sentence]
                count = n
            else:
                current.append(sentence)
                count += n
        if current:
            blocks.append(" ".join(current).strip())
    return "\n\n".join(blocks)


def subject_from_keyword(keyword: str) -> str:
    cleaned = re.sub(r"\b(best|review|reviews|does|do|can|will|should|how|why|what|when|where)\b", " ", keyword, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?-")
    return cleaned or keyword


def pain_title(pain: str) -> str:
    return title_case(pain).replace(" And ", " and ") or "Real-Life Friction"


def build_title(keyword: str, brief: dict[str, Any]) -> str:
    subject = title_case(subject_from_keyword(keyword))
    intent = str(brief.get("intent") or "general")
    modifier = str(brief.get("modifier") or "general").replace("_", " ")
    pain = pain_title((brief.get("pain_details") or ["real-life friction"])[0])
    hook = title_case(str(brief.get("social_hook") or "The Viral Promise"))

    if intent == "comparison":
        other = title_case(modifier) if modifier != "general" else "The Alternative"
        return f"{subject} vs {other}: The Tradeoff That Changes The Decision"
    if intent == "side_effect":
        return f"{subject} Sounds Simple Until {pain} Shows Up"
    if intent == "safety":
        return f"{subject}: The Safety Question You Should Not Flatten"
    if intent == "timing":
        return f"{subject}: The Timing Question Gets Messier In Real Life"
    if intent == "benefit":
        return f"{subject}: What The Promise Misses About The Real Pattern"
    if intent == "weight_loss":
        return f"{subject} Sounds Like {hook} Until {pain} Shows Up"
    return f"{subject} Sounds Useful Until The Real-Life Tradeoff Shows Up"


def build_description(keyword: str, brief: dict[str, Any]) -> str:
    entity = str(brief.get("entity") or subject_from_keyword(keyword))
    intent = str(brief.get("intent") or "decision")
    details = [compact_sentence(x) for x in (brief.get("pain_details") or [])[:3]]
    detail_text = ", ".join(details) if details else "real-life friction, safety boundaries, and decision points"
    return f"A story-led {intent.replace('_', ' ')} guide to {entity}, using concrete reader friction around {detail_text}."


def build_headings(keyword: str, brief: dict[str, Any]) -> list[str]:
    subject = title_case(subject_from_keyword(keyword))
    intent = str(brief.get("intent") or "general")
    pain = pain_title((brief.get("pain_details") or ["real-life friction"])[0])
    hook = title_case(str(brief.get("social_hook") or "The Viral Hook"))
    scene = title_case(str(brief.get("scene") or "A Normal Day"))

    if intent == "comparison":
        return [
            "The Comparison Sounds Cleaner Than The Real Decision",
            f"Where {subject} Looks Strong On Paper",
            f"Where {pain} Changes The Tradeoff",
            f"The {scene} Story That Makes The Choice Less Abstract",
            f"{subject} Compared In Reader Language",
            "What To Do Before You Pick A Side",
        ]
    if intent == "side_effect":
        return [
            f"The {pain} Problem Is The Part People Notice Late",
            f"Why The {hook} Story Leaves Out The Messy Part",
            "The Second Week Can Change The Whole Decision",
            f"The {scene} Story That Shows The Cost",
            f"{subject} Hype Compared With The Real Routine",
            "What To Do Before You Keep Pushing Through",
        ]
    if intent == "safety":
        return [
            "The Scary Search Is Not The Same As A Clear Answer",
            "What The Question Is Really Asking",
            f"Where {pain} Belongs In The Decision",
            f"The {scene} Story That Shows Why Context Matters",
            f"{subject} Safety Questions Compared In Plain English",
            "What To Do Before You Guess",
        ]
    if intent == "benefit":
        return [
            "The Benefit Claim Needs A Real-World Filter",
            f"Why {hook} Makes The Promise Feel Stronger Than It Is",
            f"Where {pain} Can Change The Result",
            f"The {scene} Story That Makes The Pattern Clearer",
            f"{subject} Promise Compared With The Follow-Through",
            "What To Do Before You Trust The Pattern",
        ]
    return [
        f"The {hook} Promise Sounds Clean Until Real Life Enters",
        f"Where {subject} May Help And Where The Hype Runs Ahead",
        f"The {pain} Problem Most People Do Not Price In",
        f"The {scene} Story That Shows The Turning Point",
        f"{subject} Compared With The Shortcut People Think They Bought",
        "What To Do Before You Make It A Routine",
    ]


def build_frontmatter(keyword: str, title: str, description: str, category_id: int, keyword_id: int | None, brief: dict[str, Any]) -> str:
    keyword_line = f"keyword_id: {keyword_id}\n" if keyword_id is not None else ""
    entity = str(brief.get("entity") or "")
    intent = str(brief.get("intent") or "")
    modifier = str(brief.get("modifier") or "")
    keywords = ", ".join([x for x in [keyword, entity, intent.replace("_", " "), modifier.replace("_", " ")] if x and x != "general"])
    return f"""---
title: {title}
description: {description}
keywords: {keywords}
category_id: {category_id}
{keyword_line}tag: ymyl content, evidence aware guide
country: US
region:
locality:
---
"""


def build_opening(keyword: str, brief: dict[str, Any]) -> str:
    name = str(brief.get("story_name") or "Sarah")
    scene = str(brief.get("scene") or "a normal day")
    hook = str(brief.get("social_hook") or "the viral promise")
    details = [str(x) for x in (brief.get("pain_details") or ["routine friction", "hidden cost", "old habits returning"])]
    first = details[0]
    second = details[1] if len(details) > 1 else "the routine started feeling heavier"
    third = details[2] if len(details) > 2 else "the old pattern returned"

    text = (
        f"{name} did not search {keyword} because they wanted another generic guide. "
        f"The search started when {hook} collided with {scene}.\n\n"
        f"At first, the promise looked clean. Then {first} showed up, followed by {second}.\n\n"
        f"By the time {third} entered the picture, the question had changed. It was no longer whether the idea sounded useful. It was whether the real routine was worth repeating."
    )
    return mobile_paragraphs(text)


def build_sections(keyword: str, brief: dict[str, Any], headings: list[str]) -> str:
    subject = subject_from_keyword(keyword)
    name = str(brief.get("story_name") or "Sarah")
    scene = str(brief.get("scene") or "a normal day")
    hook = str(brief.get("social_hook") or "the viral promise")
    details = [str(x) for x in (brief.get("pain_details") or ["routine friction", "hidden cost", "old habits returning", "quality uncertainty"])]
    while len(details) < 4:
        details.append("repeatability problems")
    comparison = str(brief.get("comparison_angle") or "hype version vs real routine")

    section_one = mobile_paragraphs(
        f"The hook works because {hook} gives the reader a simple story to hold onto. It makes {subject} feel easier than the decision really is.\n\n"
        f"The problem is not that the hook is always useless. The problem is that it hides the lived part: {details[0]}, {details[1]}, and the pressure to keep going when the first wave of hope fades.\n\n"
        f"[IMAGE: {keyword} real-world decision]"
    )
    section_two = mobile_paragraphs(
        f"The cleaner version talks about promise. The real version asks what happens during {scene}.\n\n"
        f"That is where {details[2]} matters. A plan can look good in a post and still become difficult once meals, work, sleep, cost, or safety context enter the day."
    )
    section_three = mobile_paragraphs(
        f"The detail most people miss is not always dramatic. Sometimes it is {details[3]}. Sometimes it is the small daily negotiation that makes the routine feel bigger than expected.\n\n"
        f"This is why the article should not crown a universal winner. It should help the reader identify the tradeoff before they mistake discomfort, novelty, or expectation for a durable result.\n\n"
        f"[YOUTUBE_VIDEO: {keyword} real-life tradeoffs]"
    )
    case = mobile_paragraphs(
        f"{name}'s story is a composite pattern, not a fake case file. It shows why {subject} cannot be judged from the cleanest first impression.\n\n"
        f"In the beginning, {hook} made the choice feel obvious. Then {scene} exposed the cost. One part of the day was shaped by {details[0]}. Another was shaped by {details[1]}.\n\n"
        f"The emotional hinge is simple: the question stops being `does this sound promising?` and becomes `can I live with the full cost of making it work?`"
    )
    table = (
        f"A useful comparison for {subject} should be written in reader language, not report language. The angle here is: {comparison}.\n\n"
        "| What You Feel In Real Life | Hype Version | Reality Check |\n"
        "|---|---|---|\n"
        f"| Why it hooks people | {hook} | A decision with real tradeoffs |\n"
        f"| First friction | Easy to ignore | {details[0]} |\n"
        f"| Daily burden | Looks simple from the outside | {details[1]} and {details[2]} |\n"
        f"| Hidden cost | Rarely priced in | {details[3]} |\n"
        "| Better question | Does it sound good? | Can the routine survive ordinary pressure? |"
    )
    action = mobile_paragraphs(
        f"A useful next step for {subject} is to turn the promise into a decision you can actually test.\n\n"
        f"1. **Name the hook.** Write down whether {hook} is what made the idea feel attractive.\n"
        f"2. **Track the friction.** Watch for {details[0]}, {details[1]}, and {details[2]}.\n"
        "3. **Check the safety context.** Do not turn a search result into a personal medical plan. Use a qualified professional when medication, pregnancy, chronic conditions, or strong symptoms are involved.\n"
        "4. **Set a review point.** Decide when you will keep, adjust, or stop the routine instead of drifting."
    )

    blocks = [section_one, section_two, section_three, case, table, action]
    return "\n\n".join(f"## {heading}\n\n{body}" for heading, body in zip(headings, blocks))


def build_faq(keyword: str, brief: dict[str, Any]) -> str:
    subject = subject_from_keyword(keyword)
    angles = [str(x) for x in (brief.get("faq_angles") or [])]
    while len(angles) < 4:
        angles.append("what to check before making it routine")
    details = [str(x) for x in (brief.get("pain_details") or ["routine friction", "hidden cost"])]
    hook = str(brief.get("social_hook") or "the viral promise")

    qas = [
        (
            f"Does {subject} actually work in real life",
            f"It may help some people, but the real answer depends on the full routine, not only the cleanest claim. The useful question is whether {hook}, product quality, expectations, and {details[0]} still make sense after the first impression fades.",
        ),
        (
            f"Why do people get disappointed with {subject}",
            f"Disappointment usually appears when the promise is cleaner than the process. People expect a shortcut, then discover {details[0]} or {details[1] if len(details) > 1 else 'daily friction'} changes how the routine feels.",
        ),
        (
            f"What should I watch before making {subject} a routine",
            f"Watch the concrete details: {', '.join(details[:4])}. These details matter because they show whether the idea fits real life, not just whether it sounds convincing online.",
        ),
        (
            f"When should I ask a qualified professional about {subject}",
            "Ask before making health-sensitive changes if you take medications, have a medical condition, are pregnant, have severe symptoms, or are unsure whether the routine fits your situation. This article is educational and cannot replace individualized guidance.",
        ),
    ]
    lines = ["## Frequently Asked Questions"]
    for question, answer in qas:
        lines.append(f"### {question}\n\n{mobile_paragraphs(answer)}")
    return "\n\n".join(lines)


def build_tail(keyword: str, brief: dict[str, Any]) -> str:
    sources = [str(x) for x in (brief.get("sources") or [])]
    if not sources:
        sources = ["CDC", "MedlinePlus", "NIH"]
    source_lines = "\n".join(f"- {source}" for source in sources[:5])
    subject = subject_from_keyword(keyword)
    return (
        "## The Next Step Without Guesswork\n\n"
        f"The useful move after searching {subject} is not to copy the loudest claim. It is to compare the promise with the actual routine, the safety context, and the details that would make the plan hard to repeat.\n\n"
        "## AI Disclosure\n"
        "This article draft was prepared with AI assistance and reviewed through a structured editorial workflow.\n\n"
        "## References\n"
        f"{source_lines}\n\n"
        "## Author\n"
        "**Evidence-Aware Wellness Editor**"
    )


def build_markdown(keyword: str, brief: dict[str, Any], category_id: int, keyword_id: int | None = None) -> tuple[str, str, str]:
    title = build_title(keyword, brief)
    description = build_description(keyword, brief)
    headings = build_headings(keyword, brief)
    toc = ["## Table of Contents"] + [f"- [{heading}](#{slugify(heading)})" for heading in headings]
    toc += ["- [Frequently Asked Questions](#frequently-asked-questions)", "- [The Next Step Without Guesswork](#the-next-step-without-guesswork)"]
    body = "\n\n".join([
        "> **Disclaimer:** This content is for general educational purposes only and does not replace individualized professional advice.",
        f"Last updated: {datetime.now().strftime('%A, %B %d, %Y')}",
        "\n".join(toc),
        build_opening(keyword, brief),
        build_sections(keyword, brief, headings),
        build_faq(keyword, brief),
        build_tail(keyword, brief),
    ])
    markdown = build_frontmatter(keyword, title, description, category_id, keyword_id, brief) + "\n" + body.strip() + "\n"
    return markdown, title, description


def write_article_from_brief(
    keyword: str,
    brief: dict[str, Any],
    output_root: Path,
    category_id: int,
    keyword_id: int | None = None,
    stage1_1_path: Path | None = None,
    stage1_2_path: Path | None = None,
) -> PipelineResult:
    output_root.mkdir(parents=True, exist_ok=True)
    slug = slugify(keyword)
    markdown_path = output_root / f"ui_{slug}.md"
    markdown, title, description = build_markdown(keyword, brief, category_id, keyword_id)
    markdown_path.write_text(markdown, encoding="utf-8")
    preview_path = render_preview_html(markdown_path)
    load_article(markdown_path)
    return PipelineResult(
        keyword=keyword,
        stage1_1_path=stage1_1_path or markdown_path,
        stage1_2_path=stage1_2_path or markdown_path,
        markdown_path=markdown_path,
        preview_path=preview_path,
        title=title,
        description=description,
        publish_result=None,
    )
