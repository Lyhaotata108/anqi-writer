#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Composable CTR title variant generator for Title Engine V3.6.

V3.6 keeps non-colon variety but rejects overlong generated titles instead of
letting the title engine truncate them mid-phrase.
"""

from __future__ import annotations
import hashlib
import re

from ctr_fragment_bank import ANGLE_GRAMMAR

MAX_GENERATED_TITLE_LEN = 108

EXTRA_SHAPES_BY_ANGLE = {
    "timeline": ["subject_dash", "colon_dash"],
    "before_buy": ["subject_dash", "colon_dash", "before_subject"],
    "hidden_catch": ["subject_dash", "question_dash", "before_subject"],
    "reality_check_ctr": ["question_direct", "question_dash", "subject_dash"],
    "looked_into": ["editorial_dash", "subject_dash", "colon_dash"],
    "hidden_risk": ["subject_dash", "question_dash", "colon_dash"],
    "money_access": ["subject_dash", "colon_dash"],
    "comparison_decision": ["subject_dash", "question_dash", "colon_dash"],
    "public_claim": ["subject_dash", "question_dash", "colon_dash"],
    "before_next_dose": ["subject_dash", "colon_dash"],
    "practical_filter": ["subject_dash", "colon_dash", "before_subject"],
    "hidden_context": ["subject_dash", "question_dash", "colon_dash"],
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


def strip_leading_connector(text: str) -> str:
    text = normalize(text)
    text = re.sub(r"^(and|but)\s+", "", text, flags=re.I)
    return text


def demote_transition(text: str) -> str:
    text = strip_leading_connector(text)
    text = re.sub(r"^(before|when|once|after)\s+", "", text, flags=re.I)
    return normalize(text)


def phrase_sentence(lead: str, contrast: str) -> str:
    lead = normalize(lead)
    contrast = normalize(contrast)
    c_low = contrast.lower()
    if " before " in lead.lower() and c_low.startswith("before "):
        return f"{lead} — {cap_first(demote_transition(contrast))}"
    if c_low.startswith("and "):
        return f"{lead} {contrast}"
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
    contrast = cap_first(strip_leading_connector(contrast))
    return f"{lead} — {contrast}"


def safe_question(question: str, subject: str) -> str:
    question = normalize(question).rstrip("?")
    subject = normalize(subject)
    if len(question) > 72 or question.lower().count("for weight loss") > 1:
        return f"Does {subject} Actually Work"
    return question


def build_title(subject: str, question: str, lead: str, contrast: str, shape: str) -> str:
    subject = normalize(subject)
    question = safe_question(question, subject)
    lead = normalize(lead)
    contrast = normalize(contrast)

    if shape == "question_colon":
        return f"{question}? {lead}: {cap_first(strip_leading_connector(contrast))}"
    if shape == "question_dash":
        return f"{question}? {phrase_dash(lead, contrast)}"
    if shape == "question_direct":
        return f"{question}? {phrase_sentence(lead, contrast)}"
    if shape == "editorial_dash":
        return f"{lead} on {subject} — {cap_first(strip_leading_connector(contrast))}"
    if shape == "subject_dash":
        return f"{subject} — {phrase_sentence(lead, contrast)}"
    if shape == "before_subject":
        return f"Before You Try {subject}, {phrase_sentence(lead, contrast)}"
    if shape == "colon_before":
        return f"{subject}: {phrase_sentence(lead, contrast)}"
    if shape == "colon_and":
        return f"{subject}: {phrase_and(lead, contrast)}"
    return f"{subject}: {phrase_dash(lead, contrast)}"


def commercial_or_operational_subject(subject: str, keyword: str, angle: str) -> bool:
    s = normalize(subject).lower()
    k = normalize(keyword).lower()
    if angle in {"before_buy", "money_access", "before_next_dose"}:
        return True
    if s.startswith("best ") or k.startswith("best "):
        return True
    if any(token in s for token in ["dosage", "dose", "injection site", "over the counter", "non prescribed"]):
        return True
    if k.startswith("how to ask your doctor"):
        return True
    return False


def has_bad_transition(title: str) -> bool:
    t = normalize(title).lower()
    if t.count(" before ") >= 2:
        return True
    if t.count(" — ") >= 2:
        return True
    if re.search(r"before you try .+\bbefore\b", t):
        return True
    if re.search(r"\bthat\s+[—:]", t):
        return True
    if re.search(r"\b(before|when|once|after) the$", t):
        return True
    if re.search(r"\b(gets|looks|make the|does not)$", t):
        return True
    if re.search(r"\b(the|and|or|to|for|with|of|in)$", t):
        return True
    return False


def shape_allowed(shape: str, lead: str, contrast: str, angle: str, subject: str, keyword: str) -> bool:
    lead_l = lead.lower()
    contrast_l = contrast.lower()
    if shape.startswith("question") and commercial_or_operational_subject(subject, keyword, angle):
        return False
    if shape == "before_subject" and ("before" in lead_l or contrast_l.startswith("before ")):
        return False
    if shape == "question_direct" and contrast_l.startswith("before ") and "before" in lead_l:
        return False
    if shape == "editorial_dash" and not re.match(r"^(i looked|i checked|i compared)\b", lead_l):
        return False
    return True


def generated_title_ok(title: str) -> bool:
    title = normalize(title)
    if len(title) > MAX_GENERATED_TITLE_LEN:
        return False
    if len(title) < 48:
        return False
    if has_bad_transition(title):
        return False
    return True


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
    extra_shapes = EXTRA_SHAPES_BY_ANGLE.get(ctr_angle, ["subject_dash", "question_dash"])
    shapes = rotate(unique(extra_shapes + base_shapes), keyword + ctr_angle + "shape")
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    family = f"frag_{ctr_angle}"
    for i, lead in enumerate(leads):
        for j, contrast in enumerate(contrasts):
            for shape in shapes:
                if len(out) >= limit:
                    return out
                if not shape_allowed(shape, lead, contrast, ctr_angle, subject, keyword):
                    continue
                title = build_title(subject, question, lead, contrast, shape)
                if not generated_title_ok(title):
                    continue
                key = normalize(title).lower()
                if key in seen:
                    continue
                seen.add(key)
                pattern_id = f"frag_{ctr_angle}_{len(out) + 1:03d}_{i:02d}_{j:02d}_{shape}"
                out.append((family, pattern_id, title))
    return out
