#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CTR-first SEO title engine.

V3.3 keeps the approved CTR style and adds composable fragment variants so the
same keyword pool can scale without repeating the same fixed title frame.
"""

from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime
import argparse
import hashlib
import re
from typing import Any

from canonical_subject import canonical_cluster_key, canonicalize_title_question, canonicalize_title_subject, title_case
from ctr_angle_classifier import CTRAngle, classify_ctr_angle
from ctr_title_pattern_bank import CTR_STRONG_TOKENS, CTR_TITLE_PATTERNS, CTR_WEAK_PHRASES
from title_intent_classifier import TitleIntent, classify_title_intent
from title_pattern_bank import FAMILY_PRIORITY, TITLE_PATTERNS
from title_scorer import TitleCandidate, score_title
from title_variant_generator import generate_fragment_variants


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
    technical_score: int = 0
    ctr_score: int = 0
    score: int = 0
    ctr_angle: str = ""
    click_trigger: str = ""
    risk_trigger: str = ""
    specificity_score: int = 0


@dataclass(frozen=True)
class CTRTitleCandidate:
    title: str
    family: str
    pattern_id: str
    technical_score: int
    ctr_score: int
    total_score: int
    reasons: list[str]
    ctr_angle: CTRAngle


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_l(text: str) -> str:
    return normalize(text).lower()


def title_case_keyword(keyword: str) -> str:
    return title_case(keyword)


def trim_title(title: str, max_len: int = 118) -> str:
    title = normalize(title).rstrip(" .")
    if len(title) <= max_len:
        return title
    return title[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:-&")


def rotation_index(keyword: str, family: str, size: int) -> int:
    if size <= 0:
        return 0
    digest = hashlib.md5(f"{keyword.lower()}::{family}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def title_context(keyword: str, year: int) -> dict[str, str | int]:
    subject = canonicalize_title_subject(keyword)
    question = canonicalize_title_question(keyword)
    return {
        "kw": subject,
        "subject": subject,
        "question": question.rstrip("?"),
        "raw_kw": title_case(keyword),
        "year": year,
    }


def candidate_families(intent: TitleIntent) -> list[str]:
    families = FAMILY_PRIORITY.get(intent.intent_family, [intent.primary_family])
    merged = []
    for family in [intent.primary_family, *families, *intent.secondary_families, "general_review"]:
        if family in TITLE_PATTERNS and family not in merged:
            merged.append(family)
    return merged


def iter_rotated_patterns(keyword: str, family: str, bank: dict[str, list[str]]) -> list[tuple[int, str]]:
    patterns = bank.get(family, [])
    if not patterns:
        return []
    start = rotation_index(keyword, family, len(patterns))
    return [((start + offset) % len(patterns), patterns[(start + offset) % len(patterns)]) for offset in range(len(patterns))]


def score_ctr_title(title: str, keyword: str, subject: str, angle: CTRAngle, technical_score: int) -> tuple[int, list[str]]:
    title_l = norm_l(title)
    keyword_l = norm_l(keyword)
    subject_l = norm_l(subject)
    score = 0
    reasons: list[str] = []

    if title_l.startswith(subject_l.split(":")[0]) or subject_l[:18] in title_l[:42]:
        score += 14
        reasons.append("subject-front-loaded")

    if 58 <= len(title) <= 112:
        score += 12
        reasons.append("ctr-length")

    strong_hits = [token for token in CTR_STRONG_TOKENS if token in title_l]
    if strong_hits:
        score += min(28, 12 + 4 * len(strong_hits))
        reasons.append("strong-ctr-trigger:" + ",".join(strong_hits[:3]))

    conflict_tokens = ["but", "until", "miss", "fails", "avoid", "hidden", "red flag", "wrong", "less clean", "speculation", "don’t prove", "don't prove", "hard later", "tradeoff", "plateau"]
    if any(token in title_l for token in conflict_tokens):
        score += 16
        reasons.append("curiosity-conflict")

    specificity_tokens = [str(datetime.now().year), "30 days", "first month", "dose", "insurance", "money", "cost", "spending", "photos", "tiktok", "injection", "side effect", "week", "routine"]
    if any(token in title_l for token in specificity_tokens):
        score += 12
        reasons.append("specific-detail")

    if re.search(r"\b(i looked|i checked|i compared|i’d|i'd|people|users|fans|tiktok)\b", title_l):
        score += 10
        reasons.append("editorial-or-user-frame")

    if "?" in title or "—" in title or ":" in title:
        score += 8
        reasons.append("click-structure")

    if angle.specificity_score >= 85:
        score += 8
        reasons.append("angle-specificity")

    if technical_score >= 60:
        score += 8
        reasons.append("technical-pass")

    weak_hits = [phrase for phrase in CTR_WEAK_PHRASES if phrase in title_l]
    if weak_hits and not strong_hits:
        score -= 24
        reasons.append("weak-editorial-phrase:" + ",".join(weak_hits[:2]))

    if title_l == keyword_l or title_l == subject_l:
        score -= 50
        reasons.append("raw-keyword-title")

    return max(0, min(100, score)), reasons


def append_ctr_candidate(
    out: list[CTRTitleCandidate],
    title: str,
    family: str,
    pattern_id: str,
    keyword: str,
    subject: str,
    angle: CTRAngle,
    existing_titles: list[str] | None,
    existing_patterns: set[str] | None,
    source_reason: str,
    technical_weight: float,
    ctr_weight: float,
    base_adjustment: int = 0,
) -> None:
    title = trim_title(title)
    tech = score_title(title, subject, family, pattern_id, existing_titles, existing_patterns)
    ctr_score, ctr_reasons = score_ctr_title(title, keyword, subject, angle, tech.score)
    total = int((tech.score * technical_weight) + (ctr_score * ctr_weight)) + base_adjustment
    reasons = list(tech.reasons) + ctr_reasons + [source_reason, f"ctr-angle:{angle.ctr_angle}"]
    out.append(CTRTitleCandidate(title, family, pattern_id, tech.score, ctr_score, total, reasons, angle))


def generate_ctr_title_candidates(
    keyword: str,
    article_type: str = "",
    classification: dict[str, Any] | None = None,
    year: int | None = None,
    existing_titles: list[str] | None = None,
    existing_patterns: set[str] | None = None,
) -> list[CTRTitleCandidate]:
    year = year or datetime.now().year
    intent = classify_title_intent(keyword, article_type, classification)
    ctx = title_context(keyword, year)
    subject = str(ctx["kw"])
    angle = classify_ctr_angle(keyword, intent.intent_family, subject)
    candidates: list[CTRTitleCandidate] = []

    for family, pattern_id, title in generate_fragment_variants(keyword, angle.ctr_angle, ctx, limit=64):
        append_ctr_candidate(
            candidates, title, family, pattern_id, keyword, subject, angle,
            existing_titles, existing_patterns, "fragment-grammar", 0.22, 0.72, 4,
        )

    for family in [*angle.preferred_families, "hidden_context", "practical_filter"]:
        for original_index, pattern in iter_rotated_patterns(keyword, family, CTR_TITLE_PATTERNS):
            pattern_id = f"ctr_{family}_{original_index + 1:02d}"
            title = pattern.format(**ctx)
            append_ctr_candidate(
                candidates, title, family, pattern_id, keyword, subject, angle,
                existing_titles, existing_patterns, "fixed-ctr-template", 0.28, 0.66, 0,
            )

    for family in candidate_families(intent):
        for original_index, pattern in iter_rotated_patterns(keyword, family, TITLE_PATTERNS)[:3]:
            pattern_id = f"{family}_{original_index + 1:02d}"
            title = pattern.format(**ctx)
            append_ctr_candidate(
                candidates, title, family, pattern_id, keyword, subject, angle,
                existing_titles, existing_patterns, "fallback-v2-pattern", 0.20, 0.48, -12,
            )

    return sorted(candidates, key=lambda item: item.total_score, reverse=True)


def choose_title_pattern(keyword: str, article_type: str, classification: dict | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> TitleDecision:
    year = year or datetime.now().year
    intent = classify_title_intent(keyword, article_type, classification)
    ctx = title_context(keyword, year)
    candidates = generate_ctr_title_candidates(keyword, article_type, classification, year, existing_titles, existing_patterns)
    if not candidates:
        raise ValueError("No title candidates generated")
    best = candidates[0]
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
        technical_score=best.technical_score,
        ctr_score=best.ctr_score,
        score=best.total_score,
        ctr_angle=best.ctr_angle.ctr_angle,
        click_trigger=best.ctr_angle.click_trigger,
        risk_trigger=best.ctr_angle.risk_trigger,
        specificity_score=best.ctr_angle.specificity_score,
    )


def generate_title_candidates(keyword: str, article_type: str = "", classification: dict[str, Any] | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> list[TitleCandidate]:
    """Backward-compatible technical candidate API."""
    year = year or datetime.now().year
    intent = classify_title_intent(keyword, article_type, classification)
    ctx = title_context(keyword, year)
    candidates = []
    for family in candidate_families(intent):
        for original_index, pattern in iter_rotated_patterns(keyword, family, TITLE_PATTERNS):
            pattern_id = f"{family}_{original_index + 1:02d}"
            title = trim_title(pattern.format(**ctx))
            candidates.append(score_title(title, str(ctx["kw"]), family, pattern_id, existing_titles, existing_patterns))
    return candidates


def generate_seo_title(keyword: str, article_type: str = "", classification: dict | None = None, original_title: str | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> str:
    return choose_title_pattern(keyword, article_type, classification, year, existing_titles, existing_patterns).title


def generate_title_metadata(keyword: str, article_type: str = "", classification: dict | None = None, year: int | None = None, existing_titles: list[str] | None = None, existing_patterns: set[str] | None = None) -> dict[str, Any]:
    return asdict(choose_title_pattern(keyword, article_type, classification, year, existing_titles, existing_patterns))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a CTR-first SEO title.")
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
