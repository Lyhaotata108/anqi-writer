#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Score and de-duplicate SEO title candidates.

V3.7 adds batch-level title shape balancing so the generator does not overuse
one punctuation style, especially dash-led headlines.
"""

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


def title_frame_key(title: str) -> str:
    raw = str(title or "").strip()
    if "?" in raw:
        frame = raw.split("?", 1)[1]
    elif ":" in raw:
        frame = raw.split(":", 1)[1]
    elif "—" in raw:
        frame = raw.split("—", 1)[1]
    else:
        frame = raw
    frame = frame.replace("’", "'").replace("‘", "'")
    frame = re.sub(r"\b20\d{2}\b", "year", frame.lower())
    frame = re.sub(r"[^a-z0-9]+", "-", frame).strip("-")
    return frame or "whole-title"


def title_shape_key(title: str) -> str:
    raw = str(title or "").strip().lower()
    if re.match(r"^(i looked|i checked|i compared)\b", raw):
        return "editorial"
    if raw.startswith("before you "):
        return "before"
    if "?" in raw:
        return "question"
    if "—" in raw:
        return "dash"
    if ":" in raw:
        return "colon"
    return "natural"


def title_shape_counts(existing_titles: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for title in existing_titles:
        shape = title_shape_key(title)
        counts[shape] = counts.get(shape, 0) + 1
    return counts


def shape_balance_adjustment(title: str, existing_titles: list[str]) -> tuple[int, list[str]]:
    if len(existing_titles) < 20:
        return 0, []
    shape = title_shape_key(title)
    counts = title_shape_counts(existing_titles)
    total = max(1, len(existing_titles))
    current_ratio = counts.get(shape, 0) / total
    caps = {
        "dash": 0.62,
        "colon": 0.24,
        "question": 0.30,
        "before": 0.12,
        "editorial": 0.14,
        "natural": 0.10,
    }
    penalty = 0
    reasons: list[str] = []
    cap = caps.get(shape, 0.25)
    if current_ratio > cap:
        penalty = min(36, int((current_ratio - cap) * 100) + 8)
        reasons.append(f"shape-overuse-penalty:{shape}:{current_ratio:.2f}")

    bonus = 0
    if shape in {"question", "colon", "before", "editorial", "natural"} and current_ratio < 0.10:
        bonus = 10
        reasons.append(f"underused-shape-bonus:{shape}")
    if shape == "dash" and current_ratio < 0.45:
        bonus = max(bonus, 4)
        reasons.append("dash-still-usable")
    return bonus - penalty, reasons


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


def frame_repeat_count(title: str, existing_titles: Iterable[str]) -> int:
    frame = title_frame_key(title)
    return sum(1 for old in existing_titles if title_frame_key(old) == frame)


def score_title(title: str, keyword: str, family: str, pattern_id: str, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> TitleCandidate:
    existing_titles = existing_titles or []
    existing_patterns = existing_patterns or set()
    title_l = normalize(title)
    kw_l = normalize(keyword)
    score = 0
    reasons: list[str] = []

    if title_l.startswith(kw_l[: min(22, len(kw_l))]) or (kw_l.split() and kw_l.split()[0] in title_l[:35]):
        score += 20
        reasons.append("keyword/front-loaded")
    if 48 <= len(title) <= 112:
        score += 12
        reasons.append("good-length")
    if any(token in title_l for token in HOOK_TOKENS):
        score += 18
        reasons.append("hook-token")
    if ":" in title or "?" in title or "—" in title:
        score += 8
        reasons.append("clickable-structure")

    if pattern_id not in existing_patterns:
        score += 16
        reasons.append("fresh-pattern")
    else:
        score -= 34
        reasons.append("used-pattern-penalty")

    repeated_frame_count = frame_repeat_count(title, existing_titles)
    if repeated_frame_count:
        penalty = min(54, repeated_frame_count * 9)
        score -= penalty
        reasons.append(f"repeated-frame-penalty:{repeated_frame_count}")

    shape_adjustment, shape_reasons = shape_balance_adjustment(title, existing_titles)
    if shape_adjustment:
        score += shape_adjustment
    reasons.extend(shape_reasons)

    for phrase in BANNED_TITLE_PHRASES:
        if phrase in title_l:
            score -= 60
            reasons.append(f"banned:{phrase}")

    similarity = max_title_similarity(title, existing_titles)
    if similarity > 0.55:
        score -= 60
        reasons.append(f"too-similar:{similarity:.2f}")
    elif similarity > 0.35:
        score -= 25
        reasons.append(f"similar:{similarity:.2f}")
    else:
        score += 10
        reasons.append("batch-distinct")

    return TitleCandidate(title=title, family=family, pattern_id=pattern_id, score=score, reasons=reasons)


def select_best(candidates: list[TitleCandidate]) -> TitleCandidate:
    if not candidates:
        raise ValueError("No title candidates supplied")
    return sorted(candidates, key=lambda item: item.score, reverse=True)[0]
