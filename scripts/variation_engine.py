#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic variation engine for low-duplication article briefs.

Given the same keyword, the same variation is selected every time. Across a
large keyword batch, names, scenes, hooks, pain details, comparison angles, and
FAQ angles rotate to reduce visible template repetition.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
from typing import Iterable, TypeVar

from entity_pain_bank import get_entity_pack
from intent_classifier import classify_keyword

T = TypeVar("T")


@dataclass(frozen=True)
class VariationBrief:
    keyword: str
    entity: str
    lane: str
    intent: str
    modifier: str
    page_type: str
    story_name: str
    scene: str
    social_hook: str
    pain_details: list[str]
    faq_angles: list[str]
    comparison_angle: str
    safety_boundaries: list[str]
    sources: list[str]
    title_angle: str
    case_angle: str


def stable_int(seed: str) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def pick(items: list[T], seed: str, offset: int = 0) -> T:
    if not items:
        raise ValueError("Cannot pick from an empty list")
    index = (stable_int(seed) + offset) % len(items)
    return items[index]


def pick_many(items: list[T], seed: str, count: int, offset: int = 0) -> list[T]:
    if not items:
        return []
    count = min(count, len(items))
    start = (stable_int(seed) + offset) % len(items)
    rotated = items[start:] + items[:start]
    return rotated[:count]


def build_variation_brief(keyword: str) -> VariationBrief:
    classification = classify_keyword(keyword)
    pack = get_entity_pack(classification.entity)
    seed = f"{classification.cluster_key}::{keyword}"

    story_name = pick(pack.story_names, seed, 3)
    scene = pick(pack.scenes, seed, 11)
    social_hook = pick(pack.social_hooks, seed, 19)
    pain_details = pick_many(pack.pain_details, seed, 4, 29)
    faq_angles = pick_many(pack.faq_angles, seed, 4, 37)
    comparison_angle = pick(pack.comparison_angles, seed, 43)

    title_angle = make_title_angle(classification.intent, classification.modifier, social_hook, pain_details)
    case_angle = make_case_angle(story_name, scene, social_hook, pain_details)

    return VariationBrief(
        keyword=keyword,
        entity=classification.entity,
        lane=classification.lane,
        intent=classification.intent,
        modifier=classification.modifier,
        page_type=classification.page_type,
        story_name=story_name,
        scene=scene,
        social_hook=social_hook,
        pain_details=pain_details,
        faq_angles=faq_angles,
        comparison_angle=comparison_angle,
        safety_boundaries=pack.safety_boundaries,
        sources=pack.sources,
        title_angle=title_angle,
        case_angle=case_angle,
    )


def make_title_angle(intent: str, modifier: str, social_hook: str, pain_details: list[str]) -> str:
    first_pain = pain_details[0] if pain_details else "real-life friction"
    if intent == "comparison":
        return f"comparison decision: {social_hook} vs the real tradeoff"
    if intent == "side_effect":
        return f"pain-first: {modifier.replace('_', ' ')} through {first_pain}"
    if intent == "weight_loss":
        return f"promise gap: {social_hook} until {first_pain} shows up"
    if intent == "benefit":
        return f"expectation check: claimed benefit vs repeatable pattern"
    if intent == "timing":
        return f"routine question: timing promise vs daily friction"
    if intent == "safety":
        return f"safety decision: search anxiety vs practical next step"
    return f"real-world decision: {social_hook} vs {first_pain}"


def make_case_angle(story_name: str, scene: str, social_hook: str, pain_details: list[str]) -> str:
    detail = pain_details[0] if pain_details else "routine friction"
    return f"{story_name} enters through {social_hook}, then {detail} appears during {scene}"


def build_prompt_brief(keyword: str) -> str:
    brief = build_variation_brief(keyword)
    details = "\n".join(f"- {item}" for item in brief.pain_details)
    faqs = "\n".join(f"- {item}" for item in brief.faq_angles)
    safety = "\n".join(f"- {item}" for item in brief.safety_boundaries)
    sources = "\n".join(f"- {item}" for item in brief.sources)

    return f"""Keyword: {brief.keyword}
Entity: {brief.entity}
Lane: {brief.lane}
Intent: {brief.intent}
Modifier: {brief.modifier}
Page Type: {brief.page_type}

PAS Story Inputs:
- Story Name: {brief.story_name}
- Scene: {brief.scene}
- Social Hook: {brief.social_hook}
- Title Angle: {brief.title_angle}
- Case Angle: {brief.case_angle}
- Comparison Angle: {brief.comparison_angle}

Must-use felt details:
{details}

FAQ angles:
{faqs}

Safety boundaries:
{safety}

Preferred source profile:
{sources}

Formatting rules:
- Do not reveal the final verdict in the introduction.
- Do not use anonymous placeholders such as someone, early signal, or ordinary life returns.
- Use named-story PAS: pain, agitation, decision path.
- Keep paragraphs mobile-friendly: no paragraph over 50 words.
- Use reader-language comparison tables, not report-language tables.
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic variation briefs from keywords.")
    parser.add_argument("keyword", nargs="+", help="Keyword text. Multiple args are joined with spaces.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of prompt brief.")
    args = parser.parse_args()

    keyword = " ".join(args.keyword)
    if args.json:
        print(json.dumps(asdict(build_variation_brief(keyword)), ensure_ascii=False, indent=2))
    else:
        print(build_prompt_brief(keyword))


if __name__ == "__main__":
    main()
