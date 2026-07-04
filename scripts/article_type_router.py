#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Route keywords into scalable sample-style article types.

This router is intentionally rule-based so large keyword batches can be routed
before any AI call. Do not add one-off keyword exceptions here; add reusable
intent patterns only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import re


@dataclass(frozen=True)
class ArticleRoute:
    article_type: str
    reason: str
    title_style: str
    required_structure: list[str]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def has_any(text: str, tokens: tuple[str, ...] | list[str]) -> bool:
    return any(token in text for token in tokens)


def matches(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.I) is not None


def looks_like_public_figure(keyword: str, classification: dict | None) -> bool:
    page_type = normalize((classification or {}).get("page_type", ""))
    entity = str((classification or {}).get("entity", "")).strip()
    if page_type in {"viral_truth", "public_figure", "celebrity_profile"} and len(entity.split()) >= 2:
        return True
    return bool(matches(keyword, r"\b(weight loss journey|transformation|before and after)\b") and len(keyword.split()) >= 3)


def route_article_type(keyword: str, classification: dict | None = None) -> ArticleRoute:
    k = normalize(keyword)
    intent = normalize((classification or {}).get("intent", ""))
    page_type = normalize((classification or {}).get("page_type", ""))

    # 1. Public figure / viral transformation profiles need fact-check structure.
    if looks_like_public_figure(k, classification):
        return ArticleRoute(
            article_type="public_figure_profile",
            reason="public figure or viral transformation query",
            title_style="Timeline/results/what-is-public headline",
            required_structure=[
                "What Is Publicly Known",
                "Timeline",
                "What The Person Actually Said",
                "What Is Media Speculation",
                "What Readers Should Not Copy Blindly",
                "FAQ",
            ],
        )

    # 2. Reviews, trials, tested, lab-test, and 'really work' queries.
    if matches(k, r"\b(reviews?|users?|reddit|trials?|tested|lab tests?|really work|actually work|real results|what .* say)\b"):
        return ArticleRoute(
            article_type="review_analysis",
            reason="reviews/tested/user-report search intent",
            title_style="Reviews/tested/results headline with safety angle",
            required_structure=[
                "Quick Verdict",
                "What Was Reviewed",
                "What Users Report",
                "What The Evidence Does Not Show",
                "Safety Notes",
                "FAQ",
                "Next Steps Without the Guesswork",
            ],
        )

    # 3. Shopping/list intent. Must produce real options, not a generic guide.
    if matches(k, r"\b(top\s*\d+|top\s+ten|best|ranked|ranking|list of|which .+ best)\b"):
        return ArticleRoute(
            article_type="top_10_listicle",
            reason="ranking/listicle/commercial research intent",
            title_style="Best/Top listicle with evaluation criteria",
            required_structure=[
                "Quick Verdict",
                "How We Evaluated These Options",
                "The 10 Options People Usually Compare",
                "Comparison Table",
                "Red Flags",
                "Who Should Be Careful",
                "FAQ",
                "Next Steps Without the Guesswork",
            ],
        )

    # 4. Explicit comparison decisions.
    if has_any(k, [" vs ", " versus ", "compare", "comparison", "better than", "instead of", "which is better"]) or intent == "comparison":
        return ArticleRoute(
            article_type="comparison_decision",
            reason="comparison decision query",
            title_style="Side-by-side decision headline",
            required_structure=[
                "Quick Verdict",
                "Where Option A Wins",
                "Where Option B Wins",
                "Side-by-side Table",
                "Who Should Choose Which",
                "FAQ",
                "Next Steps Without the Guesswork",
            ],
        )

    # 5. Regulated / YMYL safety, interaction, pregnancy, and drug-test intents.
    if has_any(k, [
        "side effect", "side effects", "safe", "safety", "hurt", "danger", "risk", "risks",
        "warning", "warnings", "interaction", "interact", "contraindication", "too low",
        "pregnant", "pregnancy", "breastfeeding", "baby", "drug test", "urine test", "liver",
        "kidney", "heart", "blood pressure", "thyroid", "medication",
    ]) or intent in {"safety", "side_effect", "interaction", "pregnancy", "drug_test"} or page_type in {"safety_guide", "side_effect_pain", "safety_interaction"}:
        return ArticleRoute(
            article_type="side_effect_safety",
            reason="side effect, safety, interaction, pregnancy, or drug-test intent",
            title_style="Safety decision headline",
            required_structure=[
                "Why This Question Matters",
                "Common Effects",
                "Warning Signs",
                "Who Should Be Careful",
                "Interaction Questions",
                "What To Ask a Professional",
                "FAQ",
            ],
        )

    # 6. Dosage / amount intent. Works for supplements, foods, drinks, medications.
    if matches(k, r"\b(how much|how many|dose|dosage|mg|milligram|grams?|gummies?|capsules?|pills?|drops?|servings?)\b") or intent == "dosage":
        return ArticleRoute(
            article_type="dosage_guide",
            reason="dosage or amount intent",
            title_style="Dose/amount guide with safety boundaries",
            required_structure=[
                "Quick Verdict",
                "What The Amount Means",
                "Typical Ranges People Compare",
                "Safety Boundaries",
                "Mistakes To Avoid",
                "FAQ",
                "Next Steps Without the Guesswork",
            ],
        )

    # 7. Timing / duration / onset intent.
    if matches(k, r"\b(when to take|best time|morning|night|before bed|with food|empty stomach|how long|how fast|how soon|time to|take effect|start working)\b") or intent in {"timing", "how_long"}:
        return ArticleRoute(
            article_type="timing_guide",
            reason="timing, duration, or onset intent",
            title_style="Timing guide with realistic timeline",
            required_structure=[
                "Quick Verdict",
                "What Timing Changes",
                "Timeline Table",
                "What Can Make It Feel Faster Or Slower",
                "Common Mistakes",
                "FAQ",
                "Next Steps Without the Guesswork",
            ],
        )

    # 8. Symptom / meaning / diagnostic-adjacent explainer intent.
    if matches(k, r"\b(symptoms?|signs?|why do i|why am i|what causes|cause of|meaning|means|normal|high|low|after eating|fasting)\b") or page_type in {"symptom_explainer", "condition_explainer"}:
        return ArticleRoute(
            article_type="symptom_explainer",
            reason="symptom or meaning explainer intent",
            title_style="Symptom explainer with triage boundaries",
            required_structure=[
                "Why This Happens",
                "Common Patterns",
                "When It Needs Attention",
                "What To Track",
                "Comparison Table",
                "FAQ",
                "Next Steps Without the Guesswork",
            ],
        )

    # 9. Cost / insurance / affordability intent.
    if matches(k, r"\b(cost|price|expensive|cheap|affordable|insurance|covered|coverage|copay|coupon|discount|worth it|money)\b"):
        return ArticleRoute(
            article_type="cost_review",
            reason="cost, insurance, or value intent",
            title_style="Cost/value decision headline",
            required_structure=[
                "Quick Verdict",
                "What You Actually Pay For",
                "Cost Comparison Table",
                "When It Is Worth It",
                "When It Is Not Worth It",
                "FAQ",
                "Next Steps Without the Guesswork",
            ],
        )

    # 10. Professional process / how-it-works explainers.
    if matches(k, r"\b(what does|how does|how do|what is|how to|process|steps|appointment|consultation|program|plan|guide)\b"):
        return ArticleRoute(
            article_type="process_explainer",
            reason="process/how/what explainer intent",
            title_style="Process explainer headline",
            required_structure=[
                "What It Actually Means",
                "Step 1",
                "Step 2",
                "Step 3",
                "Comparison Table",
                "FAQ",
                "Next Steps Without the Guesswork",
            ],
        )

    # 11. Evidence/review and does-it-work intents.
    if has_any(k, [
        "review", "tested", "tracked", "does it work", "actually work", "results", "before and after",
        "metabolism booster", "weight loss supplement", "fat burner", "berberine", "apple cider vinegar",
        "green tea", "detox tea", "drops", "gummies", "cbd", "metformin", "mounjaro", "ozempic",
    ]):
        return ArticleRoute(
            article_type="evidence_review",
            reason="evidence/review/tracking-style intent",
            title_style="Evidence-aware editorial headline",
            required_structure=[
                "Why People Search This",
                "What We Evaluated",
                "Results Table",
                "What Worked",
                "What Under-delivered",
                "FAQ",
                "Daily Protocol",
                "Next Steps Without the Guesswork",
            ],
        )

    return ArticleRoute(
        article_type="generic_editorial",
        reason="fallback editorial intent; monitor generic share in batch reports",
        title_style="Search-intent editorial headline",
        required_structure=[
            "Search Intent Opening",
            "What Actually Matters",
            "Comparison Table",
            "Concrete Scenario",
            "FAQ",
            "Next Steps Without the Guesswork",
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Route one keyword to an article type.")
    parser.add_argument("keyword", nargs="+")
    args = parser.parse_args()
    print(asdict(route_article_type(" ".join(args.keyword))))


if __name__ == "__main__":
    main()
