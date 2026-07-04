#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Composable CTR title variant generator for Title Engine V3.3."""

from __future__ import annotations
import hashlib
import re
from typing import Iterable

from ctr_fragment_bank import ANGLE_GRAMMAR


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


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


def build_title(subject: str, question: str, lead: str, contrast: str, shape: str) -> str:
    subject = normalize(subject)
    question = normalize(question).rstrip("?")
    lead = normalize(lead)
    contrast = normalize(contrast)
    if shape == "question_colon":
        return f"{question}? {lead}: {contrast}"
    if shape == "question_dash":
        return f"{question}? {lead} — {contrast}"
    if shape == "question_direct":
        return f"{question}? {lead}"
    if shape == "editorial_dash":
        return f"{lead} on {subject} — {contrast}"
    if shape == "colon_before":
        return f"{subject}: {lead} {contrast}"
    if shape == "colon_and":
        return f"{subject}: {lead} and {contrast}"
    return f"{subject}: {lead} — {contrast}"


def generate_fragment_variants(keyword: str, ctr_angle: str, ctx: dict, limit: int = 48) -> list[tuple[str, str, str]]:
    """Return (family, pattern_id, title) candidates built from fragments."""
    grammar = ANGLE_GRAMMAR.get(ctr_angle) or ANGLE_GRAMMAR.get("hidden_context")
    if not grammar:
        return []
    subject = str(ctx.get("kw") or ctx.get("subject") or keyword)
    question = str(ctx.get("question") or f"Does {subject} Actually Work")
    leads = rotate(list(grammar.get("lead", [])), keyword + ctr_angle + "lead")
    contrasts = rotate(list(grammar.get("contrast", [])), keyword + ctr_angle + "contrast")
    shapes = rotate(list(grammar.get("shape", [])), keyword + ctr_angle + "shape")
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    family = f"frag_{ctr_angle}"
    for shape in shapes:
        for i, lead in enumerate(leads):
            for j, contrast in enumerate(contrasts):
                if len(out) >= limit:
                    return out
                title = build_title(subject, question, lead, contrast, shape)
                key = normalize(title).lower()
                if key in seen:
                    continue
                seen.add(key)
                pattern_id = f"frag_{ctr_angle}_{len(out) + 1:03d}_{i:02d}_{j:02d}"
                out.append((family, pattern_id, title))
    return out
