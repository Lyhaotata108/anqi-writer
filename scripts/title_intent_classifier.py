#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Classify large keyword sets into reusable title intent families.

This is intentionally rule-based. It should scale to large SEO keyword pools
without adding one-off keyword exceptions for every term.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import re
from typing import Any


GLP1_TERMS = {
    "ozempic", "wegovy", "mounjaro", "zepbound", "semaglutide",
    "tirzepatide", "retatrutide", "glp 1", "glp-1", "glp1",
}
PILL_TERMS = {
    "weight loss pills", "diet pills", "fat burner", "phentermine", "alli",
    "orlistat", "contrave", "topiramate", "adipex", "golo", "keto pills",
}
TREND_RECIPE_TERMS = {
    "pink salt", "gelatin", "jello", "coffee method", "coffee hack", "lemon balm",
    "apple cider vinegar", "acv", "chia", "cabbage soup", "baking soda",
    "cortisol cocktail", "mounjaro recipe", "natural mounjaro", "detox water",
}
FOOD_DIET_TERMS = {
    "high protein", "oatmeal", "overnight oats", "smoothie", "juice", "green tea",
    "tea", "milk", "fruit", "pineapple", "avocado", "salad", "yogurt", "tuna",
    "almond milk", "mct oil", "olive oil", "cinnamon", "turmeric", "probiotic",
}
PUBLIC_FIGURE_TERMS = {
    "jelly roll", "nikocado", "kelly clarkson", "fat joe", "mike pompeo",
    "scott disick", "dr oz", "dr barbara", "barbara o'neill", "barbara o neill",
}


@dataclass(frozen=True)
class TitleIntent:
    intent_family: str
    entity_type: str
    modifier: str
    page_type: str
    primary_family: str
    secondary_families: list[str]
    reason: str


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def has_any(k: str, terms: set[str] | tuple[str, ...] | list[str]) -> bool:
    return any(term in k for term in terms)


def classify_title_intent(keyword: str, article_type: str = "", classification: dict[str, Any] | None = None) -> TitleIntent:
    k = norm(keyword)
    page_type = norm((classification or {}).get("page_type", ""))

    if has_any(k, PUBLIC_FIGURE_TERMS) or page_type in {"viral_truth", "public_figure", "celebrity_profile"}:
        return TitleIntent("public_figure", "person", "timeline", "public_fact_check", "public_fact_check", ["timeline", "myth_busting"], "public figure or viral transformation query")

    if " vs " in k or " versus " in k or "compare" in k or "comparison" in k:
        return TitleIntent("comparison", "mixed", "versus", "comparison_decision", "comparison", ["tradeoff", "decision"], "comparison keyword")

    if re.search(r"\b(cost|price|insurance|cover|coverage|coupon|near me|doctor|dr near me|how to get|get prescribed|medicaid|aetna|blue cross)\b", k):
        return TitleIntent("cost_access", "service_or_medication", "access", "access_guide", "cost_access", ["doctor_questions", "coverage_reality"], "cost, coverage, near-me, or access intent")

    if re.search(r"\b(dose|dosage|dosing|chart|units|mg|ml|maximum dose|starting dose|maintenance dose|increase .+ dose)\b", k):
        entity_type = "glp1_medication" if has_any(k, GLP1_TERMS) else "medication_or_supplement"
        return TitleIntent("dosage", entity_type, "dose", "dosage_guide", "dosage", ["timeline", "mistake_filter"], "dose/chart/titration intent")

    if re.search(r"\b(reviews?|results?|before and after|reddit|1 month|2 month|3 months|6 week|by week|pictures|photo)\b", k):
        entity_type = "glp1_medication" if has_any(k, GLP1_TERMS) else "product_or_method"
        return TitleIntent("reviews_results", entity_type, "results", "review_analysis", "reviews_results", ["tested", "reality_check"], "reviews, results, or before-after intent")

    if re.match(r"^(do|does|can|will|is|are|should|how effective)\b", k) or re.search(r"\b(really work|actually work|help with|good for|safe for|cause weight loss|aid in)\b", k):
        entity_type = "glp1_medication" if has_any(k, GLP1_TERMS) else "method_or_product"
        return TitleIntent("does_it_work", entity_type, "question", "question_review", "reality_check", ["evidence_vs_repeat", "tradeoff"], "question intent")

    if re.search(r"\b(best|top|top rated|recommended|list of|which .+ best)\b", k):
        entity_type = "pills" if has_any(k, PILL_TERMS) or "pills" in k else "ranked_options"
        return TitleIntent("best_top", entity_type, "best", "ranked_review", "ranked_review", ["red_flags", "comparison"], "best/top commercial research intent")

    if re.search(r"\b(side effects?|safe|safety|danger|risks?|warning|warnings|drug test|interaction)\b", k):
        entity_type = "glp1_medication" if has_any(k, GLP1_TERMS) else "method_or_product"
        return TitleIntent("safety", entity_type, "risk", "safety_guide", "safety", ["red_flags", "what_to_avoid"], "safety or side-effect intent")

    if has_any(k, GLP1_TERMS):
        return TitleIntent("glp1_medication", "glp1_medication", "weight_loss", "medication_review", "glp1_medication", ["timeline", "maintenance"], "GLP-1 medication weight-loss keyword")

    if has_any(k, TREND_RECIPE_TERMS) or re.search(r"\b(recipe|trick|hack|method|drink|water|cleanse)\b", k):
        return TitleIntent("viral_recipe", "natural_trend", "recipe", "trend_fact_check", "viral_recipe", ["tested", "myth_busting"], "viral recipe/trick/drink intent")

    if has_any(k, PILL_TERMS) or "pills" in k:
        return TitleIntent("pills_commercial", "pills", "commercial", "ranked_review", "pills_commercial", ["red_flags", "fda_filter"], "pills/commercial intent")

    if has_any(k, FOOD_DIET_TERMS):
        return TitleIntent("food_diet", "food_or_diet", "natural", "food_guide", "food_diet", ["appetite", "how_to_use"], "food, diet, or natural method intent")

    if re.search(r"\b(benefits?|what does|what is|good for)\b", k):
        return TitleIntent("benefits", "method_or_supplement", "benefits", "benefit_review", "claim_filter", ["what_works", "signal_vs_hype"], "benefits or claim-filter intent")

    return TitleIntent("general_review", "general", "general", "editorial_review", "general_review", ["claim_filter", "reality_check"], "fallback title intent")


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify title intent for one keyword.")
    parser.add_argument("keyword", nargs="+")
    parser.add_argument("--type", default="")
    args = parser.parse_args()
    print(asdict(classify_title_intent(" ".join(args.keyword), args.type)))


if __name__ == "__main__":
    main()
