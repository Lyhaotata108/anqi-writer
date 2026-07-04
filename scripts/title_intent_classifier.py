#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Classify large keyword sets into reusable title intent families.

Rule-based by design. The goal is not to memorize single keywords, but to map
large SEO keyword pools into stable title families: GLP-1 medication, dosage,
reviews/results, viral recipe, food/drink subtypes, pills, safety, access,
comparison, public figure, and claim-filter queries.
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
    "pills for weight loss", "weight loss medication pills", "water pills",
}
SUPPLEMENT_TERMS = {
    "berberine", "moringa", "fiber pills", "cortisol supplements",
    "green tea extract", "black seed oil", "castor oil", "lipase inhibitors",
}
TREND_RECIPE_TERMS = {
    "pink salt", "gelatin", "jello", "coffee method", "coffee hack", "lemon balm",
    "apple cider vinegar", "acv", "bragg", "braggs", "chia", "cabbage soup",
    "baking soda", "cortisol cocktail", "mounjaro recipe", "natural mounjaro",
    "homemade mounjaro", "japanese mounjaro", "brazilian mounjaro", "detox water",
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


def food_subfamily(k: str) -> tuple[str, str] | None:
    if "high protein" in k or "protein" in k and re.search(r"\b(food|foods|meal|meals|recipe|recipes|snack|snacks|breakfast|shake|drink)\b", k):
        return "high_protein", "high-protein food intent"
    if "smoothie" in k or "shake" in k:
        return "smoothie_juice", "smoothie or shake recipe intent"
    if "juice" in k or "cleanse" in k:
        return "smoothie_juice", "juice or cleanse intent"
    if "green tea" in k or re.search(r"\b(tea|teas|matcha|yerba mate|mate tea|ginger tea|chamomile tea|dandelion tea|herbal tea|detox tea)\b", k):
        return "tea_drink", "tea or drink intent"
    if "probiotic" in k or "lactobacillus" in k:
        return "probiotic", "probiotic intent"
    if "mct oil" in k or "olive oil" in k or "castor oil" in k:
        return "oil_fat", "oil/fat method intent"
    if "turmeric" in k or "cinnamon" in k or "dandelion" in k or "moringa" in k:
        return "herb_spice", "herb or spice intent"
    if re.search(r"\b(milk|almond milk|oat milk|yogurt)\b", k):
        return "milk_dairy", "milk or dairy intent"
    if re.search(r"\b(fruit|pineapple|apple|apples|avocado|avocados|butter fruit|tuna|oatmeal|oats|salad|cabbage)\b", k):
        return "whole_food", "whole food intent"
    return None


def classify_title_intent(keyword: str, article_type: str = "", classification: dict[str, Any] | None = None) -> TitleIntent:
    k = norm(keyword)
    page_type = norm((classification or {}).get("page_type", ""))

    if has_any(k, PUBLIC_FIGURE_TERMS) or page_type in {"viral_truth", "public_figure", "celebrity_profile"}:
        return TitleIntent("public_figure", "person", "timeline", "public_fact_check", "public_fact_check", ["claim_filter", "reality_check"], "public figure or viral transformation query")

    if " vs " in k or " versus " in k or "compare" in k or "comparison" in k:
        return TitleIntent("comparison", "mixed", "versus", "comparison_decision", "comparison", ["claim_filter", "reviews_results"], "comparison keyword")

    if re.search(r"\b(cost|price|insurance|cover|coverage|coupon|near me|doctor|dr near me|how to get|get prescribed|medicaid|aetna|blue cross)\b", k):
        return TitleIntent("cost_access", "service_or_medication", "access", "access_guide", "cost_access", ["glp1_medication", "reality_check"], "cost, coverage, near-me, or access intent")

    if re.search(r"\b(dose|dosage|dosing|chart|units|mg|ml|maximum dose|starting dose|maintenance dose|increase .+ dose)\b", k):
        entity_type = "glp1_medication" if has_any(k, GLP1_TERMS) else "medication_or_supplement"
        return TitleIntent("dosage", entity_type, "dose", "dosage_guide", "dosage", ["safety", "glp1_medication"], "dose/chart/titration intent")

    if re.search(r"\b(side effects?|safe|safety|danger|risks?|warning|warnings|drug test|interaction)\b", k):
        entity_type = "glp1_medication" if has_any(k, GLP1_TERMS) else "method_or_product"
        return TitleIntent("safety", entity_type, "risk", "safety_guide", "safety", ["claim_filter", "reality_check"], "safety or side-effect intent")

    if re.search(r"\b(reviews?|results?|before and after|reddit|1 month|2 month|3 months|6 week|by week|pictures|photo)\b", k):
        entity_type = "glp1_medication" if has_any(k, GLP1_TERMS) else "product_or_method"
        return TitleIntent("reviews_results", entity_type, "results", "review_analysis", "reviews_results", ["reality_check", "claim_filter"], "reviews, results, or before-after intent")

    if re.match(r"^(do|does|can|will|is|are|should|how effective)\b", k) or re.search(r"\b(really work|actually work|help with|good for|safe for|cause weight loss|aid in)\b", k):
        entity_type = "glp1_medication" if has_any(k, GLP1_TERMS) else "method_or_product"
        return TitleIntent("does_it_work", entity_type, "question", "question_review", "reality_check", ["claim_filter", "reviews_results"], "question intent")

    # Recipe/trick/natural Mounjaro must beat real GLP-1 medication matching.
    if has_any(k, TREND_RECIPE_TERMS) or re.search(r"\b(recipe|trick|hack|method|drink|water|cleanse)\b", k):
        return TitleIntent("viral_recipe", "natural_trend", "recipe", "trend_fact_check", "viral_recipe", ["reality_check", "claim_filter"], "viral recipe/trick/drink intent")

    sub = food_subfamily(k)
    if sub:
        family, reason = sub
        return TitleIntent(family, "food_or_diet", "natural", "food_guide", family, ["claim_filter", "reality_check"], reason)

    if re.search(r"\b(best|top|top rated|recommended|list of|which .+ best)\b", k):
        if has_any(k, PILL_TERMS) or "pills" in k:
            return TitleIntent("pills_commercial", "pills", "best", "ranked_review", "pills_commercial", ["safety", "comparison"], "best/top pill commercial intent")
        if has_any(k, SUPPLEMENT_TERMS) or "supplement" in k or "supplements" in k:
            return TitleIntent("supplement_commercial", "supplement", "best", "ranked_review", "supplement_commercial", ["claim_filter", "safety"], "best/top supplement intent")
        return TitleIntent("best_top", "ranked_options", "best", "ranked_review", "ranked_review", ["comparison", "claim_filter"], "best/top research intent")

    if has_any(k, PILL_TERMS) or "pills" in k:
        return TitleIntent("pills_commercial", "pills", "commercial", "ranked_review", "pills_commercial", ["safety", "comparison"], "pills/commercial intent")

    if has_any(k, GLP1_TERMS):
        return TitleIntent("glp1_medication", "glp1_medication", "weight_loss", "medication_review", "glp1_medication", ["reviews_results", "claim_filter"], "GLP-1 medication weight-loss keyword")

    if has_any(k, SUPPLEMENT_TERMS) or "supplement" in k or "supplements" in k:
        return TitleIntent("supplement_commercial", "supplement", "general", "supplement_review", "supplement_commercial", ["claim_filter", "safety"], "supplement review intent")

    if re.search(r"\b(benefits?|what does|what is|good for)\b", k):
        return TitleIntent("benefits", "method_or_supplement", "benefits", "benefit_review", "claim_filter", ["reality_check", "reviews_results"], "benefits or claim-filter intent")

    return TitleIntent("general_review", "general", "general", "editorial_review", "general_review", ["claim_filter", "reality_check"], "fallback title intent")


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify title intent for one keyword.")
    parser.add_argument("keyword", nargs="+")
    parser.add_argument("--type", default="")
    args = parser.parse_args()
    print(asdict(classify_title_intent(" ".join(args.keyword), args.type)))


if __name__ == "__main__":
    main()
