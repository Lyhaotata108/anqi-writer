#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit title intent classification and CTR title output."""

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
    parser = argparse.ArgumentParser(description="Classify keyword title intents and preview CTR-first generated titles.")
    parser.add_argument("input", help="Plain-text keyword file, one keyword per line")
    parser.add_argument("--output", default="output/title_intent_audit.csv")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 2

    rows = []
    used_titles = []
    used_patterns = set()
    seen_clusters = {}
    for keyword in read_keywords(input_path):
        intent = classify_title_intent(keyword)
        meta = generate_title_metadata(keyword, classification=asdict(intent), existing_titles=used_titles, existing_patterns=used_patterns)
        cluster_key = meta.get("cluster_key")
        cluster_first_keyword = seen_clusters.get(cluster_key, "")
        cluster_status = "primary" if not cluster_first_keyword else "duplicate"
        if not cluster_first_keyword:
            seen_clusters[cluster_key] = keyword

        used_titles.append(meta["title"])
        used_patterns.add(meta["pattern"])
        rows.append({
            "keyword": keyword,
            "canonical_subject": meta.get("subject"),
            "canonical_question": meta.get("question"),
            "cluster_key": cluster_key,
            "cluster_status": cluster_status,
            "cluster_first_keyword": cluster_first_keyword,
            "intent_family": intent.intent_family,
            "entity_type": intent.entity_type,
            "modifier": intent.modifier,
            "page_type": intent.page_type,
            "ctr_angle": meta.get("ctr_angle"),
            "click_trigger": meta.get("click_trigger"),
            "risk_trigger": meta.get("risk_trigger"),
            "specificity_score": meta.get("specificity_score"),
            "title_family": meta.get("family"),
            "pattern_id": meta.get("pattern"),
            "technical_score": meta.get("technical_score"),
            "ctr_score": meta.get("ctr_score"),
            "title_score": meta.get("score"),
            "title": meta.get("title"),
            "reason": meta.get("reason"),
        })

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "keyword", "canonical_subject", "canonical_question", "cluster_key", "cluster_status",
        "cluster_first_keyword", "intent_family", "entity_type", "modifier", "page_type",
        "ctr_angle", "click_trigger", "risk_trigger", "specificity_score",
        "title_family", "pattern_id", "technical_score", "ctr_score", "title_score", "title", "reason",
    ]
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    duplicate_count = sum(1 for row in rows if row["cluster_status"] == "duplicate")
    low_ctr = sum(1 for row in rows if int(row["ctr_score"] or 0) < 75)
    print(f"Wrote {len(rows)} rows to {out}")
    print(f"Clusters: {len(seen_clusters)} primary · {duplicate_count} duplicate")
    print(f"Low CTR rows: {low_ctr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
