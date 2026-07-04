#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reference-style body engine for batch articles.

This module pushes generated articles toward the user's target style:
search-confusion opening, short-version verdict, practical definition, field-report
sections, decision tables, real-user FAQ, and a protocol close.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from title_engine import title_case_keyword


def compact(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).replace("```", "").strip()
    text = re.sub(r"https?://\S+", "", text).strip()
    return text[:max_len].rstrip(" ,;:-") if max_len else text


def style_family(article_type: str) -> str:
    if article_type in {"evidence_review", "dosage_guide", "timing_guide"}:
        return "field_report"
    if article_type in {"review_analysis", "top_10_listicle"}:
        return "review_tested"
    if article_type == "process_explainer":
        return "inside_process"
    if article_type == "side_effect_safety":
        return "risk_screen"
    if article_type == "public_figure_profile":
        return "public_fact_check"
    return "institutional_editorial"


def style_prompt_block(article_type: str, keyword: str) -> str:
    family = style_family(article_type)
    return f"""Body style target: {family}
Write in the reference style the user provided:
- Do not start with a dictionary definition.
- First paragraph must start from search confusion and reader frustration.
- Second paragraph must use a strong "Here's the short version" verdict.
- Add a practical definition: "In practical terms..." or "In precise terms...".
- H2 headings should sound like editorial findings, not encyclopedia headings.
- Every section should contain: misconception, what we found/reviewed, real-life detail, what to track, and takeaway.
- Use phrases such as: "what actually moved the needle", "despite the hype", "not a miracle", "where the decision changes", "what to track".
- FAQ questions must sound like real search questions, not generic definitions.
- End with a 4-step protocol and a closing loop that repeats the keyword.
- Keep the tone assertive, report-like, and direct.
Keyword being written: {keyword}
""".strip()


def default_search_opening(keyword: str, article_type: str) -> str:
    if article_type == "public_figure_profile":
        return f"If you have typed “{keyword}” into search, you are probably not looking for generic weight-loss advice. You want the timeline, the public claims, what was actually said, and what parts are being repeated without enough context."
    if article_type == "review_analysis":
        return f"If you have searched “{keyword},” you have probably seen polished reviews, dramatic testimonials, and a few warning signs all mixed together. The useful question is not whether people are talking about it. It is what those reports actually prove."
    return f"If you have ever typed “{keyword}” and felt more confused than before, you are not alone. The search results usually push big promises, quick wins, and confident claims, but the useful answer is much narrower once you separate measurable signals from marketing noise."


def default_short_version(keyword: str, article_type: str) -> str:
    if article_type == "side_effect_safety":
        return f"Here’s the short version: {keyword} is not just a yes-or-no safety question. The real decision depends on dose, timing, medication overlap, personal tolerance, and which warning signs would change the plan."
    if article_type == "process_explainer":
        return f"Here’s the short version: {keyword} is not a one-step explanation. It is a sequence of assessment, personalization, tracking, and adjustment that only works when the process matches real life."
    if article_type == "public_figure_profile":
        return f"Here’s the short version: {keyword} should be treated as a public timeline, not a copy-paste plan. What matters is what is confirmed, what is speculation, and what readers should avoid copying blindly."
    return f"Here’s the short version: {keyword} may sound like one simple promise, but it usually breaks into three decisions: what can realistically work, what is exaggerated, and what needs to be tracked before you trust the result."


def default_practical_definition(keyword: str, article_type: str) -> str:
    if article_type == "review_analysis":
        return f"In practical terms, a useful review of {keyword} should compare user reports, plausible mechanisms, safety complaints, and the gap between what people feel and what evidence can actually prove."
    if article_type == "public_figure_profile":
        return f"In practical terms, {keyword} should be judged by public statements, visible timeline changes, credible reporting, and clear separation between confirmed facts and online speculation."
    return f"In practical terms, {keyword} should be judged by measurable changes, tradeoffs, consistency, and whether the benefit is large enough to matter outside a headline."


def normalize_style_fields(raw: dict[str, Any]) -> dict[str, str]:
    return {
        "misconception": compact(raw.get("misconception"), 260),
        "what_we_found": compact(raw.get("what_we_found") or raw.get("real_process") or raw.get("professional_take"), 420),
        "real_life_detail": compact(raw.get("real_life_detail") or raw.get("real_world_detail"), 420),
        "what_to_track": compact(raw.get("what_to_track"), 260),
        "takeaway": compact(raw.get("takeaway") or raw.get("reader_takeaway"), 260),
    }


def section_heading(article_type: str, index: int, keyword: str, original: str = "") -> str:
    original = compact(original, 80)
    if original and not re.search(r"\b(overview|introduction|benefits|conclusion)\b", original, flags=re.I):
        return original
    topic = title_case_keyword(keyword)
    patterns = {
        "evidence_review": [
            f"Why {topic} Gets Confusing — and Where to Intervene",
            "The Claims We Compared Closely",
            "What Actually Moved the Needle",
            "What Under-Delivered Despite the Hype",
            "The Tracking Signals That Matter Most",
        ],
        "review_analysis": [
            f"Why {topic} Reviews Are So Noisy",
            "What Users Report Most Often",
            "What Reviews Cannot Prove",
            "Where The Risk Signals Show Up",
            "The Pattern Worth Paying Attention To",
        ],
        "process_explainer": [
            "Step 1: The Full-Body Investigation, Not Just a Form",
            "Step 2: The Blueprint Built Around Real Life",
            "Step 3: Rewiring the Habit Loop, Not Just the Plate",
            "Step 4: Tracking, Tweaking, and Breaking Plateaus",
            "Where The Process Usually Succeeds or Fails",
        ],
        "side_effect_safety": [
            f"Why {topic} Is a Safety Question, Not Just a Search Query",
            "The Common Effects People Notice First",
            "The Warning Signs That Change the Decision",
            "Who Needs a More Careful Risk Screen",
            "What To Ask Before You Try It",
        ],
        "public_figure_profile": [
            "What Is Publicly Known So Far",
            "The Timeline People Are Actually Searching For",
            "What Was Said Publicly Versus Repeated Online",
            "What Readers Should Not Copy Blindly",
            "The Part Most Articles Leave Out",
        ],
    }
    return patterns.get(article_type, patterns["evidence_review"])[min(index, 4)]


def core_insight_heading(article_type: str) -> str:
    return {
        "evidence_review": "Signal, Not Hype: The Part That Actually Matters",
        "review_analysis": "Patterns, Not Promises: What The Reviews Really Show",
        "process_explainer": "Process, Not a Printout: Why The Details Matter",
        "side_effect_safety": "Safety, Not Shortcuts: Where The Decision Changes",
        "public_figure_profile": "Timeline, Not Transformation Myths",
        "top_10_listicle": "What Works, What Fails & What To Avoid",
    }.get(article_type, "Evidence, Not Empty Claims")


def protocol_heading(article_type: str) -> str:
    return {
        "evidence_review": "Putting It All Together: A 4-Step Reality Check Protocol",
        "review_analysis": "Putting It All Together: A 4-Step Review Filter",
        "process_explainer": "Putting It All Together: A 4-Step Appointment Prep Plan",
        "side_effect_safety": "Putting It All Together: A 4-Step Safety Check",
        "public_figure_profile": "Putting It All Together: A 4-Step Fact-Check Filter",
        "top_10_listicle": "Putting It All Together: A 4-Step Buying Filter",
    }.get(article_type, "Putting It All Together: A 4-Step Decision Protocol")


def default_closing_loop(keyword: str, article_type: str) -> str:
    return f"You came here searching {keyword}. The useful answer is not a louder claim or a cleaner-looking label. It is a decision framework: what changed, what failed to move, what deserves tracking, and what should happen before you act on the next piece of advice."


def current_year() -> int:
    return datetime.now().year
