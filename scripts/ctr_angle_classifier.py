#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CTR angle classifier for the title engine.

This layer decides *why a real searcher would click* before picking a title
pattern. V3.9 supports weight_loss, cbd, and blood intent families.
"""

from __future__ import annotations
from dataclasses import asdict, dataclass
import argparse
import re


@dataclass(frozen=True)
class CTRAngle:
    ctr_angle: str
    click_trigger: str
    risk_trigger: str
    specificity_score: int
    preferred_families: list[str]
    reason: str


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def classify_ctr_angle(keyword: str, intent_family: str = "", subject: str = "") -> CTRAngle:
    k = norm(keyword)
    intent = norm(intent_family)

    if intent == "public_figure":
        return CTRAngle("public_claim", "confirmed_vs_speculation", "misread_public_claims", 88, ["public_claim", "hidden_context", "real_story"], "public figure queries need confirmation/speculation framing")

    if intent in {"cbd_access", "blood_access", "cost_access"} or re.search(r"\b(cost|price|insurance|coverage|cover|coupon|near me|doctor|get prescribed|where to buy|legal|law|shipping|online)\b", k):
        return CTRAngle("money_access", "money_or_access_friction", "spending_or_coverage_mistake", 87, ["money_access", "before_buy", "practical_filter"], "cost/access queries click on money and denial risk")

    if intent in {"injection_site"} or re.search(r"\b(best place to inject|where to inject|injection site|site rotation)\b", k):
        return CTRAngle("before_next_dose", "before_next_action", "wrong_site_or_rotation_mistake", 90, ["before_next_dose", "hidden_risk", "practical_filter"], "injection-site searches imply an immediate next action")

    if intent in {"timing_guide", "dosage", "cbd_dosage", "blood_levels"} or re.search(r"\b(best time|when to take|how long|how fast|dose|dosage|dosing|chart|mg|ml|units|normal range|reading|levels?|a1c|glucose)\b", k):
        return CTRAngle("timeline", "first_days_or_results_window", "timeline_or_number_misread", 86, ["timeline", "hidden_risk", "practical_filter"], "timing, dosage, and marker-level queries need number/timeline context")

    if intent in {"safety", "cbd_safety", "blood_safety"} or re.search(r"\b(side effects?|safe|safety|risk|warning|danger|drug test|interaction|pregnant|symptoms?|emergency)\b", k):
        return CTRAngle("hidden_risk", "red_flag_or_normal_until_not", "underestimated_side_effect_or_warning_sign", 90, ["hidden_risk", "before_you_try", "reality_check_ctr"], "safety searches need risk-framing before reassurance")

    if intent in {"reviews_results", "cbd_reviews"} or re.search(r"\b(review|reviews|results|before and after|reddit|1 month|2 month|3 month|6 week|brand|brands)\b", k):
        return CTRAngle("looked_into", "real_results_vs_hype", "results_overread", 84, ["looked_into", "timeline", "hidden_context"], "review/result searches respond to editorial investigation framing")

    if intent in {"pills_commercial", "supplement_commercial", "cbd_product_review"} or re.search(r"\b(best|top|otc|over the counter|pills|supplement|buy|gummies|oil|tincture|capsule|cream|full spectrum|broad spectrum|isolate)\b", k):
        return CTRAngle("before_buy", "avoid_wasting_money", "marketing_or_label_trap", 89, ["before_buy", "looked_into", "hidden_risk"], "commercial queries need before-you-buy and money-risk framing")

    if intent in {"comparison", "cbd_comparison", "blood_comparison"} or " vs " in k or " versus " in k:
        return CTRAngle("comparison_decision", "which_one_fails_or_wins", "wrong_choice_tradeoff", 84, ["comparison_decision", "looked_into", "money_access"], "comparison queries need decision and tradeoff framing")

    if intent == "viral_recipe" or re.search(r"\b(recipe|trick|hack|viral|tiktok|method|drink)\b", k):
        return CTRAngle("hidden_catch", "viral_claim_vs_failure_point", "trend_hype_or_hidden_catch", 88, ["hidden_catch", "before_you_try", "reality_check_ctr"], "viral recipe searches need catch/trend/friction framing")

    if intent in {"does_it_work", "cbd_question", "blood_question"} or re.match(r"^(do|does|can|is|are|will|should|what|why)\b", k) or "help with" in k or "actually work" in k:
        return CTRAngle("reality_check_ctr", "answer_less_clean_than_expected", "oversimplified_answer", 82, ["reality_check_ctr", "hidden_context", "practical_filter"], "question queries need direct but nuanced answer framing")

    if intent == "glp1_medication":
        return CTRAngle("timeline", "first_30_days_then_hard_part", "maintenance_or_rebound_problem", 86, ["timeline", "looked_into", "hidden_context"], "GLP-1 searches click on the first month plus maintenance problem")

    if intent in {"high_protein", "smoothie_juice", "tea_drink", "herb_spice", "whole_food", "milk_dairy", "oil_fat", "probiotic", "cbd_condition", "blood_lifestyle", "blood_pressure", "blood_sugar", "blood_lipids"}:
        return CTRAngle("practical_filter", "what_helps_vs_what_sells_hype", "wellness_hype_or_backfire", 80, ["practical_filter", "hidden_catch", "before_you_try"], "natural, lifestyle, and marker queries need a practical filter hook")

    return CTRAngle("hidden_context", "part_people_miss", "generic_advice_failure", 76, ["hidden_context", "practical_filter", "reality_check_ctr"], "fallback CTR angle")


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify the CTR angle for a keyword.")
    parser.add_argument("keyword", nargs="+")
    parser.add_argument("--intent", default="")
    args = parser.parse_args()
    print(asdict(classify_ctr_angle(" ".join(args.keyword), args.intent)))


if __name__ == "__main__":
    main()
