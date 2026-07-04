#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Route keywords into sample-style article types."""

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


def route_article_type(keyword: str, classification: dict | None = None) -> ArticleRoute:
    k = normalize(keyword)
    intent = normalize((classification or {}).get("intent", ""))
    page_type = normalize((classification or {}).get("page_type", ""))

    if re.search(r"\b(top\s*\d+|best|ranked|list of|which .+ best)\b", k):
        return ArticleRoute(
            article_type="top_10_listicle",
            reason="ranking/listicle search intent",
            title_style="Best/Top listicle with evaluation criteria",
            required_structure=[
                "Quick Verdict",
                "How We Evaluated These Options",
                "The Options People Usually Compare",
                "Comparison Table",
                "Red Flags",
                "Who Should Be Careful",
                "FAQ",
                "Next Steps Without the Guesswork",
            ],
        )

    if any(token in k for token in [" vs ", " versus ", "compare", "comparison", "better than", "instead of"]) or intent == "comparison":
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

    if any(token in k for token in ["side effect", "side effects", "safe", "safety", "hurt", "danger", "drug test", "pregnant", "pregnancy", "interaction", "interact", "too low"]) or intent in {"safety", "side_effect", "interaction"} or page_type in {"safety_guide", "side_effect_pain", "safety_interaction"}:
        return ArticleRoute(
            article_type="side_effect_safety",
            reason="side effect or safety intent",
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

    if re.search(r"\b(what does|how does|how do|what is|how to|process|steps)\b", k) or intent in {"how_long", "timing", "dosage"}:
        return ArticleRoute(
            article_type="process_explainer",
            reason="process/how/what explainer intent",
            title_style="Real, unfiltered process headline",
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

    if any(token in k for token in ["review", "tested", "tracked", "does it work", "results", "metabolism booster", "weight loss supplement", "fat burner", "berberine", "apple cider vinegar", "green tea", "detox tea", "drops"]):
        return ArticleRoute(
            article_type="evidence_review",
            reason="evidence/review/tracking-style intent",
            title_style="Tracked/looked-closely editorial headline",
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
        reason="fallback editorial intent",
        title_style="Search-intent editorial headline",
        required_structure=[
            "Search Intent Opening",
            "What Actually Matters",
            "Comparison Table",
            "Composite Scenario",
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
