#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reusable SEO title engine for batch article generation.

The goal is controlled formula variation, not one-off keyword fixes:
keyword-first, current-year freshness, risk/results/safety hooks, and no generic
AI title phrases such as "Comprehensive Guide" or "Evidence-Based Review".
"""

from __future__ import annotations

from datetime import datetime
import argparse
import re
from dataclasses import asdict, dataclass


BANNED_TITLE_PHRASES = [
    "comprehensive",
    "ultimate guide",
    "complete guide",
    "deep dive",
    "everything you need to know",
    "clinical evidence and practical realities",
    "evidence-based review",
    "comprehensive, evidence-based review",
    "the real story behind",
]

SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "is", "of", "on", "or", "the", "to", "vs", "with"}


@dataclass(frozen=True)
class TitleDecision:
    title: str
    pattern: str
    reason: str


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def title_case_keyword(keyword: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9+%]+", " ", keyword).split()
    out: list[str] = []
    for i, word in enumerate(words):
        lower = word.lower()
        if i and lower in SMALL_WORDS:
            out.append(lower)
        elif lower in {"cbd", "a1c", "ldl", "hdl", "ed"}:
            out.append(lower.upper())
        elif lower in {"ozempic", "wegovy", "mounjaro", "bluechew", "extenze", "enzyte"}:
            out.append({"bluechew": "BlueChew", "extenze": "ExtenZe"}.get(lower, lower[:1].upper() + lower[1:]))
        else:
            out.append(lower[:1].upper() + lower[1:])
    return " ".join(out) or "Article"


def clean_title(title: str) -> str:
    title = normalize(title)
    title = re.sub(r"\s+[|\-–—]\s+.*$", "", title).strip()
    for phrase in BANNED_TITLE_PHRASES:
        title = re.sub(re.escape(phrase), "", title, flags=re.I).strip(" -:—")
    return normalize(title)


def trim_title(title: str, max_len: int = 76) -> str:
    title = normalize(title).rstrip(" .")
    if len(title) <= max_len:
        return title
    cut = title[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:-&")
    return cut or title[:max_len].rstrip(" ,;:-&")


def is_public_figure(classification: dict | None, keyword: str) -> bool:
    classification = classification or {}
    page_type = str(classification.get("page_type") or "").lower()
    entity = str(classification.get("entity") or "").strip()
    if page_type in {"viral_truth", "public_figure", "celebrity_profile"} and len(entity.split()) >= 2:
        return True
    if re.search(r"\b(weight loss journey|transformation|before and after)\b", keyword, flags=re.I) and len(keyword.split()) >= 3:
        return True
    return False


def choose_title_pattern(keyword: str, article_type: str, classification: dict | None = None, year: int | None = None) -> TitleDecision:
    year = year or datetime.now().year
    k = normalize(keyword).lower()
    kw = title_case_keyword(keyword)
    page_type = str((classification or {}).get("page_type") or "").lower()

    if article_type == "top_10_listicle" or re.search(r"\b(top\s*\d+|best|ranked)\b", k):
        if kw.lower().startswith(("top ", "best ")):
            title = f"{kw}: What Works, What Fails & Safety Tips"
        else:
            title = f"Best {kw} {year}: What Works & What To Avoid"
        return TitleDecision(trim_title(title), "top_list", "listicle keyword with works/fails/safety hook")

    if article_type == "comparison_decision" or any(token in k for token in [" vs ", " versus ", "compare", "comparison"]):
        return TitleDecision(trim_title(f"{kw}: Real Differences, Risks & Best Uses"), "comparison", "comparison intent")

    if article_type == "side_effect_safety" or re.search(r"\b(side effects?|safe|safety|risks?|drug test|interaction)\b", k):
        return TitleDecision(trim_title(f"{kw}: Side Effects, Hidden Risks & What To Avoid"), "safety", "safety or risk intent")

    if article_type == "dosage_guide" or re.search(r"\b(dosage|dose|how much|mg|drops?|capsules?|pills?)\b", k):
        return TitleDecision(trim_title(f"{kw}: Dosage, Side Effects & {year} Safety Check"), "dosage", "dosage intent")

    if article_type == "timing_guide" or re.search(r"\b(when to take|best time|how long|how fast|how soon)\b", k):
        return TitleDecision(trim_title(f"{kw}: Best Time, Results Timeline & Safety Tips"), "timing", "timing intent")

    if article_type == "symptom_explainer":
        return TitleDecision(trim_title(f"{kw}: Causes, Risks & What To Check Next"), "symptom", "symptom explainer intent")

    if article_type == "cost_review":
        return TitleDecision(trim_title(f"{kw}: Cost, Coverage & Is It Worth It in {year}"), "cost", "cost/value intent")

    if is_public_figure(classification, keyword):
        return TitleDecision(trim_title(f"{kw}: Timeline, Results & What Is Actually Public"), "public_figure", "public figure / viral profile intent")

    if article_type == "process_explainer":
        return TitleDecision(trim_title(f"{kw}: What Happens, Costs & Safety Questions"), "process", "process/how-it-works intent")

    if re.search(r"\b(reviews?|users?|reddit|trial|tested|lab test)\b", k):
        return TitleDecision(trim_title(f"{kw}: Reviews, Real Results & Safety Notes"), "review_analysis", "review/tested intent")

    if article_type == "evidence_review":
        return TitleDecision(trim_title(f"{kw}: Real Results, Risks & {year} Safety"), "evidence_review", "evidence/review intent")

    if page_type == "viral_truth":
        return TitleDecision(trim_title(f"{kw}: What Is Public, What Is Hype & {year} Update"), "viral_truth", "viral truth / fact-check intent")

    return TitleDecision(trim_title(f"{kw}: What Works, What Fails & Safety Tips"), "fallback", "fallback SEO title pattern")


def generate_seo_title(keyword: str, article_type: str, classification: dict | None = None, original_title: str | None = None, year: int | None = None) -> str:
    original = clean_title(original_title or "")
    if original:
        lower = original.lower()
        banned = any(phrase in lower for phrase in BANNED_TITLE_PHRASES)
        weak = not any(hook in lower for hook in ["risk", "safety", "result", "tested", "review", "works", "hidden", "timeline", "2026", str(year or datetime.now().year)])
        keyword_first = original.lower().startswith(title_case_keyword(keyword).lower().split(":")[0][:18].lower())
        if keyword_first and not banned and not weak:
            return trim_title(original)
    return choose_title_pattern(keyword, article_type, classification, year).title


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a batch-safe SEO title.")
    parser.add_argument("keyword", nargs="+")
    parser.add_argument("--type", default="evidence_review")
    args = parser.parse_args()
    print(asdict(choose_title_pattern(" ".join(args.keyword), args.type)))


if __name__ == "__main__":
    main()
