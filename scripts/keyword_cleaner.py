#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keyword cleanup and generation eligibility checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import re


@dataclass(frozen=True)
class KeywordCleanResult:
    raw_keyword: str
    clean_keyword: str
    keyword_status: str
    reason: str


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


TWO_WORD_INTENT_TOKENS = {
    "benefit", "benefits", "side-effects", "side", "effects", "dosage", "dose", "cost", "price",
    "reviews", "review", "results", "safety", "safe", "uses", "use", "symptoms", "risks",
}


def clean_keyword(raw_keyword: str) -> KeywordCleanResult:
    raw = normalize_spaces(raw_keyword)
    cleaned = raw.lower().replace("’", "'")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_?")

    if not cleaned:
        return KeywordCleanResult(raw, cleaned, "skip", "empty keyword")

    words = cleaned.split()
    if len(words) < 2:
        return KeywordCleanResult(raw, cleaned, "low_quality", "too short to infer a useful search intent")

    if len(words) == 2 and not (words[1] in TWO_WORD_INTENT_TOKENS or words[0] in {"best", "top"}):
        return KeywordCleanResult(raw, cleaned, "needs_review", "two-word keyword needs review unless it contains a clear intent token")

    if re.search(r"^\d+\s+(lemon|juice|water|tea|coffee|drops|pill|pills|capsule|capsules)\b", cleaned):
        if "100 lemon" in cleaned or "100 juice" in cleaned:
            return KeywordCleanResult(raw, cleaned.replace("100 lemon", "100% lemon"), "needs_review", "numeric prefix may mean percentage or malformed keyword")
        return KeywordCleanResult(raw, cleaned, "brand_unknown", "numeric product-like keyword needs review before generation")

    if re.search(r"\b(fake|free download|coupon code|near me|amazon price|walmart|where to buy)\b", cleaned):
        return KeywordCleanResult(raw, cleaned, "needs_review", "commercial/local intent is not ready for this editorial writer")

    if len(cleaned) > 120:
        return KeywordCleanResult(raw, cleaned[:120].rstrip(), "needs_review", "keyword is unusually long")

    return KeywordCleanResult(raw, cleaned, "clean", "ready for sample-style generation")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean one keyword and report generation status.")
    parser.add_argument("keyword", nargs="+")
    args = parser.parse_args()
    print(asdict(clean_keyword(" ".join(args.keyword))))


if __name__ == "__main__":
    main()
