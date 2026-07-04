#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reusable keyword entity and intent classifier.

This module is intentionally rule-based so large keyword batches can be
classified locally before any AI call.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import csv
import re
from pathlib import Path


ENTITY_PATTERNS: dict[str, list[str]] = {
    "berberine": ["berberine"],
    "mounjaro": ["mounjaro", "tirzepatide"],
    "ozempic": ["ozempic", "semaglutide"],
    "wegovy": ["wegovy"],
    "zbound": ["zbound"],
    "metformin": ["metformin"],
    "cbd": ["cbd", "cannabidiol", "cbd gummies", "cbd oil"],
    "blood sugar": ["blood sugar", "blood glucose", "glucose", "a1c"],
    "cholesterol": ["cholesterol", "ldl", "hdl", "triglycerides"],
    "blood pressure": ["blood pressure", "hypertension"],
}

QUESTION_PREFIXES = {
    "will", "can", "could", "would", "does", "do", "is", "are", "should",
    "why", "how", "what", "when", "where",
}

STOP_WORDS = {
    "the", "a", "an", "for", "to", "of", "and", "or", "in", "on", "with",
    "my", "your", "you", "me", "best", "top", "new", "review", "reviews",
    "2024", "2025", "2026",
}


@dataclass(frozen=True)
class KeywordClassification:
    keyword: str
    normalized_keyword: str
    entity: str
    intent: str
    modifier: str
    page_type: str
    lane: str
    cluster_key: str


def normalize(text: str) -> str:
    text = str(text or "").lower().strip()
    text = text.replace("’", "'")
    text = text.replace("natures ozempic", "nature's ozempic")
    text = re.sub(r"[^a-z0-9\s'/-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_question_prefixes(text: str) -> str:
    words = normalize(text).split()
    while words and words[0] in QUESTION_PREFIXES:
        words.pop(0)
    return " ".join(words)


def detect_entity(keyword: str) -> str:
    k = normalize(keyword)
    entries = sorted(
        ENTITY_PATTERNS.items(),
        key=lambda item: max(len(pattern) for pattern in item[1]),
        reverse=True,
    )
    for entity, patterns in entries:
        if any(pattern in k for pattern in patterns):
            return entity

    cleaned = strip_question_prefixes(k)
    words = [word for word in cleaned.split() if word not in STOP_WORDS]
    if len(words) >= 2:
        return " ".join(words[:2])
    if words:
        return words[0]
    return "unknown"


def detect_intent_and_modifier(keyword: str) -> tuple[str, str, str]:
    k = normalize(keyword)

    if any(token in k for token in [" vs ", " versus ", "compare", "comparison", "better than", "instead of"]):
        target = "general"
        for item in ["metformin", "ozempic", "mounjaro", "wegovy", "zbound", "cbd", "apple cider vinegar", "green tea"]:
            if item in k:
                target = item.replace(" ", "_")
                break
        return "comparison", target, "comparison_decision"

    if any(token in k for token in ["interfere", "interaction", "interact", "with medication", "with prednisone", "with thyroid"]):
        target = "medication"
        for item in ["prednisone", "thyroid medication", "thyroid", "levothyroxine", "metformin", "insulin", "birth control", "antibiotics", "statin"]:
            if item in k:
                target = item.replace(" ", "_")
                break
        return "interaction", target, "safety_interaction"

    if any(token in k for token in ["pregnant", "pregnancy", "baby", "breastfeeding", "breast feeding", "hurt the baby"]):
        return "safety", "pregnancy_baby", "safety_guide"

    if any(token in k for token in ["drug test", "show up on a drug test", "test positive"]):
        return "safety", "drug_test", "safety_guide"

    if any(token in k for token in ["too low blood sugar", "blood sugar too low", "go too low", "low blood sugar", "hypoglycemia"]):
        return "side_effect", "low_blood_sugar", "side_effect_pain"

    if any(token in k for token in ["lower blood sugar", "reduce blood sugar", "blood glucose", "lower blood glucose", "lower my a1c", "reduce a1c", "a1c"]):
        return "benefit", "blood_sugar_a1c", "benefit_explainer"

    if any(token in k for token in ["cholesterol", "ldl", "hdl", "triglycerides"]):
        return "benefit", "cholesterol", "benefit_explainer"

    if any(token in k for token in ["weight loss", "lose weight", "losing weight", "make you lose weight", "help lose weight", "fat loss"]):
        return "weight_loss", "general", "viral_truth"

    if any(token in k for token in ["hunger", "appetite", "cravings", "food noise"]):
        return "appetite", "hunger_cravings", "viral_truth"

    if any(token in k for token in ["best time", "when to take", "morning or night", "before bed", "with food", "empty stomach"]):
        return "timing", "when_to_take", "timing_guide"

    if any(token in k for token in ["dose", "dosage", "how much", "mg", "milligram"]):
        return "dosage", "general", "dosage_guide"

    if any(token in k for token in ["how long", "how fast", "how quickly", "when does", "time to work"]):
        return "how_long", "time_to_work", "expectation_guide"

    if any(token in k for token in ["break fast", "break my fast", "fasting"]):
        return "fasting", "break_fast", "lifestyle_question"

    side_effect_tokens = [
        "side effect", "side effects", "headache", "headaches", "gout", "gout attack",
        "stomach", "belly", "diarrhea", "constipation", "nausea", "cramps",
        "dizzy", "fatigue", "tired", "itchy", "skin", "darker",
    ]
    if any(token in k for token in side_effect_tokens):
        symptom = "general_side_effect"
        for item in ["headaches", "headache", "gout attack", "gout", "stomach", "belly", "diarrhea", "constipation", "nausea", "cramps", "dizzy", "fatigue", "tired", "itchy skin", "itchy", "skin", "darker"]:
            if item in k:
                symptom = item.replace(" ", "_")
                break
        return "side_effect", symptom, "side_effect_pain"

    return "general", "general", "general_article"


def detect_lane(entity: str, keyword: str) -> str:
    k = normalize(keyword)
    if entity in {"mounjaro", "ozempic", "wegovy", "zbound", "metformin"}:
        return "medication"
    if entity == "cbd":
        return "cbd"
    if entity in {"blood sugar", "cholesterol", "blood pressure"}:
        return "blood"
    if any(token in k for token in ["berberine", "apple cider vinegar", "green tea extract", "fiber supplement", "supplement"]):
        return "supplement"
    return "weight_loss"


def classify_keyword(keyword: str) -> KeywordClassification:
    normalized = normalize(keyword)
    entity = detect_entity(keyword)
    intent, modifier, page_type = detect_intent_and_modifier(keyword)
    lane = detect_lane(entity, keyword)
    cluster_key = f"{entity}__{intent}__{modifier}"
    return KeywordClassification(
        keyword=keyword,
        normalized_keyword=normalized,
        entity=entity,
        intent=intent,
        modifier=modifier,
        page_type=page_type,
        lane=lane,
        cluster_key=cluster_key,
    )


def read_keywords(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return []
    header = [normalize(value) for value in rows[0]]
    keyword_col = 0
    for index, column_name in enumerate(header):
        if column_name in {"keyword", "keywords", "query", "search term", "search_term"}:
            keyword_col = index
            break
    has_header = any("keyword" in value or "query" in value or "search" in value for value in header)
    start = 1 if has_header else 0
    keywords: list[str] = []
    for row in rows[start:]:
        if row and keyword_col < len(row) and row[keyword_col].strip():
            keywords.append(row[keyword_col].strip())
    return keywords


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify keywords by entity, intent, modifier, page type, and lane.")
    parser.add_argument("input", help="CSV/TXT keyword file or a single keyword.")
    parser.add_argument("--output", default=None, help="Optional output CSV path.")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    if input_path.exists():
        keywords = read_keywords(input_path)
        output_path = Path(args.output).expanduser() if args.output else input_path.with_suffix(".classified.csv")
        rows = [asdict(classify_keyword(keyword)) for keyword in keywords]
        with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [field.name for field in KeywordClassification.__dataclass_fields__.values()])
            writer.writeheader()
            writer.writerows(rows)
        print(f"Classified {len(rows)} keywords: {output_path}")
    else:
        print(asdict(classify_keyword(args.input)))


if __name__ == "__main__":
    main()
