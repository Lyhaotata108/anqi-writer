#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate long-form body blueprints from title intent audit output.

Body V1 turns the approved title/intent CSV into publishable article plans.
It does not write the article yet; it decides the body template, voice mode,
section plan, FAQ strategy, risk notes, and target length.
"""

from __future__ import annotations
from pathlib import Path
import argparse
import csv
import re
from typing import Any


DEFAULT_OUTPUT = "output/body_blueprint_audit_v1.csv"


LENGTH_PROFILES = {
    "expert_process_explainer": {
        "target_word_count": 2400,
        "word_count_range": "2000-2800",
        "intro_word_count": "90-140",
        "short_answer_word_count": "120-180",
        "h2_count": 7,
        "faq_count": 7,
    },
    "evidence_protocol_review": {
        "target_word_count": 2700,
        "word_count_range": "2200-3200",
        "intro_word_count": "90-140",
        "short_answer_word_count": "130-200",
        "h2_count": 8,
        "faq_count": 8,
    },
    "commercial_before_buy_review": {
        "target_word_count": 2800,
        "word_count_range": "2300-3300",
        "intro_word_count": "90-140",
        "short_answer_word_count": "130-200",
        "h2_count": 8,
        "faq_count": 8,
    },
    "viral_trend_reality_check": {
        "target_word_count": 2300,
        "word_count_range": "1900-2800",
        "intro_word_count": "80-130",
        "short_answer_word_count": "120-180",
        "h2_count": 7,
        "faq_count": 7,
    },
    "medication_evidence_review": {
        "target_word_count": 2500,
        "word_count_range": "2100-3000",
        "intro_word_count": "90-140",
        "short_answer_word_count": "130-200",
        "h2_count": 7,
        "faq_count": 7,
    },
    "public_claim_context": {
        "target_word_count": 1700,
        "word_count_range": "1400-2100",
        "intro_word_count": "70-110",
        "short_answer_word_count": "90-150",
        "h2_count": 5,
        "faq_count": 5,
    },
    "cost_access_explainer": {
        "target_word_count": 2300,
        "word_count_range": "1900-2800",
        "intro_word_count": "80-130",
        "short_answer_word_count": "120-180",
        "h2_count": 7,
        "faq_count": 7,
    },
    "comparison_decision_review": {
        "target_word_count": 2500,
        "word_count_range": "2100-3000",
        "intro_word_count": "90-140",
        "short_answer_word_count": "130-200",
        "h2_count": 7,
        "faq_count": 7,
    },
}


MEDICATION_TERMS = {
    "ozempic", "wegovy", "mounjaro", "zepbound", "semaglutide", "tirzepatide",
    "retatrutide", "metformin", "topiramate", "contrave", "phentermine",
    "alli", "orlistat", "berberine"
}

VIRAL_TERMS = {
    "pink salt", "himalayan", "apple cider vinegar", "acv", "gelatin", "jello",
    "coffee method", "coffee hack", "mounjaro recipe", "cortisol cocktail",
    "baking soda", "lemon balm", "chia"
}

COMMERCIAL_TERMS = {
    "pills", "supplement", "capsule", "gummies", "drops", "otc", "over the counter",
    "best", "buy", "reviews", "price"
}

PUBLIC_FIGURE_HINTS = {
    "jelly roll", "kelly clarkson", "fat joe", "mike pompeo", "nikocado", "scott disick", "dr oz"
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_l(text: str) -> str:
    return normalize(text).lower()


def contains_any(text: str, needles: set[str]) -> bool:
    t = norm_l(text)
    return any(n in t for n in needles)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def duplicate_keywords_by_cluster(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in rows:
        cluster = row.get("cluster_key", "")
        if not cluster:
            continue
        if row.get("cluster_status") == "duplicate":
            out.setdefault(cluster, []).append(row.get("keyword", ""))
    return out


def infer_body_template(row: dict[str, str]) -> str:
    keyword = row.get("keyword", "")
    subject = row.get("canonical_subject", "")
    intent = row.get("intent_family", "")
    angle = row.get("ctr_angle", "")
    haystack = f"{keyword} {subject} {intent} {angle}"
    h = norm_l(haystack)

    if contains_any(haystack, PUBLIC_FIGURE_HINTS) or angle == "public_claim":
        return "public_claim_context"
    if angle == "comparison_decision" or " vs " in h or " versus " in h:
        return "comparison_decision_review"
    if angle == "money_access" or any(token in h for token in ["cost", "insurance", "coverage", "near me", "how to get", "prescribed"]):
        return "cost_access_explainer"
    if angle == "before_buy" or contains_any(haystack, COMMERCIAL_TERMS):
        return "commercial_before_buy_review"
    if angle == "hidden_catch" or contains_any(haystack, VIRAL_TERMS):
        return "viral_trend_reality_check"
    if contains_any(haystack, MEDICATION_TERMS):
        return "medication_evidence_review"
    if angle in {"looked_into", "practical_filter"} or any(token in h for token in ["booster", "over 40", "best tea", "protein", "foods", "drink"]):
        return "evidence_protocol_review"
    return "expert_process_explainer"


def infer_voice_mode(template: str) -> str:
    if template == "expert_process_explainer":
        return "expert_explainer"
    if template in {"evidence_protocol_review", "comparison_decision_review"}:
        return "evidence_review"
    if template == "commercial_before_buy_review":
        return "buyer_safety_review"
    if template == "viral_trend_reality_check":
        return "trend_reality_check"
    if template == "public_claim_context":
        return "confirmed_vs_speculation"
    if template == "cost_access_explainer":
        return "practical_access_explainer"
    return "expert_explainer"


def risk_level(row: dict[str, str], template: str) -> str:
    h = norm_l(" ".join([row.get("keyword", ""), row.get("canonical_subject", ""), row.get("ctr_angle", "")]))
    if template == "public_claim_context":
        return "high"
    if contains_any(h, MEDICATION_TERMS) or any(token in h for token in ["side effect", "safe", "dosage", "dose", "prescription"]):
        return "high"
    if template in {"commercial_before_buy_review", "viral_trend_reality_check", "cost_access_explainer"}:
        return "medium"
    return "medium"


def disclaimer_required(template: str, row: dict[str, str]) -> str:
    h = norm_l(" ".join([row.get("keyword", ""), row.get("canonical_subject", "")]))
    if template in {"public_claim_context", "medication_evidence_review", "commercial_before_buy_review", "viral_trend_reality_check", "cost_access_explainer"}:
        return "yes"
    if contains_any(h, MEDICATION_TERMS):
        return "yes"
    return "yes"


def table_type(template: str, angle: str) -> str:
    if template == "commercial_before_buy_review":
        return "claim_vs_what_to_verify"
    if template == "evidence_protocol_review":
        return "intervention_comparison"
    if template == "comparison_decision_review":
        return "side_by_side_decision_table"
    if template == "viral_trend_reality_check":
        return "claim_vs_reality_table"
    if template == "medication_evidence_review":
        return "benefit_risk_fit_table"
    if template == "cost_access_explainer":
        return "cost_access_checklist_table"
    if angle == "before_buy":
        return "red_flags_table"
    return "optional_summary_table"


def protocol_type(template: str, angle: str) -> str:
    if template == "evidence_protocol_review":
        return "4_step_daily_protocol"
    if template == "viral_trend_reality_check":
        return "safer_use_protocol"
    if template == "commercial_before_buy_review":
        return "before_buying_checklist"
    if template == "medication_evidence_review":
        return "doctor_discussion_checklist"
    if template == "cost_access_explainer":
        return "coverage_call_script"
    if template == "comparison_decision_review":
        return "decision_filter"
    return "practical_next_steps"


def intro_hook(row: dict[str, str], template: str) -> str:
    subject = row.get("canonical_subject") or row.get("keyword")
    if template == "public_claim_context":
        return f"Searching {subject} usually means people want to separate visible change from rumor. Open by distinguishing confirmed information from speculation."
    if template == "commercial_before_buy_review":
        return f"Searching {subject} usually means the reader is close to spending money but does not know which claims to trust. Open with buyer risk and decision criteria."
    if template == "viral_trend_reality_check":
        return f"Searching {subject} usually means the reader saw the trend and wants to know whether there is anything real behind it. Open with the viral promise and the tradeoff."
    if template == "evidence_protocol_review":
        return f"Searching {subject} usually means the reader has seen too many conflicting recommendations. Open with what is worth comparing and what usually matters most."
    if template == "medication_evidence_review":
        return f"Searching {subject} usually means the reader wants realistic results, safety context, and what to ask a clinician. Open with a practical, non-promissory answer."
    return f"Searching {subject} usually means the reader wants a real explanation, not a generic list. Open with the problem behind the query."


def short_answer_angle(row: dict[str, str], template: str) -> str:
    angle = row.get("ctr_angle", "")
    if angle == "timeline":
        return "Summarize what usually changes first, what does not change quickly, and what tends to become difficult later."
    if angle == "before_buy":
        return "Give the buying verdict first: what to verify, what to avoid, and why the highest-click option may not be the safest option."
    if angle == "hidden_catch":
        return "State the useful kernel of truth, then explain the catch that makes the trend less simple than it looks."
    if angle == "reality_check_ctr":
        return "Give the direct answer first, then explain why the simple yes/no answer can mislead readers."
    if angle == "looked_into":
        return "Explain the review criteria: evidence quality, real-world fit, safety, cost, and what people usually miss."
    if angle == "public_claim":
        return "Separate confirmed public facts from speculation and avoid assigning methods or causes that are not verified."
    return "Give a practical verdict in plain language, including limits, risks, and next steps."


def h2_sections(template: str, row: dict[str, str]) -> list[str]:
    subject = row.get("canonical_subject") or row.get("keyword") or "This Topic"
    if template == "expert_process_explainer":
        return [
            f"What {subject} Really Means in Practice",
            "The Short Version: What To Expect First",
            "Step 1: The Initial Assessment Most People Skip",
            "Step 2: How the Plan Gets Personalized",
            "Step 3: The Behavior Change Piece That Makes It Stick",
            "Step 4: Tracking, Tweaking, and Avoiding Plateaus",
            "Questions People Usually Ask Before Taking the Next Step",
            "The Practical Next Step",
        ]
    if template == "evidence_protocol_review":
        return [
            f"Why {subject} Is More Complicated Than It Sounds",
            "The Short Version: What Actually Deserves Attention",
            "What We Compare Before Calling Anything Useful",
            "The Options That Usually Have the Strongest Practical Case",
            "The Overlooked Factor That Changes the Result",
            "What Underperforms Despite the Hype",
            "A Practical 4-Step Protocol Without the Guesswork",
            "Frequently Asked Questions",
        ]
    if template == "commercial_before_buy_review":
        return [
            f"Before You Spend Money on {subject}, Check This First",
            "The Short Version: What I’d Avoid First",
            "The Claims That Sound Strong but Need Proof",
            "Prescription, OTC, and Supplement Options: What Changes",
            "Red Flags That Matter More Than Reviews",
            "How To Compare Options Without Falling for Hype",
            "A Before-Buying Checklist",
            "Frequently Asked Questions",
        ]
    if template == "viral_trend_reality_check":
        return [
            f"Why {subject} Went Viral",
            "The Short Version: The Useful Part and the Catch",
            "What It Might Actually Help With",
            "Where the Weight-Loss Claim Starts Falling Apart",
            "The Tradeoff People Usually Miss",
            "A Safer Way To Think About the Trend",
            "Frequently Asked Questions",
            "The Practical Takeaway",
        ]
    if template == "medication_evidence_review":
        return [
            f"What {subject} Is Usually Expected To Do",
            "The Short Version: Results, Limits, and Safety Context",
            "What Usually Happens First",
            "What Gets Hard Later",
            "Who It May Fit — and Who Should Be Careful",
            "Cost, Access, and Doctor Questions",
            "Frequently Asked Questions",
            "The Next Step To Discuss With a Clinician",
        ]
    if template == "public_claim_context":
        return [
            f"What Is Actually Known About {subject}",
            "The Short Version: Confirmed Details vs. Speculation",
            "What Photos and Public Comments Can — and Cannot — Prove",
            "Why People Keep Searching This Story",
            "What Not To Copy From Celebrity Weight-Loss Stories",
            "Frequently Asked Questions",
            "The Responsible Takeaway",
        ]
    if template == "cost_access_explainer":
        return [
            f"Why {subject} Can Be Harder Than It Sounds",
            "The Short Version: What To Check First",
            "Cost, Coverage, and Access Rules That Change the Answer",
            "What To Ask Before Paying Out of Pocket",
            "How To Avoid Wasted Appointments or Bad Offers",
            "A Practical Coverage Checklist",
            "Frequently Asked Questions",
            "The Next Step",
        ]
    if template == "comparison_decision_review":
        return [
            f"The Real Difference Behind {subject}",
            "The Short Version: Which Option Fits Which Situation",
            "How the Two Options Compare on Results, Risk, and Cost",
            "Where One Looks Better on Paper",
            "Where the Other May Fit Real Life Better",
            "A Side-by-Side Decision Table",
            "Frequently Asked Questions",
            "The Practical Decision Filter",
        ]
    return [
        f"What {subject} Really Means",
        "The Short Version",
        "What People Usually Miss",
        "What To Compare First",
        "Risks, Limits, and Tradeoffs",
        "Frequently Asked Questions",
        "The Practical Takeaway",
    ]


def content_warnings(template: str, row: dict[str, str]) -> str:
    warnings = [
        "Do not invent studies, case numbers, clinical data, or personal test results.",
        "Do not promise guaranteed weight loss or fat burning.",
        "Use short paragraphs, expert editorial tone, and direct answers.",
    ]
    if template == "public_claim_context":
        warnings.append("Do not claim a public figure used a drug, surgery, diet, or method unless the input provides confirmed evidence.")
    if template in {"medication_evidence_review", "commercial_before_buy_review", "cost_access_explainer"}:
        warnings.append("Include medical disclaimer and advise clinician discussion for medications, supplements, conditions, or side effects.")
    if template == "viral_trend_reality_check":
        warnings.append("Do not frame viral recipes as detoxes, cures, or direct fat-burning shortcuts.")
    if template == "evidence_protocol_review":
        warnings.append("Use evidence-review wording unless real tracking data is provided; avoid fake 'I tracked' or 'we tested' claims.")
    return " | ".join(warnings)


def build_blueprint(row: dict[str, str], duplicates: list[str]) -> dict[str, Any]:
    template = infer_body_template(row)
    profile = LENGTH_PROFILES[template]
    status = row.get("cluster_status", "")
    publish_role = "primary_article" if status == "primary" else "merge_support"
    if publish_role == "merge_support":
        target_word_count = 0
        word_count_range = "merge into primary FAQ/H2"
    else:
        target_word_count = profile["target_word_count"]
        word_count_range = profile["word_count_range"]

    h2s = h2_sections(template, row)
    h2s = h2s[:8] + [""] * max(0, 8 - len(h2s))

    return {
        "keyword": row.get("keyword", ""),
        "cluster_status": status,
        "cluster_key": row.get("cluster_key", ""),
        "publish_role": publish_role,
        "canonical_subject": row.get("canonical_subject", ""),
        "title": row.get("title", ""),
        "intent_family": row.get("intent_family", ""),
        "ctr_angle": row.get("ctr_angle", ""),
        "title_shape": row.get("title_shape", ""),
        "body_template": template,
        "body_voice_mode": infer_voice_mode(template),
        "target_word_count": target_word_count,
        "word_count_range": word_count_range,
        "intro_word_count": profile["intro_word_count"] if publish_role == "primary_article" else "0",
        "short_answer_word_count": profile["short_answer_word_count"] if publish_role == "primary_article" else "0",
        "h2_count": profile["h2_count"] if publish_role == "primary_article" else 0,
        "faq_count": profile["faq_count"] if publish_role == "primary_article" else 0,
        "intro_hook": intro_hook(row, template),
        "short_answer_angle": short_answer_angle(row, template),
        "h2_1": h2s[0],
        "h2_2": h2s[1],
        "h2_3": h2s[2],
        "h2_4": h2s[3],
        "h2_5": h2s[4],
        "h2_6": h2s[5],
        "h2_7": h2s[6],
        "h2_8": h2s[7],
        "table_type": table_type(template, row.get("ctr_angle", "")) if publish_role == "primary_article" else "",
        "protocol_type": protocol_type(template, row.get("ctr_angle", "")) if publish_role == "primary_article" else "",
        "faq_strategy": "Use duplicate keywords from same cluster first, then add People Also Ask style questions." if publish_role == "primary_article" else "Merge this keyword into the primary article FAQ/H2.",
        "duplicate_keywords": " | ".join(duplicates[:12]),
        "risk_level": risk_level(row, template),
        "disclaimer_required": disclaimer_required(template, row),
        "content_warnings": content_warnings(template, row),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "keyword", "cluster_status", "cluster_key", "publish_role", "canonical_subject", "title",
        "intent_family", "ctr_angle", "title_shape", "body_template", "body_voice_mode",
        "target_word_count", "word_count_range", "intro_word_count", "short_answer_word_count",
        "h2_count", "faq_count", "intro_hook", "short_answer_angle",
        "h2_1", "h2_2", "h2_3", "h2_4", "h2_5", "h2_6", "h2_7", "h2_8",
        "table_type", "protocol_type", "faq_strategy", "duplicate_keywords",
        "risk_level", "disclaimer_required", "content_warnings",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate long-form body blueprints from a title audit CSV.")
    parser.add_argument("input", help="Input title_intent_audit CSV")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    source_rows = read_csv(input_path)
    duplicates = duplicate_keywords_by_cluster(source_rows)
    blueprints = [build_blueprint(row, duplicates.get(row.get("cluster_key", ""), [])) for row in source_rows]
    output_path = Path(args.output)
    write_csv(output_path, blueprints)

    primary_count = sum(1 for row in blueprints if row["publish_role"] == "primary_article")
    merge_count = len(blueprints) - primary_count
    avg_words = int(sum(int(row["target_word_count"] or 0) for row in blueprints) / max(1, primary_count))
    templates: dict[str, int] = {}
    for row in blueprints:
        templates[row["body_template"]] = templates.get(row["body_template"], 0) + 1
    template_summary = ", ".join(f"{k}:{v}" for k, v in sorted(templates.items()))

    print(f"Wrote {len(blueprints)} rows to {output_path}")
    print(f"Primary articles: {primary_count} · Merge-support rows: {merge_count}")
    print(f"Average target words for primary articles: {avg_words}")
    print(f"Templates: {template_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
