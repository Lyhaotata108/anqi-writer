#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate long-form body blueprints from title intent audit output.

Body V1.2 supports three categories: weight_loss, cbd, and blood.
Clustered FAQ/H2/semantic keywords become body coverage instead of separate
zero-word article rows.
"""

from __future__ import annotations
from pathlib import Path
import argparse
import csv
import re
from typing import Any

DEFAULT_OUTPUT = "output/body_blueprint_audit_v1.csv"

LENGTH_PROFILES = {
    "expert_process_explainer": (2400, "2000-2800", "90-140", "120-180", 7, 7),
    "evidence_protocol_review": (2700, "2200-3200", "90-140", "130-200", 8, 8),
    "commercial_before_buy_review": (2800, "2300-3300", "90-140", "130-200", 8, 8),
    "viral_trend_reality_check": (2300, "1900-2800", "80-130", "120-180", 7, 7),
    "medication_evidence_review": (2500, "2100-3000", "90-140", "130-200", 7, 7),
    "public_claim_context": (1700, "1400-2100", "70-110", "90-150", 5, 5),
    "cost_access_explainer": (2300, "1900-2800", "80-130", "120-180", 7, 7),
    "comparison_decision_review": (2500, "2100-3000", "90-140", "130-200", 7, 7),
    "cbd_buyer_review": (2600, "2200-3100", "90-140", "130-200", 8, 8),
    "cbd_safety_explainer": (2400, "2000-2900", "90-140", "130-200", 7, 7),
    "cbd_condition_review": (2500, "2100-3000", "90-140", "130-200", 7, 7),
    "blood_marker_explainer": (2600, "2200-3200", "90-140", "130-200", 8, 8),
    "blood_lifestyle_protocol": (2700, "2300-3300", "90-140", "130-200", 8, 8),
    "blood_safety_explainer": (2300, "1900-2800", "80-130", "120-180", 7, 7),
}

MEDICATION_TERMS = {"ozempic", "wegovy", "mounjaro", "zepbound", "semaglutide", "tirzepatide", "retatrutide", "metformin", "topiramate", "contrave", "phentermine", "alli", "orlistat", "berberine"}
VIRAL_TERMS = {"pink salt", "himalayan", "apple cider vinegar", "acv", "gelatin", "jello", "coffee method", "coffee hack", "mounjaro recipe", "cortisol cocktail", "baking soda", "lemon balm", "chia"}
COMMERCIAL_TERMS = {"pills", "supplement", "capsule", "gummies", "drops", "otc", "over the counter", "best", "buy", "reviews", "price"}
PUBLIC_FIGURE_HINTS = {"jelly roll", "kelly clarkson", "fat joe", "mike pompeo", "nikocado", "scott disick", "dr oz"}


def clean_category(value: str) -> str:
    raw = str(value or "weight_loss").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"weight", "weightloss", "weight_loss"}:
        return "weight_loss"
    if raw in {"cbd", "hemp"}:
        return "cbd"
    if raw in {"blood", "blood_health", "blood_sugar", "blood_pressure"}:
        return "blood"
    return "weight_loss"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_l(text: str) -> str:
    return normalize(text).lower()


def split_pipe(text: str) -> list[str]:
    return [part.strip() for part in str(text or "").split("|") if part.strip()]


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
        if cluster and row.get("cluster_status") == "duplicate":
            out.setdefault(cluster, []).append(row.get("keyword", ""))
    return out


def clustered_keywords(row: dict[str, str], fallback_duplicates: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    secondary = split_pipe(row.get("secondary_keywords")) or fallback_duplicates
    faq = split_pipe(row.get("faq_keywords"))
    h2 = split_pipe(row.get("h2_keywords"))
    semantic = split_pipe(row.get("semantic_keywords"))
    if not faq:
        faq = [kw for kw in secondary if re.match(r"^(what|why|how|when|where|does|do|can|should|is|are)\b", kw, flags=re.I)][:8]
    if not h2:
        h2 = [kw for kw in secondary if any(t in kw.lower() for t in ["cost", "dose", "side effect", "how long", "where", "best time", "results", "reviews", "normal", "level", "legal"] )][:8]
    if not semantic:
        semantic = [kw for kw in secondary if kw not in faq and kw not in h2][:12]
    return secondary, faq, h2, semantic


def infer_body_template(row: dict[str, str]) -> str:
    category = clean_category(row.get("category", "weight_loss"))
    intent = row.get("intent_family", "")
    h = norm_l(" ".join([row.get("keyword", ""), row.get("canonical_subject", ""), intent, row.get("ctr_angle", "")]))
    angle = row.get("ctr_angle", "")

    if category == "cbd":
        if intent in {"cbd_safety", "cbd_dosage", "cbd_access"} or angle in {"hidden_risk", "timeline", "money_access"}:
            return "cbd_safety_explainer"
        if intent in {"cbd_condition", "cbd_question"}:
            return "cbd_condition_review"
        return "cbd_buyer_review"

    if category == "blood":
        if intent in {"blood_safety", "blood_access"} or angle == "hidden_risk":
            return "blood_safety_explainer"
        if intent in {"blood_lifestyle", "blood_question"} or any(t in h for t in ["lower", "reduce", "diet", "foods", "exercise", "naturally"]):
            return "blood_lifestyle_protocol"
        return "blood_marker_explainer"

    if contains_any(h, PUBLIC_FIGURE_HINTS) or angle == "public_claim":
        return "public_claim_context"
    if angle == "comparison_decision" or " vs " in h or " versus " in h:
        return "comparison_decision_review"
    if angle == "money_access" or any(token in h for token in ["cost", "insurance", "coverage", "near me", "how to get", "prescribed"]):
        return "cost_access_explainer"
    if angle == "before_buy" or contains_any(h, COMMERCIAL_TERMS):
        return "commercial_before_buy_review"
    if angle == "hidden_catch" or contains_any(h, VIRAL_TERMS):
        return "viral_trend_reality_check"
    if contains_any(h, MEDICATION_TERMS):
        return "medication_evidence_review"
    if angle in {"looked_into", "practical_filter"} or any(token in h for token in ["booster", "over 40", "best tea", "protein", "foods", "drink"]):
        return "evidence_protocol_review"
    return "expert_process_explainer"


def infer_voice_mode(template: str) -> str:
    return {
        "expert_process_explainer": "expert_explainer",
        "evidence_protocol_review": "evidence_review",
        "commercial_before_buy_review": "buyer_safety_review",
        "viral_trend_reality_check": "trend_reality_check",
        "medication_evidence_review": "medical_evidence_review",
        "public_claim_context": "confirmed_vs_speculation",
        "cost_access_explainer": "practical_access_explainer",
        "comparison_decision_review": "evidence_comparison_review",
        "cbd_buyer_review": "cbd_buyer_safety_review",
        "cbd_safety_explainer": "cbd_medical_safety_explainer",
        "cbd_condition_review": "cbd_claim_filter_review",
        "blood_marker_explainer": "blood_marker_explainer",
        "blood_lifestyle_protocol": "blood_lifestyle_protocol",
        "blood_safety_explainer": "blood_safety_explainer",
    }.get(template, "expert_explainer")


def table_type(template: str) -> str:
    return {
        "commercial_before_buy_review": "claim_vs_what_to_verify",
        "evidence_protocol_review": "intervention_comparison",
        "comparison_decision_review": "side_by_side_decision_table",
        "viral_trend_reality_check": "claim_vs_reality_table",
        "medication_evidence_review": "benefit_risk_fit_table",
        "cost_access_explainer": "cost_access_checklist_table",
        "public_claim_context": "confirmed_vs_speculation_table",
        "cbd_buyer_review": "cbd_product_claim_vs_verification_table",
        "cbd_safety_explainer": "cbd_safety_interaction_table",
        "cbd_condition_review": "cbd_evidence_vs_claim_table",
        "blood_marker_explainer": "blood_marker_range_context_table",
        "blood_lifestyle_protocol": "lifestyle_intervention_comparison_table",
        "blood_safety_explainer": "warning_signs_table",
    }.get(template, "optional_summary_table")


def protocol_type(template: str) -> str:
    return {
        "evidence_protocol_review": "4_step_daily_protocol",
        "viral_trend_reality_check": "safer_use_protocol",
        "commercial_before_buy_review": "before_buying_checklist",
        "medication_evidence_review": "doctor_discussion_checklist",
        "cost_access_explainer": "coverage_call_script",
        "comparison_decision_review": "decision_filter",
        "public_claim_context": "responsible_context_filter",
        "cbd_buyer_review": "cbd_before_buying_checklist",
        "cbd_safety_explainer": "clinician_and_label_checklist",
        "cbd_condition_review": "evidence_and_expectation_filter",
        "blood_marker_explainer": "numbers_to_discuss_with_clinician",
        "blood_lifestyle_protocol": "4_step_monitoring_protocol",
        "blood_safety_explainer": "when_to_seek_medical_help_filter",
    }.get(template, "practical_next_steps")


def h2_sections(template: str, row: dict[str, str]) -> list[str]:
    subject = row.get("canonical_subject") or row.get("keyword") or "This Topic"
    sections = {
        "cbd_buyer_review": [f"Before You Buy {subject}, Check This First", "The Short Version: What Is Worth Verifying", "Full-Spectrum, Broad-Spectrum, and Isolate: What Changes", "The Label Details That Matter More Than Reviews", "Red Flags Around Testing, Potency, and Claims", "How To Compare CBD Options Without Falling for Hype", "Frequently Asked Questions", "The Practical Buying Checklist"],
        "cbd_safety_explainer": [f"What To Know Before Using {subject}", "The Short Version: Benefits, Limits, and Safety Context", "Dosage, Timing, and Why the Number Can Mislead", "Side Effects and Interactions To Check First", "Drug Testing, Legal, and Product Quality Questions", "Who Should Be More Careful", "Frequently Asked Questions", "The Clinician Discussion Checklist"],
        "cbd_condition_review": [f"Why People Search {subject}", "The Short Version: What the Claim Can and Cannot Prove", "What Evidence Usually Looks At", "Where Real-World Results Get Messy", "Safety, Interactions, and Expectation Setting", "How To Compare CBD With Other Options", "Frequently Asked Questions", "The Practical Takeaway"],
        "blood_marker_explainer": [f"What {subject} Really Tells You", "The Short Version: What the Number Can and Cannot Mean", "Normal Ranges, Context, and Why One Reading Is Not Enough", "What Can Push the Number Up or Down", "When the Pattern Matters More Than a Single Result", "What To Ask Your Clinician", "Frequently Asked Questions", "The Practical Monitoring Plan"],
        "blood_lifestyle_protocol": [f"Why {subject} Is Harder Than a Simple Tip", "The Short Version: What Usually Moves the Needle", "Food, Activity, Sleep, and Medication Context", "The Changes That Tend To Help Most", "What Usually Underperforms Despite the Hype", "A Practical 4-Step Monitoring Protocol", "Frequently Asked Questions", "The Next Step"],
        "blood_safety_explainer": [f"When {subject} Needs More Caution", "The Short Version: What To Watch First", "Warning Signs That Should Not Be Ignored", "What Can Make the Reading Look Worse or Better", "Home Monitoring vs. Medical Evaluation", "Questions To Ask Before Waiting It Out", "Frequently Asked Questions", "The Responsible Takeaway"],
        "expert_process_explainer": [f"What {subject} Really Means in Practice", "The Short Version: What To Expect First", "Step 1: The Initial Assessment Most People Skip", "Step 2: How the Plan Gets Personalized", "Step 3: The Behavior Change Piece That Makes It Stick", "Step 4: Tracking, Tweaking, and Avoiding Plateaus", "Questions People Usually Ask Before Taking the Next Step", "The Practical Next Step"],
        "evidence_protocol_review": [f"Why {subject} Is More Complicated Than It Sounds", "The Short Version: What Actually Deserves Attention", "What We Compare Before Calling Anything Useful", "The Options That Usually Have the Strongest Practical Case", "The Overlooked Factor That Changes the Result", "What Underperforms Despite the Hype", "A Practical 4-Step Protocol Without the Guesswork", "Frequently Asked Questions"],
        "commercial_before_buy_review": [f"Before You Spend Money on {subject}, Check This First", "The Short Version: What I’d Avoid First", "The Claims That Sound Strong but Need Proof", "Prescription, OTC, and Supplement Options: What Changes", "Red Flags That Matter More Than Reviews", "How To Compare Options Without Falling for Hype", "A Before-Buying Checklist", "Frequently Asked Questions"],
        "viral_trend_reality_check": [f"Why {subject} Went Viral", "The Short Version: The Useful Part and the Catch", "What It Might Actually Help With", "Where the Weight-Loss Claim Starts Falling Apart", "The Tradeoff People Usually Miss", "A Safer Way To Think About the Trend", "Frequently Asked Questions", "The Practical Takeaway"],
        "medication_evidence_review": [f"What {subject} Is Usually Expected To Do", "The Short Version: Results, Limits, and Safety Context", "What Usually Happens First", "What Gets Hard Later", "Who It May Fit — and Who Should Be Careful", "Cost, Access, and Doctor Questions", "Frequently Asked Questions", "The Next Step To Discuss With a Clinician"],
        "public_claim_context": [f"What Is Actually Known About {subject}", "The Short Version: Confirmed Details vs. Speculation", "What Photos and Public Comments Can — and Cannot — Prove", "Why People Keep Searching This Story", "What Not To Copy From Celebrity Weight-Loss Stories", "Frequently Asked Questions", "The Responsible Takeaway"],
        "cost_access_explainer": [f"Why {subject} Can Be Harder Than It Sounds", "The Short Version: What To Check First", "Cost, Coverage, and Access Rules That Change the Answer", "What To Ask Before Paying Out of Pocket", "How To Avoid Wasted Appointments or Bad Offers", "A Practical Coverage Checklist", "Frequently Asked Questions", "The Next Step"],
        "comparison_decision_review": [f"The Real Difference Behind {subject}", "The Short Version: Which Option Fits Which Situation", "How the Two Options Compare on Results, Risk, and Cost", "Where One Looks Better on Paper", "Where the Other May Fit Real Life Better", "A Side-by-Side Decision Table", "Frequently Asked Questions", "The Practical Decision Filter"],
    }.get(template, [f"What {subject} Really Means", "The Short Version", "What People Usually Miss", "Risks, Limits, and Tradeoffs", "Frequently Asked Questions", "The Practical Takeaway"])
    return sections[:8] + [""] * max(0, 8 - len(sections))


def intro_hook(row: dict[str, str], template: str) -> str:
    subject = row.get("canonical_subject") or row.get("keyword")
    category = clean_category(row.get("category", "weight_loss"))
    if category == "cbd":
        return f"Searching {subject} usually means the reader wants a practical answer without product hype. Open with what can be verified, what is uncertain, and what safety checks matter."
    if category == "blood":
        return f"Searching {subject} usually means the reader is trying to interpret a health number or reduce risk. Open with context, pattern, and when to seek medical guidance."
    if template == "public_claim_context":
        return f"Searching {subject} usually means people want to separate visible change from rumor. Open by distinguishing confirmed information from speculation."
    if template == "commercial_before_buy_review":
        return f"Searching {subject} usually means the reader is close to spending money but does not know which claims to trust. Open with buyer risk and decision criteria."
    if template == "viral_trend_reality_check":
        return f"Searching {subject} usually means the reader saw the trend and wants to know whether there is anything real behind it. Open with the viral promise and the tradeoff."
    return f"Searching {subject} usually means the reader wants a real answer, not a generic list. Open with the problem behind the query."


def short_answer_angle(row: dict[str, str]) -> str:
    category = clean_category(row.get("category", "weight_loss"))
    angle = row.get("ctr_angle", "")
    if category == "cbd":
        return "Give a non-promissory CBD verdict first: what may be plausible, what is not proven, what safety/product-quality checks matter, and when to ask a clinician."
    if category == "blood":
        return "Give a health-number verdict first: what the reading can mean, what patterns matter, and when medical guidance is more important than internet advice."
    return {
        "timeline": "Summarize what usually changes first, what does not change quickly, and what becomes difficult later.",
        "before_buy": "Give the buying verdict first: what to verify, what to avoid, and why reviews are not enough.",
        "hidden_catch": "State the useful kernel of truth, then explain the catch that makes the trend less simple than it looks.",
        "reality_check_ctr": "Give the direct answer first, then explain why the simple yes/no answer can mislead readers.",
        "looked_into": "Explain the review criteria: evidence quality, real-world fit, safety, cost, and what people usually miss.",
        "public_claim": "Separate confirmed public facts from speculation and avoid assigning unverified causes.",
    }.get(angle, "Give a practical verdict in plain language, including limits, risks, and next steps.")


def risk_level(row: dict[str, str], template: str) -> str:
    category = clean_category(row.get("category", "weight_loss"))
    h = norm_l(" ".join([row.get("keyword", ""), row.get("canonical_subject", ""), row.get("ctr_angle", "")]))
    if category in {"cbd", "blood"}:
        return "high"
    if template == "public_claim_context" or contains_any(h, MEDICATION_TERMS) or any(t in h for t in ["side effect", "safe", "dosage", "dose", "prescription"]):
        return "high"
    return "medium"


def content_warnings(category: str, template: str) -> str:
    warnings = ["Do not invent studies, case numbers, clinical data, or personal test results.", "Do not promise guaranteed outcomes.", "Use short paragraphs, expert editorial tone, and direct answers."]
    if category == "cbd":
        warnings.append("CBD content must avoid cure/treat claims, flag interactions/drug-testing/product-quality issues, and advise clinician guidance for medical conditions or medications.")
    if category == "blood":
        warnings.append("Blood-health content must avoid diagnosis, explain that readings need clinical context, and flag urgent symptoms or very abnormal values as medical-care situations.")
    if template == "public_claim_context":
        warnings.append("Do not claim a public figure used a drug, surgery, diet, or method unless confirmed evidence is provided.")
    if template in {"medication_evidence_review", "commercial_before_buy_review", "cost_access_explainer"}:
        warnings.append("Include medical disclaimer and advise clinician discussion for medications, supplements, conditions, or side effects.")
    if template == "viral_trend_reality_check":
        warnings.append("Do not frame viral recipes as detoxes, cures, or direct fat-burning shortcuts.")
    return " | ".join(warnings)


def build_blueprint(row: dict[str, str], fallback_duplicates: list[str]) -> dict[str, Any]:
    category = clean_category(row.get("category", "weight_loss"))
    template = infer_body_template(row)
    target, word_range, intro_words, short_words, h2_count, faq_count = LENGTH_PROFILES[template]
    secondary, faq, h2_keywords, semantic = clustered_keywords(row, fallback_duplicates)
    h2s = h2_sections(template, row)
    return {
        "category": category,
        "keyword": row.get("keyword", ""),
        "cluster_status": row.get("cluster_status", "primary"),
        "cluster_key": row.get("cluster_key", ""),
        "publish_role": "primary_article",
        "canonical_subject": row.get("canonical_subject", ""),
        "title": row.get("title", ""),
        "intent_family": row.get("intent_family", ""),
        "ctr_angle": row.get("ctr_angle", ""),
        "title_shape": row.get("title_shape", ""),
        "body_template": template,
        "body_voice_mode": infer_voice_mode(template),
        "target_word_count": target,
        "word_count_range": word_range,
        "intro_word_count": intro_words,
        "short_answer_word_count": short_words,
        "h2_count": h2_count,
        "faq_count": faq_count,
        "intro_hook": intro_hook(row, template),
        "short_answer_angle": short_answer_angle(row),
        "h2_1": h2s[0], "h2_2": h2s[1], "h2_3": h2s[2], "h2_4": h2s[3],
        "h2_5": h2s[4], "h2_6": h2s[5], "h2_7": h2s[6], "h2_8": h2s[7],
        "table_type": table_type(template),
        "protocol_type": protocol_type(template),
        "faq_strategy": "Use clustered faq_keywords first, then add People Also Ask style questions if fewer than target FAQ count.",
        "duplicate_keywords": " | ".join(secondary[:30]),
        "faq_keywords": " | ".join(faq[:15]),
        "h2_keywords": " | ".join(h2_keywords[:15]),
        "semantic_keywords": " | ".join(semantic[:15]),
        "risk_level": risk_level(row, template),
        "disclaimer_required": "yes",
        "content_warnings": content_warnings(category, template),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["category", "keyword", "cluster_status", "cluster_key", "publish_role", "canonical_subject", "title", "intent_family", "ctr_angle", "title_shape", "body_template", "body_voice_mode", "target_word_count", "word_count_range", "intro_word_count", "short_answer_word_count", "h2_count", "faq_count", "intro_hook", "short_answer_angle", "h2_1", "h2_2", "h2_3", "h2_4", "h2_5", "h2_6", "h2_7", "h2_8", "table_type", "protocol_type", "faq_strategy", "duplicate_keywords", "faq_keywords", "h2_keywords", "semantic_keywords", "risk_level", "disclaimer_required", "content_warnings"]
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
    source_rows = [row for row in read_csv(input_path) if row.get("cluster_status", "primary") == "primary"]
    fallback = duplicate_keywords_by_cluster(source_rows)
    blueprints = [build_blueprint(row, fallback.get(row.get("cluster_key", ""), [])) for row in source_rows]
    output_path = Path(args.output)
    write_csv(output_path, blueprints)
    avg_words = int(sum(int(row["target_word_count"] or 0) for row in blueprints) / max(1, len(blueprints)))
    templates: dict[str, int] = {}
    categories: dict[str, int] = {}
    for row in blueprints:
        templates[row["body_template"]] = templates.get(row["body_template"], 0) + 1
        categories[row["category"]] = categories.get(row["category"], 0) + 1
    template_summary = ", ".join(f"{k}:{v}" for k, v in sorted(templates.items()))
    category_summary = ", ".join(f"{k}:{v}" for k, v in sorted(categories.items()))
    print(f"Wrote {len(blueprints)} primary article blueprints to {output_path}")
    print(f"Categories: {category_summary}")
    print(f"Average target words: {avg_words}")
    print(f"Templates: {template_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
