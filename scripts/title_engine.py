#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Intent-family SEO title engine with V2.1 family-bias scoring."""

from __future__ import annotations
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import argparse
import hashlib
import re
from typing import Any

from canonical_subject import canonical_cluster_key, canonicalize_title_question, canonicalize_title_subject, title_case
from title_intent_classifier import TitleIntent, classify_title_intent
from title_pattern_bank import FAMILY_PRIORITY, TITLE_PATTERNS
from title_scorer import TitleCandidate, score_title, select_best

@dataclass(frozen=True)
class TitleDecision:
    title: str
    pattern: str
    reason: str
    family: str = ""
    intent_family: str = ""
    subject: str = ""
    question: str = ""
    cluster_key: str = ""
    score: int = 0

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()

def title_case_keyword(keyword: str) -> str:
    return title_case(keyword)

def trim_title(title: str, max_len: int = 112) -> str:
    title = normalize(title).rstrip(" .")
    if len(title) <= max_len:
        return title
    return title[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:-&")

def rotation_index(keyword: str, family: str, size: int) -> int:
    if size <= 0: return 0
    digest = hashlib.md5(f"{keyword.lower()}::{family}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size

def title_context(keyword: str, year: int) -> dict[str, str | int]:
    subject = canonicalize_title_subject(keyword)
    question = canonicalize_title_question(keyword)
    return {"kw": subject, "subject": subject, "question": question.rstrip("?"), "raw_kw": title_case(keyword), "year": year}

def candidate_families(intent: TitleIntent) -> list[str]:
    families = FAMILY_PRIORITY.get(intent.intent_family, [intent.primary_family])
    merged = []
    for family in [intent.primary_family, *families, *intent.secondary_families, "general_review"]:
        if family in TITLE_PATTERNS and family not in merged:
            merged.append(family)
    return merged

def iter_rotated_patterns(keyword: str, family: str) -> list[tuple[int, str]]:
    patterns = TITLE_PATTERNS.get(family, [])
    if not patterns: return []
    start = rotation_index(keyword, family, len(patterns))
    return [((start + offset) % len(patterns), patterns[(start + offset) % len(patterns)]) for offset in range(len(patterns))]

def apply_family_bias(candidate: TitleCandidate, intent: TitleIntent) -> TitleCandidate:
    score = candidate.score
    reasons = list(candidate.reasons)
    if candidate.family == intent.primary_family:
        score += 18
        reasons.append("primary-family-bonus")
    elif candidate.family in FAMILY_PRIORITY.get(intent.intent_family, [])[0:1]:
        score += 10
        reasons.append("preferred-family-bonus")
    if candidate.family == "reality_check" and intent.primary_family != "reality_check":
        score -= 18
        reasons.append("reality-check-limited")
    if candidate.family == "general_review" and intent.primary_family != "general_review":
        score -= 16
        reasons.append("generic-family-limited")
    return replace(candidate, score=score, reasons=reasons)

def generate_title_candidates(keyword: str, article_type: str = "", classification: dict[str, Any] | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> list[TitleCandidate]:
    year = year or datetime.now().year
    intent = classify_title_intent(keyword, article_type, classification)
    ctx = title_context(keyword, year)
    candidates = []
    for family in candidate_families(intent):
        for original_index, pattern in iter_rotated_patterns(keyword, family):
            pattern_id = f"{family}_{original_index + 1:02d}"
            title = trim_title(pattern.format(**ctx))
            scored = score_title(title, str(ctx["kw"]), family, pattern_id, existing_titles, existing_patterns)
            candidates.append(apply_family_bias(scored, intent))
    return candidates

def choose_title_pattern(keyword: str, article_type: str, classification: dict | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> TitleDecision:
    year = year or datetime.now().year
    intent = classify_title_intent(keyword, article_type, classification)
    ctx = title_context(keyword, year)
    best = select_best(generate_title_candidates(keyword, article_type, classification, year, existing_titles, existing_patterns))
    cluster_key = canonical_cluster_key(keyword, intent.intent_family)
    return TitleDecision(
        title=best.title,
        pattern=best.pattern_id,
        reason="; ".join(best.reasons),
        family=best.family,
        intent_family=intent.intent_family,
        subject=str(ctx["kw"]),
        question=str(ctx["question"]),
        cluster_key=cluster_key,
        score=best.score,
    )

def generate_seo_title(keyword: str, article_type: str = "", classification: dict | None = None, original_title: str | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> str:
    return choose_title_pattern(keyword, article_type, classification, year, existing_titles, existing_patterns).title

def generate_title_metadata(keyword: str, article_type: str = "", classification: dict | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> dict[str, Any]:
    return asdict(choose_title_pattern(keyword, article_type, classification, year, existing_titles, existing_patterns))

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an intent-family SEO title.")
    parser.add_argument("keyword", nargs="+")
    parser.add_argument("--type", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    keyword = " ".join(args.keyword)
    if args.json:
        print(asdict(choose_title_pattern(keyword, args.type)))
    else:
        print(generate_seo_title(keyword, args.type))

if __name__ == "__main__":
    main()
