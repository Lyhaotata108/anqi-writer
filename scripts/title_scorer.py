#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Score and de-duplicate SEO title candidates."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from title_pattern_bank import BANNED_TITLE_PHRASES, HOOK_TOKENS


@dataclass(frozen=True)
class TitleCandidate:
    title: str
    family: str
    pattern_id: str
    score: int
    reasons: list[str]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def word_ngrams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", normalize(text))
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def max_title_similarity(title: str, existing_titles: Iterable[str]) -> float:
    grams = word_ngrams(title)
    return max((jaccard(grams, word_ngrams(other)) for other in existing_titles), default=0.0)


def score_title(title: str, keyword: str, family: str, pattern_id: str, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> TitleCandidate:
    existing_titles = existing_titles or []
    existing_patterns = existing_patterns or set()
    title_l = normalize(title)
    kw_l = normalize(keyword)
    score = 0
    reasons: list[str] = []

    if title_l.startswith(kw_l[: min(22, len(kw_l))]) or kw_l.split()[0] in title_l[:35]:
        score += 20
        reasons.append("keyword/front-loaded")
    if 48 <= len(title) <= 108:
        score += 12
        reasons.append("good-length")
    if any(token in title_l for token in HOOK_TOKENS):
        score += 18
        reasons.append("hook-token")
    if ":" in title or "?" in title or "—" in title:
        score += 8
        reasons.append("clickable-structure")
    if pattern_id not in existing_patterns:
        score += 12
        reasons.append("fresh-pattern")

    for phrase in BANNED_TITLE_PHRASES:
        if phrase in title_l:
            score -= 60
            reasons.append(f"banned:{phrase}")

    similarity = max_title_similarity(title, existing_titles)
    if similarity > 0.55:
        score -= 50
        reasons.append(f"too-similar:{similarity:.2f}")
    elif similarity > 0.35:
        score -= 20
        reasons.append(f"similar:{similarity:.2f}")
    else:
        score += 8
        reasons.append("batch-distinct")

    return TitleCandidate(title=title, family=family, pattern_id=pattern_id, score=score, reasons=reasons)


def select_best(candidates: list[TitleCandidate]) -> TitleCandidate:
    if not candidates:
        raise ValueError("No title candidates supplied")
    return sorted(candidates, key=lambda item: item.score, reverse=True)[0]
