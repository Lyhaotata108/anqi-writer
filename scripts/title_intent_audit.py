#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit title intent classification and CTR title output.

V3.8 supports the new pipeline where keyword_cluster_engine.py first selects
primary article keywords. When the input is primary_article_queue_v1.csv, titles
are generated only for primary articles and secondary keywords are carried into
later body/FAQ planning.
"""

from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import argparse
import csv
import sys
from typing import Any

from title_engine import generate_title_metadata
from title_intent_classifier import classify_title_intent
from title_scorer import title_frame_key, title_shape_key


def read_keyword_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return []
            fields = {name.lower(): name for name in reader.fieldnames}
            keyword_field = fields.get("primary_keyword") or fields.get("keyword") or reader.fieldnames[0]
            records: list[dict[str, Any]] = []
            for row in reader:
                keyword = str(row.get(keyword_field, "")).strip()
                if not keyword:
                    continue
                records.append({
                    "keyword": keyword,
                    "source_cluster_key": row.get(fields.get("cluster_key", ""), "") if fields.get("cluster_key") else "",
                    "source_cluster_size": row.get(fields.get("cluster_size", ""), "") if fields.get("cluster_size") else "",
                    "source_primary_score": row.get(fields.get("primary_score", ""), "") if fields.get("primary_score") else "",
                    "secondary_keywords": row.get(fields.get("secondary_keywords", ""), "") if fields.get("secondary_keywords") else "",
                    "faq_keywords": row.get(fields.get("faq_keywords", ""), "") if fields.get("faq_keywords") else "",
                    "h2_keywords": row.get(fields.get("h2_keywords", ""), "") if fields.get("h2_keywords") else "",
                    "semantic_keywords": row.get(fields.get("semantic_keywords", ""), "") if fields.get("semantic_keywords") else "",
                    "all_cluster_keywords": row.get(fields.get("all_cluster_keywords", ""), "") if fields.get("all_cluster_keywords") else "",
                    "source_type": "primary_article_queue" if fields.get("primary_keyword") else "csv_keywords",
                })
            return records
    return [{"keyword": line.strip(), "source_type": "plain_keywords"} for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify keyword title intents and preview CTR-first generated titles.")
    parser.add_argument("input", help="Plain-text keyword file or primary_article_queue CSV")
    parser.add_argument("--output", default="output/title_intent_audit.csv")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 2

    records = read_keyword_records(input_path)
    input_is_primary_queue = any(record.get("source_type") == "primary_article_queue" for record in records)

    rows = []
    used_titles = []
    used_patterns = set()
    seen_clusters = {}
    seen_frames = {}
    seen_shapes = {}
    for record in records:
        keyword = record["keyword"]
        intent = classify_title_intent(keyword)
        meta = generate_title_metadata(keyword, classification=asdict(intent), existing_titles=used_titles, existing_patterns=used_patterns)
        cluster_key = record.get("source_cluster_key") or meta.get("cluster_key")
        if input_is_primary_queue:
            cluster_first_keyword = ""
            cluster_status = "primary"
        else:
            cluster_first_keyword = seen_clusters.get(cluster_key, "")
            cluster_status = "primary" if not cluster_first_keyword else "duplicate"
            if not cluster_first_keyword:
                seen_clusters[cluster_key] = keyword

        if input_is_primary_queue and cluster_key not in seen_clusters:
            seen_clusters[cluster_key] = keyword

        frame_key = title_frame_key(meta["title"])
        frame_first_keyword = seen_frames.get(frame_key, "")
        frame_status = "fresh_frame" if not frame_first_keyword else "reused_frame"
        if not frame_first_keyword:
            seen_frames[frame_key] = keyword

        shape_key = meta.get("title_shape") or title_shape_key(meta["title"])
        seen_shapes[shape_key] = seen_shapes.get(shape_key, 0) + 1

        used_titles.append(meta["title"])
        used_patterns.add(meta["pattern"])
        rows.append({
            "keyword": keyword,
            "canonical_subject": meta.get("subject"),
            "canonical_question": meta.get("question"),
            "cluster_key": cluster_key,
            "cluster_status": cluster_status,
            "cluster_first_keyword": cluster_first_keyword,
            "source_cluster_size": record.get("source_cluster_size", ""),
            "source_primary_score": record.get("source_primary_score", ""),
            "secondary_keywords": record.get("secondary_keywords", ""),
            "faq_keywords": record.get("faq_keywords", ""),
            "h2_keywords": record.get("h2_keywords", ""),
            "semantic_keywords": record.get("semantic_keywords", ""),
            "all_cluster_keywords": record.get("all_cluster_keywords", ""),
            "title_frame_key": frame_key,
            "title_frame_status": frame_status,
            "title_frame_first_keyword": frame_first_keyword,
            "title_shape": shape_key,
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
        "cluster_first_keyword", "source_cluster_size", "source_primary_score",
        "secondary_keywords", "faq_keywords", "h2_keywords", "semantic_keywords", "all_cluster_keywords",
        "title_frame_key", "title_frame_status", "title_frame_first_keyword", "title_shape",
        "intent_family", "entity_type", "modifier", "page_type",
        "ctr_angle", "click_trigger", "risk_trigger", "specificity_score",
        "title_family", "pattern_id", "technical_score", "ctr_score", "title_score", "title", "reason",
    ]
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    duplicate_count = sum(1 for row in rows if row["cluster_status"] == "duplicate")
    reused_frames = sum(1 for row in rows if row["title_frame_status"] == "reused_frame")
    low_ctr = sum(1 for row in rows if int(row["ctr_score"] or 0) < 75)
    shape_summary = ", ".join(f"{k}:{v}" for k, v in sorted(seen_shapes.items()))
    mode = "primary_article_queue" if input_is_primary_queue else "raw_keyword_list"
    print(f"Wrote {len(rows)} rows to {out}")
    print(f"Input mode: {mode}")
    print(f"Clusters: {len(seen_clusters)} primary · {duplicate_count} duplicate")
    print(f"Frames: {len(seen_frames)} unique · {reused_frames} reused")
    print(f"Shapes: {shape_summary}")
    print(f"Low CTR rows: {low_ctr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
