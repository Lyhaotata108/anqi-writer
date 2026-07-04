#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entity pain bank for article brief generation.

The bank provides reusable but variable building blocks. It does not claim that
all details apply to every reader. Writers should phrase these as reader-reported
friction, possible tradeoffs, or decision points.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


DEFAULT_PACK: dict[str, Any] = {
    "story_names": ["Sarah", "Marcus", "Rachel", "Daniel", "Lena", "Mike", "Emma", "Chris"],
    "scenes": [
        "client meeting",
        "morning commute",
        "office lunch",
        "dinner date",
        "long drive",
        "school pickup",
        "gym day",
        "late-night snack moment",
    ],
    "social_hooks": [
        "viral shortcut",
        "low-cost fix",
        "natural alternative",
        "before-and-after promise",
    ],
    "pain_details": [
        "routine friction",
        "unclear expectations",
        "extra product costs",
        "old habits returning",
        "timing pressure",
        "quality uncertainty",
    ],
    "faq_angles": [
        "does it actually work",
        "why results slow down",
        "what side effects matter",
        "when to ask a professional",
    ],
    "comparison_angles": [
        "hype version vs real routine",
        "first-week excitement vs maintenance",
        "cheap first step vs hidden cost",
    ],
    "safety_boundaries": [
        "Do not present a supplement or medication as a guaranteed cure.",
        "Do not give individualized dosing instructions.",
        "Use clinician/professional discussion language for medical decisions.",
    ],
    "sources": [
        "NIH Office of Dietary Supplements",
        "NCCIH",
        "FDA",
        "CDC",
        "MedlinePlus",
    ],
}

ENTITY_PACKS: dict[str, dict[str, Any]] = {
    "berberine": {
        "story_names": ["Sarah", "Rachel", "Lena", "Maya", "Daniel", "Chris", "Nina", "Alex"],
        "scenes": [
            "client meeting",
            "office lunch",
            "morning commute",
            "dinner date",
            "long drive",
            "gym day",
            "weekend brunch",
            "busy workday",
        ],
        "social_hooks": [
            "Nature's Ozempic",
            "cheap yellow capsule",
            "natural weight-loss shortcut",
            "low-cost appetite-control promise",
            "viral supplement shortcut",
        ],
        "pain_details": [
            "bitter yellow powder",
            "yellow capsule stains",
            "bathroom-exit planning",
            "meeting-day stress",
            "food-noise rebound",
            "sweet-drink cravings returning",
            "extra probiotics or stomach-support products",
            "abandoned bottles",
            "product-quality uncertainty",
        ],
        "faq_angles": [
            "is it really Nature's Ozempic",
            "why the stomach feels unpredictable",
            "why food noise can come back",
            "whether the cheap bottle is still worth it",
            "what to check before making it daily",
        ],
        "comparison_angles": [
            "social-media promise vs daily routine",
            "cheap capsule vs hidden add-on cost",
            "first-week appetite drop vs long-term repeatability",
        ],
        "safety_boundaries": [
            "Do not say berberine is equivalent to a prescription GLP-1 medication.",
            "Do not claim it guarantees weight loss or blood-sugar changes.",
            "Mention supplement quality, medication interactions, and professional discussion for safety-sensitive readers.",
        ],
        "sources": ["NIH Office of Dietary Supplements", "NCCIH", "FDA Dietary Supplements"],
    },
    "metformin": {
        "story_names": ["Marcus", "Rachel", "Daniel", "Lena", "Chris", "Maya"],
        "scenes": ["client meeting", "morning commute", "office lunch", "travel day", "pharmacy pickup", "follow-up appointment"],
        "social_hooks": ["old medication with new weight-loss attention", "low-cost prescription option", "slow-and-steady promise"],
        "pain_details": ["stomach timing", "workday bathroom planning", "afternoon fatigue", "slow scale feedback", "follow-up labs", "expectation mismatch"],
        "faq_angles": ["does it help if you are not diabetic", "why progress feels slow", "what to ask a clinician", "how it compares with GLP-1 options"],
        "comparison_angles": ["slow routine vs dramatic expectation", "affordability vs tolerability", "prescription fit vs internet hype"],
        "safety_boundaries": ["Do not provide dosing instructions.", "Do not tell readers to start or stop medication.", "Frame decisions as clinician discussions."],
        "sources": ["MedlinePlus", "NIDDK", "FDA label or drug information"],
    },
    "cbd": {
        "story_names": ["Emma", "Noah", "Lena", "Chris", "Maya", "Rachel"],
        "scenes": ["restless night", "morning meeting", "long drive", "work deadline", "travel night", "weekend recovery"],
        "social_hooks": ["calm-in-a-gummy promise", "better sleep promise", "natural relaxation story", "stress relief shortcut"],
        "pain_details": ["next-morning fog", "inconsistent product feel", "label confusion", "dose uncertainty", "interaction questions", "price creep"],
        "faq_angles": ["does it work or is it hype", "can it cause morning grogginess", "how to judge product quality", "whether nightly use makes sense"],
        "comparison_angles": ["night-one calm vs morning-after cost", "product label vs actual experience", "gummy convenience vs consistency"],
        "safety_boundaries": ["Do not claim CBD treats disease.", "Mention product quality and interaction questions.", "Use caution language for medications and health conditions."],
        "sources": ["FDA CBD", "NCCIH Cannabis and Cannabinoids", "MedlinePlus"],
    },
    "blood sugar": {
        "story_names": ["Daniel", "Rachel", "Marcus", "Lena", "Chris", "Maya"],
        "scenes": ["after lunch", "morning reading", "late-night snack", "work stress day", "short-sleep morning", "post-workout check"],
        "social_hooks": ["one scary number", "after-meal spike worry", "fasting reading anxiety", "A1C confusion"],
        "pain_details": ["not knowing whether one number matters", "meal timing uncertainty", "stress and sleep confusion", "repeat-reading anxiety", "what to bring to a clinician"],
        "faq_angles": ["when to worry", "what to track", "whether food or stress affects it", "when to seek professional advice"],
        "comparison_angles": ["single reading vs pattern", "panic search vs useful record", "symptom memory vs tracked context"],
        "safety_boundaries": ["Do not diagnose from a single number.", "Mention urgent care for severe or sudden symptoms.", "Encourage professional review for repeated or worsening patterns."],
        "sources": ["CDC Diabetes", "NIDDK", "MedlinePlus Blood Glucose"],
    },
    "cholesterol": {
        "story_names": ["Daniel", "Maya", "Chris", "Rachel", "Lena", "Marcus"],
        "scenes": ["annual lab result", "doctor portal notification", "family-history conversation", "diet reset attempt", "follow-up appointment"],
        "social_hooks": ["silent number worry", "LDL panic", "lab report confusion", "heart-health wake-up call"],
        "pain_details": ["confusing lab ranges", "silent risk anxiety", "diet overcorrection", "family history worry", "statin questions", "repeat-test uncertainty"],
        "faq_angles": ["what the number means", "what to ask next", "whether lifestyle changes are enough", "when medication comes up"],
        "comparison_angles": ["one lab result vs risk pattern", "diet change vs medical plan", "internet fear vs clinician context"],
        "safety_boundaries": ["Do not diagnose cardiovascular risk from one keyword.", "Avoid telling readers to start or stop medication.", "Frame next steps as clinician discussion and tracking."],
        "sources": ["NHLBI", "CDC", "MedlinePlus Cholesterol"],
    },
}


@dataclass(frozen=True)
class EntityPainPack:
    entity: str
    story_names: list[str]
    scenes: list[str]
    social_hooks: list[str]
    pain_details: list[str]
    faq_angles: list[str]
    comparison_angles: list[str]
    safety_boundaries: list[str]
    sources: list[str]


def get_entity_pack(entity: str) -> EntityPainPack:
    base = deepcopy(DEFAULT_PACK)
    override = ENTITY_PACKS.get(entity, {})
    for key, value in override.items():
        base[key] = value
    return EntityPainPack(entity=entity, **base)


def list_supported_entities() -> list[str]:
    return sorted(ENTITY_PACKS)


if __name__ == "__main__":
    import json
    import sys

    entity = sys.argv[1] if len(sys.argv) > 1 else "berberine"
    pack = get_entity_pack(entity)
    print(json.dumps(pack.__dict__, ensure_ascii=False, indent=2))
