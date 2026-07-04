#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit title intent classification over a keyword seed file.

Usage:
    python3 scripts/title_intent_audit.py data/title_intent_seed_keywords.txt
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import argparse
import csv
import sys

from title_engine import generate_title_metadata
from title_intent_classifier import classify_title_intent


def read_keywords(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify keyword title intents and preview generated titles.")
    parser.add_argument("input", help="Plain-text keyword file, one keyword per line")
    parser.add_argument("--output", default="output/title_intent_audit.csv")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 2

    rows = []
    used_titles: list[str] = []
    used_patterns: set[str] = set()
    for keyword in read_keywords(input_path):
        intent = classify_title_intent(keyword)
        meta = generate_title_metadata(keyword, classification=asdict(intent), existing_titles=used_titles, existing_patterns=used_patterns)
        used_titles.append(meta["title"])
        used_patterns.add(meta["pattern"])
        rows.append({
            "keyword": keyword,
            "canonical_subject": meta.get("subject"),
            "canonical_question": meta.get("question"),
            "intent_family": intent.intent_family,
            "entity_type": intent.entity_type,
            "modifier": intent.modifier,
            "page_type": intent.page_type,
            "title_family": meta.get("family"),
            "pattern_id": meta.get("pattern"),
            "title_score": meta.get("score"),
            "title": meta.get("title"),
            "reason": meta.get("reason"),
        })

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["keyword", "canonical_subject", "canonical_question", "intent_family", "entity_type", "modifier", "page_type", "title_family", "pattern_id", "title_score", "title", "reason"]
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
