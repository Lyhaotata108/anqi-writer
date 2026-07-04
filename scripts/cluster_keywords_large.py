#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cluster large keyword CSV files before article generation.

Usage:
    python3 scripts/cluster_keywords_large.py data/keywords_weight_loss.csv --category 1
    python3 scripts/cluster_keywords_large.py data/keywords_cbd.csv --category 5
    python3 scripts/cluster_keywords_large.py data/keywords_blood.csv --category 9

Outputs:
    <input>.clusters.csv  one row per suggested article
    <input>.members.csv   one row per original keyword with cluster mapping
    <input>.to_generate.txt primary keywords for the browser UI
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable


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
    "will",
    "can",
    "could",
    "would",
    "does",
    "do",
    "is",
    "are",
    "should",
    "why",
    "how",
    "what",
    "when",
    "where",
}

STOP_WORDS = {
    "the",
    "a",
    "an",
    "for",
    "to",
    "of",
    "and",
    "or",
    "in",
    "on",
    "with",
    "my",
    "your",
    "you",
    "me",
    "best",
    "top",
    "new",
    "review",
    "reviews",
    "2024",
    "2025",
    "2026",
}


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
    """Return (intent, modifier, page_type)."""
    k = normalize(keyword)

    if any(token in k for token in [" vs ", " versus ", "compare", "comparison", "better than", "instead of"]):
        target = "general"
        for item in [
            "metformin",
            "ozempic",
            "mounjaro",
            "wegovy",
            "zbound",
            "cbd",
            "apple cider vinegar",
            "green tea",
        ]:
            if item in k:
                target = item.replace(" ", "_")
                break
        return "comparison", target, "comparison_decision"

    if any(token in k for token in ["interfere", "interaction", "interact", "with medication", "with prednisone", "with thyroid"]):
        target = "medication"
        for item in [
            "prednisone",
            "thyroid medication",
            "thyroid",
            "levothyroxine",
            "metformin",
            "insulin",
            "birth control",
            "antibiotics",
            "statin",
        ]:
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

    if any(token in k for token in [
        "side effect",
        "side effects",
        "headache",
        "headaches",
        "gout",
        "gout attack",
        "stomach",
        "belly",
        "diarrhea",
        "constipation",
        "nausea",
        "cramps",
        "dizzy",
        "fatigue",
        "tired",
        "itchy",
        "skin",
        "darker",
    ]):
        symptom = "general_side_effect"
        for item in [
            "headaches",
            "headache",
            "gout attack",
            "gout",
            "stomach",
            "belly",
            "diarrhea",
            "constipation",
            "nausea",
            "cramps",
            "dizzy",
            "fatigue",
            "tired",
            "itchy skin",
            "itchy",
            "skin",
            "darker",
        ]:
            if item in k:
                symptom = item.replace(" ", "_")
                break
        return "side_effect", symptom, "side_effect_pain"

    return "general", "general", "general_article"


def choose_primary_keyword(keywords: list[str]) -> str:
    def score(keyword: str) -> tuple[int, int, int]:
        k = normalize(keyword)
        words = k.split()
        question_penalty = 1 if words and words[0] in QUESTION_PREFIXES else 0
        return question_penalty, len(words), len(k)

    return sorted(keywords, key=score)[0]


def read_keywords_csv(path: Path) -> list[str]:
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
        if not row or keyword_col >= len(row):
            continue
        keyword = row[keyword_col].strip()
        if keyword:
            keywords.append(keyword)
    return keywords


def cluster_keywords(keywords: Iterable[str]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    groups: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()

    for raw in keywords:
        keyword = raw.strip()
        if not keyword:
            continue
        normalized = normalize(keyword)
        if normalized in seen:
            continue
        seen.add(normalized)

        entity = detect_entity(keyword)
        intent, modifier, _ = detect_intent_and_modifier(keyword)
        cluster_key = f"{entity}__{intent}__{modifier}"
        groups[cluster_key].append(keyword)

    cluster_rows: list[dict[str, object]] = []
    member_rows: list[dict[str, object]] = []

    for cluster_key, group_keywords in sorted(groups.items()):
        entity, intent, modifier = cluster_key.split("__", 2)
        primary = choose_primary_keyword(group_keywords)
        _, _, page_type = detect_intent_and_modifier(primary)
        secondary = [keyword for keyword in group_keywords if keyword != primary]
        should_generate = "yes" if len(group_keywords) >= 2 else "maybe"

        cluster_rows.append({
            "cluster_id": cluster_key,
            "entity": entity,
            "intent": intent,
            "modifier": modifier,
            "page_type": page_type,
            "primary_keyword": primary,
            "keyword_count": len(group_keywords),
            "secondary_keywords_sample": " | ".join(secondary[:30]),
            "should_generate": should_generate,
        })

        for keyword in group_keywords:
            member_rows.append({
                "keyword": keyword,
                "cluster_id": cluster_key,
                "entity": entity,
                "intent": intent,
                "modifier": modifier,
                "page_type": page_type,
                "is_primary": "yes" if keyword == primary else "no",
                "primary_keyword": primary,
            })

    return cluster_rows, member_rows


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_to_generate(path: Path, rows: list[dict[str, object]], include_maybe: bool) -> int:
    allowed = {"yes", "maybe"} if include_maybe else {"yes"}
    keywords = [str(row["primary_keyword"]) for row in rows if row.get("should_generate") in allowed]
    path.write_text("\n".join(keywords), encoding="utf-8")
    return len(keywords)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster large keyword CSV files by entity and intent.")
    parser.add_argument("input_csv", help="CSV file with a Keyword column, or keywords in the first column.")
    parser.add_argument("--category", type=int, default=None, help="Optional category id, kept for future workflow compatibility.")
    parser.add_argument("--yes-only", action="store_true", help="Export only clusters marked yes, excluding maybe.")
    args = parser.parse_args()

    input_path = Path(args.input_csv).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"File not found: {input_path}")

    keywords = read_keywords_csv(input_path)
    cluster_rows, member_rows = cluster_keywords(keywords)

    clusters_path = input_path.with_name(input_path.stem + ".clusters.csv")
    members_path = input_path.with_name(input_path.stem + ".members.csv")
    to_generate_path = input_path.with_name(input_path.stem + ".to_generate.txt")

    write_csv(clusters_path, cluster_rows, [
        "cluster_id",
        "entity",
        "intent",
        "modifier",
        "page_type",
        "primary_keyword",
        "keyword_count",
        "secondary_keywords_sample",
        "should_generate",
    ])
    write_csv(members_path, member_rows, [
        "keyword",
        "cluster_id",
        "entity",
        "intent",
        "modifier",
        "page_type",
        "is_primary",
        "primary_keyword",
    ])
    exported = write_to_generate(to_generate_path, cluster_rows, include_maybe=not args.yes_only)

    print(f"Input keywords: {len(keywords)}")
    print(f"Clusters: {len(cluster_rows)}")
    print(f"Members: {len(member_rows)}")
    print(f"Exported to-generate keywords: {exported}")
    print(f"Clusters CSV: {clusters_path}")
    print(f"Members CSV: {members_path}")
    print(f"To generate TXT: {to_generate_path}")


if __name__ == "__main__":
    main()
