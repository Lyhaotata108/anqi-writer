#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cluster keywords before title/body generation.

Keyword Cluster V1 changes the pipeline from "every keyword gets a title" to:
raw keywords -> clustered primary article queue -> title generation -> body plan.

Outputs:
- output/keyword_cluster_audit_v1.csv: all keywords with cluster/merge decisions
- output/primary_article_queue_v1.csv: only publishable primary article rows
"""

from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import argparse
import csv
import re
from typing import Any

from canonical_subject import canonical_cluster_key, canonicalize_title_subject
from title_intent_classifier import classify_title_intent


DEFAULT_AUDIT_OUTPUT = "output/keyword_cluster_audit_v1.csv"
DEFAULT_QUEUE_OUTPUT = "output/primary_article_queue_v1.csv"

QUESTION_PREFIX_RE = re.compile(r"^(what|why|how|when|where|who|does|do|can|will|is|are|should)\b", re.I)
LOW_PRIMARY_HINTS = {
    "reddit", "reviews", "review", "pictures", "photos", "before and after", "near me",
    "pdf", "today", "coupon", "free", "side effects", "safe", "safety"
}
HIGH_PRIMARY_HINTS = {
    "weight loss", "best", "recipe", "for weight loss", "pills", "supplement", "ozempic",
    "mounjaro", "wegovy", "semaglutide", "metformin", "berberine", "cost", "insurance"
}


def normalize(text: str) -> str:
    text = str(text or "").replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-zA-Z0-9+%'\s-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def word_count(text: str) -> int:
    return len(re.findall(r"[a-z0-9]+", normalize(text)))


def read_keywords(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return []
            fields = {name.lower(): name for name in reader.fieldnames}
            key_field = fields.get("keyword") or fields.get("primary_keyword") or reader.fieldnames[0]
            return [str(row.get(key_field, "")).strip() for row in reader if str(row.get(key_field, "")).strip()]
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def primary_keyword_score(keyword: str, subject: str, intent_family: str) -> tuple[int, list[str]]:
    k = normalize(keyword)
    s = normalize(subject)
    wc = word_count(keyword)
    score = 0
    reasons: list[str] = []

    if 3 <= wc <= 6:
        score += 22
        reasons.append("clean-length")
    elif 7 <= wc <= 9:
        score += 8
        reasons.append("acceptable-length")
    else:
        score -= 12
        reasons.append("awkward-length")

    if "weight loss" in k:
        score += 18
        reasons.append("contains-weight-loss")
    if any(token in k for token in HIGH_PRIMARY_HINTS):
        score += 12
        reasons.append("articleable-topic")
    if normalize(subject) and (k == s or k.replace("for weight loss", "weight loss").strip() == s.replace("for weight loss", "weight loss").strip()):
        score += 14
        reasons.append("matches-canonical-subject")

    if QUESTION_PREFIX_RE.match(k):
        score -= 18
        reasons.append("question-better-as-faq")
    if any(token in k for token in LOW_PRIMARY_HINTS):
        score -= 10
        reasons.append("support-modifier")
    if k.startswith(("what is", "how to", "does", "do ", "can ", "should ")):
        score -= 10
        reasons.append("longtail-question")
    if intent_family in {"pills_commercial", "supplement_commercial", "viral_recipe", "glp1_medication", "best_top"}:
        score += 10
        reasons.append("strong-article-intent")
    if intent_family in {"safety", "dosage", "timing_guide", "cost_access", "injection_site"}:
        score += 4
        reasons.append("specific-supporting-intent")

    return score, reasons


def merge_usage(keyword: str, primary_keyword: str, intent_family: str) -> str:
    k = normalize(keyword)
    p = normalize(primary_keyword)
    if k == p:
        return "primary"
    if QUESTION_PREFIX_RE.match(k) or any(token in k for token in ["does", "do ", "can ", "should", "what is", "how to", "how long", "how fast"]):
        return "faq_support"
    if intent_family in {"dosage", "timing_guide", "safety", "cost_access", "injection_site", "reviews_results"}:
        return "h2_support"
    if word_count(k) >= 8:
        return "faq_support"
    if any(token in k for token in ["near me", "reddit", "reviews", "pictures", "photos"]):
        return "semantic_support"
    return "semantic_support"


def keyword_record(keyword: str, position: int) -> dict[str, Any]:
    intent = classify_title_intent(keyword)
    subject = canonicalize_title_subject(keyword)
    cluster_key = canonical_cluster_key(keyword, intent.intent_family)
    score, reasons = primary_keyword_score(keyword, subject, intent.intent_family)
    data = asdict(intent)
    return {
        "keyword": keyword,
        "keyword_norm": normalize(keyword),
        "input_position": position,
        "canonical_subject": subject,
        "cluster_key": cluster_key,
        "keyword_score": score,
        "score_reason": ";".join(reasons),
        **data,
    }


def choose_primary(records: list[dict[str, Any]]) -> dict[str, Any]:
    # score first, then shorter/cleaner keyword, then earlier input order for stability
    return sorted(records, key=lambda r: (-int(r["keyword_score"]), word_count(r["keyword"]), int(r["input_position"])))[0]


def build_clusters(keywords: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen_exact: set[str] = set()
    records: list[dict[str, Any]] = []
    for i, keyword in enumerate(keywords, start=1):
        norm = normalize(keyword)
        if not norm:
            continue
        if norm in seen_exact:
            # keep exact duplicate in audit by giving it the same normalized record decision later
            pass
        else:
            seen_exact.add(norm)
        records.append(keyword_record(keyword, i))

    grouped: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        grouped.setdefault(rec["cluster_key"], []).append(rec)

    audit_rows: list[dict[str, Any]] = []
    queue_rows: list[dict[str, Any]] = []
    for cluster_key, members in grouped.items():
        primary = choose_primary(members)
        primary_keyword = primary["keyword"]
        cluster_size = len(members)
        support_rows = [m for m in members if m is not primary]
        faq_keywords = [m["keyword"] for m in support_rows if merge_usage(m["keyword"], primary_keyword, m["intent_family"]) == "faq_support"]
        h2_keywords = [m["keyword"] for m in support_rows if merge_usage(m["keyword"], primary_keyword, m["intent_family"]) == "h2_support"]
        semantic_keywords = [m["keyword"] for m in support_rows if merge_usage(m["keyword"], primary_keyword, m["intent_family"]) == "semantic_support"]
        secondary_keywords = [m["keyword"] for m in support_rows]

        for member in members:
            role = "primary_article" if member is primary else "merge_support"
            usage = "primary" if member is primary else merge_usage(member["keyword"], primary_keyword, member["intent_family"])
            audit_rows.append({
                **member,
                "cluster_size": cluster_size,
                "primary_keyword": primary_keyword,
                "primary_score": primary["keyword_score"],
                "publish_role": role,
                "merge_usage": usage,
                "secondary_keywords": " | ".join(secondary_keywords[:30]),
                "faq_keywords": " | ".join(faq_keywords[:15]),
                "h2_keywords": " | ".join(h2_keywords[:15]),
                "semantic_keywords": " | ".join(semantic_keywords[:15]),
            })

        queue_rows.append({
            "primary_keyword": primary_keyword,
            "cluster_key": cluster_key,
            "canonical_subject": primary["canonical_subject"],
            "intent_family": primary["intent_family"],
            "entity_type": primary["entity_type"],
            "modifier": primary["modifier"],
            "page_type": primary["page_type"],
            "primary_score": primary["keyword_score"],
            "cluster_size": cluster_size,
            "secondary_keywords": " | ".join(secondary_keywords[:30]),
            "faq_keywords": " | ".join(faq_keywords[:15]),
            "h2_keywords": " | ".join(h2_keywords[:15]),
            "semantic_keywords": " | ".join(semantic_keywords[:15]),
            "all_cluster_keywords": " | ".join([m["keyword"] for m in members][:50]),
        })

    audit_rows.sort(key=lambda r: (r["cluster_key"], 0 if r["publish_role"] == "primary_article" else 1, int(r["input_position"])))
    queue_rows.sort(key=lambda r: (-int(r["primary_score"]), r["primary_keyword"]))
    return audit_rows, queue_rows


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cluster keywords before title generation.")
    parser.add_argument("input", help="Plain text keyword file or CSV with keyword column")
    parser.add_argument("--audit-output", default=DEFAULT_AUDIT_OUTPUT)
    parser.add_argument("--queue-output", default=DEFAULT_QUEUE_OUTPUT)
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    keywords = read_keywords(input_path)
    audit_rows, queue_rows = build_clusters(keywords)

    audit_fields = [
        "keyword", "keyword_norm", "input_position", "canonical_subject", "cluster_key", "cluster_size",
        "keyword_score", "score_reason", "primary_keyword", "primary_score", "publish_role", "merge_usage",
        "intent_family", "entity_type", "modifier", "page_type", "primary_family", "secondary_families", "reason",
        "secondary_keywords", "faq_keywords", "h2_keywords", "semantic_keywords",
    ]
    queue_fields = [
        "primary_keyword", "cluster_key", "canonical_subject", "intent_family", "entity_type", "modifier", "page_type",
        "primary_score", "cluster_size", "secondary_keywords", "faq_keywords", "h2_keywords", "semantic_keywords", "all_cluster_keywords",
    ]
    write_csv(Path(args.audit_output), audit_rows, audit_fields)
    write_csv(Path(args.queue_output), queue_rows, queue_fields)

    merge_count = len(audit_rows) - len(queue_rows)
    print(f"Wrote {len(audit_rows)} rows to {args.audit_output}")
    print(f"Wrote {len(queue_rows)} primary articles to {args.queue_output}")
    print(f"Primary articles: {len(queue_rows)} · Merge-support keywords: {merge_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
