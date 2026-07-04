#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Intent-family SEO title engine.

The engine is designed for large keyword pools: classify title intent, generate
multiple candidates from pattern families, score candidates, and pick a varied
non-generic headline. It intentionally avoids one-off keyword exceptions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import argparse
import hashlib
import re
from typing import Any

from title_intent_classifier import TitleIntent, classify_title_intent
from title_pattern_bank import FAMILY_PRIORITY, TITLE_PATTERNS
from title_scorer import TitleCandidate, score_title, select_best


SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "is", "of", "on", "or", "the", "to", "vs", "with"}
BRAND_MAP = {
    "bluechew": "BlueChew",
    "extenze": "ExtenZe",
    "ozempic": "Ozempic",
    "wegovy": "Wegovy",
    "mounjaro": "Mounjaro",
    "zepbound": "Zepbound",
    "enzyte": "Enzyte",
    "cbd": "CBD",
    "ed": "ED",
    "glp": "GLP",
    "fda": "FDA",
    "a1c": "A1C",
    "ldl": "LDL",
    "hdl": "HDL",
}


@dataclass(frozen=True)
class TitleDecision:
    title: str
    pattern: str
    reason: str
    family: str = ""
    intent_family: str = ""
    score: int = 0


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def title_case_keyword(keyword: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9+%]+", " ", str(keyword or "")).split()
    out: list[str] = []
    for i, word in enumerate(words):
        lower = word.lower()
        if lower in BRAND_MAP:
            out.append(BRAND_MAP[lower])
        elif i and lower in SMALL_WORDS:
            out.append(lower)
        else:
            out.append(lower[:1].upper() + lower[1:])
    return " ".join(out) or "Article"


def trim_title(title: str, max_len: int = 108) -> str:
    title = normalize(title).rstrip(" .")
    if len(title) <= max_len:
        return title
    return title[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:-&")


def rotation_index(keyword: str, family: str, size: int) -> int:
    if size <= 0:
        return 0
    digest = hashlib.md5(f"{keyword.lower()}::{family}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def rotate(items: list[str], keyword: str, family: str) -> list[str]:
    if not items:
        return []
    idx = rotation_index(keyword, family, len(items))
    return items[idx:] + items[:idx]


def title_context(keyword: str, year: int) -> dict[str, str | int]:
    kw = title_case_keyword(keyword)
    entity = kw
    if re.match(r"^(Do|Does|Can|Will|Is|Are|Should)\b", kw):
        entity = re.sub(r"^(Do|Does|Can|Will|Is|Are|Should)\s+", "", kw).rstrip("?")
    return {"kw": kw, "entity": entity, "year": year}


def candidate_families(intent: TitleIntent) -> list[str]:
    families = FAMILY_PRIORITY.get(intent.intent_family, [intent.primary_family])
    merged: list[str] = []
    for family in [intent.primary_family, *families, *intent.secondary_families, "general_review"]:
        if family in TITLE_PATTERNS and family not in merged:
            merged.append(family)
    return merged


def generate_title_candidates(keyword: str, article_type: str = "", classification: dict[str, Any] | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> list[TitleCandidate]:
    year = year or datetime.now().year
    intent = classify_title_intent(keyword, article_type, classification)
    ctx = title_context(keyword, year)
    candidates: list[TitleCandidate] = []
    for family in candidate_families(intent):
        patterns = rotate(TITLE_PATTERNS.get(family, []), keyword, family)
        for i, pattern in enumerate(patterns):
            pattern_id = f"{family}_{i + 1:02d}"
            title = trim_title(pattern.format(**ctx))
            candidates.append(score_title(title, keyword, family, pattern_id, existing_titles, existing_patterns))
    return candidates


def choose_title_pattern(keyword: str, article_type: str, classification: dict | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> TitleDecision:
    intent = classify_title_intent(keyword, article_type, classification)
    best = select_best(generate_title_candidates(keyword, article_type, classification, year, existing_titles, existing_patterns))
    return TitleDecision(
        title=best.title,
        pattern=best.pattern_id,
        reason="; ".join(best.reasons),
        family=best.family,
        intent_family=intent.intent_family,
        score=best.score,
    )


def generate_seo_title(keyword: str, article_type: str = "", classification: dict | None = None, original_title: str | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> str:
    # original_title is intentionally ignored. AI body writers should not control titles.
    return choose_title_pattern(keyword, article_type, classification, year, existing_titles, existing_patterns).title


def generate_title_metadata(keyword: str, article_type: str = "", classification: dict | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> dict[str, Any]:
    decision = choose_title_pattern(keyword, article_type, classification, year, existing_titles, existing_patterns)
    return asdict(decision)


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
