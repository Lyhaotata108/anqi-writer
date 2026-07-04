#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Composable CTR title variant generator for Title Engine V3.4.

V3.4 adds non-colon headline shapes and fixes fragment joining so generated
headlines avoid awkward text like "and and" or repeated "before" phrases.
"""

from __future__ import annotations
import hashlib
import re

from ctr_fragment_bank import ANGLE_GRAMMAR


EXTRA_SHAPES_BY_ANGLE = {
    "timeline": ["subject_dash", "lead_in_subject_dash", "question_dash"],
    "before_buy": ["before_subject", "subject_dash", "lead_in_subject_dash"],
    "hidden_catch": ["before_subject", "subject_dash", "lead_in_subject_dash"],
    "reality_check_ctr": ["question_direct", "question_dash", "lead_in_subject_dash"],
    "looked_into": ["editorial_dash", "lead_in_subject_dash", "subject_dash"],
    "hidden_risk": ["subject_dash", "lead_in_subject_dash", "question_dash"],
    "money_access": ["subject_dash", "lead_in_subject_dash", "before_subject"],
    "comparison_decision": ["subject_dash", "lead_in_subject_dash", "question_dash"],
    "public_claim": ["subject_dash", "lead_in_subject_dash"],
    "before_next_dose": ["subject_dash", "before_subject", "lead_in_subject_dash"],
    "practical_filter": ["subject_dash", "before_subject", "lead_in_subject_dash"],
    "hidden_context": ["subject_dash", "lead_in_subject_dash", "question_dash"],
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def cap_first(text: str) -> str:
    text = normalize(text)
    return text[:1].upper() + text[1:] if text else text


def stable_index(seed: str, size: int) -> int:
    if size <= 0:
        return 0
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def rotate(items: list[str], seed: str) -> list[str]:
    if not items:
        return []
    start = stable_index(seed, len(items))
    return [items[(start + i) % len(items)] for i in range(len(items))]


def unique(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def strip_leading_and(text: str) -> str:
    return re.sub(r"^and\s+", "", normalize(text), flags=re.I)


def phrase_sentence(lead: str, contrast: str) -> str:
    lead = normalize(lead)
    contrast = normalize(contrast)
    c_low = contrast.lower()
    if c_low.startswith("and "):
        return f"{lead} {contrast}"
    if " before " in lead.lower() and c_low.startswith("before "):
        return f"{lead} — {cap_first(contrast)}"
    return f"{lead} {contrast}"


def phrase_and(lead: str, contrast: str) -> str:
    lead = normalize(lead)
    contrast = normalize(contrast)
    c_low = contrast.lower()
    if c_low.startswith("and "):
        return f"{lead} {contrast}"
    if c_low.startswith(("before ", "when ", "once ", "after ")):
        return f"{lead} {contrast}"
    return f"{lead} and {contrast}"


def phrase_dash(lead: str, contrast: str) -> str:
    lead = normalize(lead)
    contrast = cap_first(strip_leading_and(contrast))
    return f"{lead} — {contrast}"


def build_title(subject: str, question: str, lead: str, contrast: str, shape: str) -> str:
    subject = normalize(subject)
    question = normalize(question).rstrip("?")
    lead = normalize(lead)
    contrast = normalize(contrast)

    if shape == "question_colon":
        return f"{question}? {lead}: {cap_first(strip_leading_and(contrast))}"
    if shape == "question_dash":
        return f"{question}? {phrase_dash(lead, contrast)}"
    if shape == "question_direct":
        return f"{question}? {phrase_sentence(lead, contrast)}"
    if shape == "editorial_dash":
        return f"{lead} on {subject} — {cap_first(strip_leading_and(contrast))}"
    if shape == "subject_dash":
        return f"{subject} — {phrase_sentence(lead, contrast)}"
    if shape == "lead_in_subject_dash":
        return f"{lead} in {subject} — {cap_first(strip_leading_and(contrast))}"
    if shape == "before_subject":
        return f"Before You Try {subject}, {phrase_sentence(lead, contrast)}"
    if shape == "colon_before":
        return f"{subject}: {phrase_sentence(lead, contrast)}"
    if shape == "colon_and":
        return f"{subject}: {phrase_and(lead, contrast)}"
    return f"{subject}: {phrase_dash(lead, contrast)}"


def generate_fragment_variants(keyword: str, ctr_angle: str, ctx: dict, limit: int = 64) -> list[tuple[str, str, str]]:
    """Return (family, pattern_id, title) candidates built from fragments."""
    grammar = ANGLE_GRAMMAR.get(ctr_angle) or ANGLE_GRAMMAR.get("hidden_context")
    if not grammar:
        return []
    subject = str(ctx.get("kw") or ctx.get("subject") or keyword)
    question = str(ctx.get("question") or f"Does {subject} Actually Work")
    leads = rotate(list(grammar.get("lead", [])), keyword + ctr_angle + "lead")
    contrasts = rotate(list(grammar.get("contrast", [])), keyword + ctr_angle + "contrast")
    base_shapes = list(grammar.get("shape", []))
    extra_shapes = EXTRA_SHAPES_BY_ANGLE.get(ctr_angle, ["subject_dash", "lead_in_subject_dash"])
    shapes = rotate(unique(extra_shapes + base_shapes), keyword + ctr_angle + "shape")
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    family = f"frag_{ctr_angle}"
    for i, lead in enumerate(leads):
        for j, contrast in enumerate(contrasts):
            for shape in shapes:
                if len(out) >= limit:
                    return out
                title = build_title(subject, question, lead, contrast, shape)
                key = normalize(title).lower()
                if key in seen:
                    continue
                seen.add(key)
                pattern_id = f"frag_{ctr_angle}_{len(out) + 1:03d}_{i:02d}_{j:02d}_{shape}"
                out.append((family, pattern_id, title))
    return out
