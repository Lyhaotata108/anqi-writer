#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate complete Markdown article drafts from body blueprints.

This is the publishable-article layer after:
keywords -> clusters -> titles -> body blueprints.

It writes one Markdown file per primary article and an article_publish_queue.csv.
The writer is deterministic and safety-first. It does not invent case studies,
clinical data, citations, or first-person testing claims.
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
import argparse
import csv
import re
from typing import Any

DEFAULT_ARTICLES_DIR = "output/articles"
DEFAULT_QUEUE_OUTPUT = "output/article_publish_queue.csv"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_l(text: str) -> str:
    return normalize(text).lower()


def slugify(text: str) -> str:
    slug = str(text or "").lower().replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:80].strip("-") or "article"


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", str(text or "")))


def split_pipe(text: str) -> list[str]:
    return [part.strip() for part in str(text or "").split("|") if part.strip()]


def title_case(text: str) -> str:
    small = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "is", "of", "on", "or", "the", "to", "vs", "with"}
    words = re.sub(r"[^a-zA-Z0-9+%']+", " ", str(text or "")).split()
    out = []
    for i, word in enumerate(words):
        low = word.lower()
        if low in {"cbd", "a1c", "ldl", "hdl", "fda", "otc"}:
            out.append(low.upper())
        elif i and low in small:
            out.append(low)
        else:
            out.append(low[:1].upper() + low[1:])
    return " ".join(out).strip()


def question_from_keyword(keyword: str, category: str) -> str:
    k = normalize(keyword).rstrip("?")
    if re.match(r"^(what|why|how|when|where|who|does|do|can|will|is|are|should)\b", k, flags=re.I):
        return title_case(k) + "?"
    if category == "cbd":
        return f"Is {title_case(k)} worth considering?"
    if category == "blood":
        return f"What should you know about {title_case(k)}?"
    return f"Does {title_case(k)} actually matter?"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def clean_category(row: dict[str, str]) -> str:
    raw = str(row.get("category") or "weight_loss").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"cbd", "hemp"}:
        return "cbd"
    if raw in {"blood", "blood_health", "blood_sugar", "blood_pressure"}:
        return "blood"
    return "weight_loss"


def last_updated() -> str:
    return datetime.now().strftime("%B %d, %Y").replace(" 0", " ")


def front_matter(row: dict[str, str], slug: str) -> str:
    category = clean_category(row)
    return "\n".join([
        "---",
        f"title: \"{normalize(row.get('title') or row.get('keyword'))}\"",
        f"slug: \"{slug}\"",
        f"category: \"{category}\"",
        f"primary_keyword: \"{normalize(row.get('keyword'))}\"",
        f"body_template: \"{normalize(row.get('body_template'))}\"",
        f"target_word_count: \"{normalize(row.get('target_word_count'))}\"",
        "status: \"draft_ready\"",
        "---",
        "",
    ])


def intro(row: dict[str, str]) -> str:
    category = clean_category(row)
    keyword = normalize(row.get("keyword"))
    title = normalize(row.get("title"))
    hook = normalize(row.get("intro_hook"))
    if category == "cbd":
        return (
            f"Searching **{keyword}** usually means you want a practical answer without product hype. CBD content online often mixes reasonable questions with aggressive marketing, so the useful starting point is not whether one product sounds impressive, but what can be verified on the label, what the claim is trying to solve, and what safety issues could change the decision.\n\n"
            f"This guide uses the title angle — **{title}** — as the editorial frame. The goal is to separate what may be plausible from what is still uncertain, explain the checks that matter before buying or using CBD, and keep the advice grounded enough that a reader can discuss it with a clinician when medications, chronic conditions, or drug testing are involved. {hook}"
        )
    if category == "blood":
        return (
            f"Searching **{keyword}** usually means you are trying to understand a number, a pattern, or a risk signal. Blood-related searches can feel urgent because the same phrase may be harmless in one context and important in another. That is why this article treats the topic as a practical interpretation guide, not a diagnosis.\n\n"
            f"The title angle — **{title}** — sets the main promise: explain what the number or claim can mean, what it cannot prove by itself, and which next steps are more useful than guessing. {hook} The safest answer usually depends on repeated readings, symptoms, medical history, medications, and whether a clinician has already given a target range."
        )
    return (
        f"Searching **{keyword}** usually means you want more than a generic list. You may be comparing options, checking a trend, trying to understand realistic results, or deciding whether something is worth your time and money. The problem is that many weight-loss articles answer the surface keyword but skip the part that actually changes the decision.\n\n"
        f"This article follows the title angle — **{title}** — and focuses on what a reader can use in real life: the short version first, the tradeoffs that usually get missed, the questions worth asking, and the safer next step. {hook}"
    )


def short_version(row: dict[str, str]) -> str:
    category = clean_category(row)
    angle = normalize(row.get("short_answer_angle"))
    if category == "cbd":
        body = (
            "CBD is best approached as a product-quality and expectation-setting question, not a miracle-solution question. The most useful checks are the amount of CBD per serving, whether the product is full-spectrum, broad-spectrum, or isolate, whether third-party testing is current, and whether the claimed benefit matches something a reader can realistically evaluate.\n\n"
            "The main caution is that CBD can interact with some medications, may matter for people who are pregnant or managing chronic conditions, and can create drug-testing concerns when THC exposure is possible. A careful buyer should verify the certificate of analysis, avoid cure-style claims, and ask a clinician when there is a medical condition or daily medication involved. " + angle
        )
    elif category == "blood":
        body = (
            "A blood-related number rarely tells the whole story by itself. One reading can be affected by timing, food, stress, sleep, exercise, hydration, medication, device accuracy, and the way the sample was taken. The more useful question is whether the pattern repeats and whether it matches symptoms or risk factors.\n\n"
            "For anything very abnormal, rapidly changing, or paired with concerning symptoms, the next step is medical guidance rather than another internet search. For less urgent questions, tracking readings consistently and comparing them with a clinician-provided target range is usually more useful than chasing a single perfect number. " + angle
        )
    else:
        body = (
            "The short version is that most weight-loss topics are less clean than the headline makes them sound. Some options can help under the right conditions, but they rarely work as standalone shortcuts. The real question is whether the method fits the person, whether the evidence is strong enough, and what usually breaks down after the first burst of motivation.\n\n"
            "A good decision starts with the claim, then checks the tradeoff: cost, safety, consistency, appetite, side effects, maintenance, or whether the result depends on replacing a higher-calorie habit rather than burning fat directly. " + angle
        )
    return f"## The Short Version\n\n{body}"


def section_paragraphs(row: dict[str, str], h2: str, index: int) -> str:
    category = clean_category(row)
    keyword = normalize(row.get("keyword"))
    template = normalize(row.get("body_template"))
    h2_l = norm_l(h2)

    if category == "cbd":
        paragraphs = [
            f"The useful way to read this section is to connect **{keyword}** to a real decision. CBD questions often become confusing because the same word can describe a gummy, oil, topical, capsule, isolate, or full-spectrum product. Those products do not create identical expectations, and they should not be judged by the same marketing claim alone.",
            "A careful review starts with the product facts: serving size, CBD amount per serving, other cannabinoids, THC exposure, third-party lab testing, ingredient list, and the date of the certificate of analysis. When those details are missing or vague, the article should treat the claim as weaker, even if the product page or review sounds confident.",
            "The second layer is personal fit. A reader taking daily medication, managing a chronic condition, preparing for drug testing, or using other sleep, anxiety, or pain products has a different risk profile than someone casually comparing wellness products. The safer framing is not “CBD works” or “CBD does not work,” but whether the claim, product quality, and risk context line up.",
        ]
        if "safety" in template or "risk" in h2_l or "side effect" in h2_l:
            paragraphs.append("Safety also depends on dose, timing, liver-metabolized medications, alcohol use, pregnancy status, and whether the product contains measurable THC. This is why strong medical claims should be avoided unless there is clear supporting evidence. The article should push readers toward label verification and professional guidance instead of self-escalating the dose.")
        else:
            paragraphs.append("The practical takeaway is to slow the decision down. A reader should compare products using verifiable details, not star ratings alone. If the product cannot show what is inside, how it was tested, and what the serving actually provides, it should not be treated as a strong option no matter how polished the sales page looks.")
    elif category == "blood":
        paragraphs = [
            f"The first rule for **{keyword}** is context. A blood pressure reading, glucose value, A1C result, cholesterol number, or blood test marker can look simple on a chart, but the interpretation changes with timing, history, symptoms, medication, and whether the result repeats. A single number can start the conversation; it should not finish it.",
            "Patterns matter more than isolated readings. For home measurements, consistency matters: same device, similar time of day, proper technique, and enough readings to see whether the pattern is stable. For lab values, the useful context often includes fasting status, recent illness, supplements, medication changes, and whether earlier results were trending in the same direction.",
            "The article should avoid diagnosing the reader. Instead, it should explain what the number can suggest, why it may move, when it becomes more concerning, and what a clinician would typically want to know next. This keeps the content helpful without pretending that a general article can replace individualized care.",
        ]
        if "warning" in h2_l or "safety" in template or "caution" in h2_l:
            paragraphs.append("If a reading is extremely abnormal, rapidly worsening, or paired with symptoms such as chest pain, trouble breathing, confusion, fainting, severe headache, weakness, or vision changes, the safest advice is urgent medical evaluation. Internet guidance is only appropriate for general education, not emergency triage.")
        else:
            paragraphs.append("The practical next step is usually structured tracking and a better question. Instead of asking what the number means in isolation, ask whether it is new, repeated, related to symptoms, influenced by recent behavior, or already outside a clinician-provided target range.")
    else:
        paragraphs = [
            f"The useful way to approach **{keyword}** is to separate the promise from the mechanism. Many weight-loss claims sound persuasive because they focus on the desired result, but the better question is what actually changes: appetite, calories, protein intake, activity, medication response, water weight, digestion, or consistency over time.",
            "A strong article should not pretend that every reader has the same body, budget, medical history, or tolerance for side effects. What looks like a simple trend or product decision often depends on whether the person can repeat the behavior, whether the method creates problems later, and whether the early result is likely to be maintained.",
            "This section should also keep the title promise in view. If the headline creates curiosity around hype, cost, safety, the first month, or a hidden tradeoff, the body has to answer that tension directly. Otherwise the article may get the click but lose the reader before the helpful part arrives.",
        ]
        if "buy" in h2_l or "spend" in h2_l or "money" in h2_l or "red flag" in h2_l:
            paragraphs.append("Before spending money, the reader should check whether the claim is specific, whether the product or method explains its limits, whether safety warnings are easy to find, and whether the result depends on a broader diet or medication plan. Vague promises are not proof, and high-volume reviews do not replace evidence or fit.")
        elif "short version" in h2_l or "expect" in h2_l:
            paragraphs.append("The short answer should be direct but not exaggerated. If something may help, explain the condition under which it may help. If the claim is weak, say that clearly. If the risk is not obvious, bring it forward before the reader reaches the end of the article.")
        else:
            paragraphs.append("The practical takeaway is to focus on the failure point. Most weight-loss decisions do not fail because the reader did not want the result enough. They fail because the method was hard to repeat, did not match the person’s health context, or solved one problem while creating another.")

    return f"## {h2}\n\n" + "\n\n".join(paragraphs)


def comparison_table(row: dict[str, str]) -> str:
    category = clean_category(row)
    table_type = normalize(row.get("table_type"))
    if category == "cbd":
        return "\n".join([
            "## Comparison Table: What To Verify Before You Trust the Claim",
            "",
            "| Checkpoint | Why it matters | What to look for |",
            "|---|---|---|",
            "| CBD amount per serving | Marketing often highlights bottle size, not usable serving strength | Clear mg amount per serving |",
            "| Product spectrum | Full-spectrum, broad-spectrum, and isolate can create different expectations | Spectrum type and THC disclosure |",
            "| Third-party testing | Reduces uncertainty around potency and contaminants | Recent certificate of analysis |",
            "| Drug-testing risk | Some products may contain trace THC | THC amount and testing notes |",
            "| Medical fit | Conditions and medications can change the risk profile | Clinician discussion when relevant |",
            "",
            f"This table is tied to the blueprint table type: **{table_type}**. It should be expanded with product-specific details only when verified data is available.",
        ])
    if category == "blood":
        return "\n".join([
            "## Comparison Table: What Can Change the Reading",
            "",
            "| Factor | Why it changes interpretation | Practical next step |",
            "|---|---|---|",
            "| Timing | Readings can vary by time of day, meals, stress, and activity | Compare readings taken under similar conditions |",
            "| Device or test method | Home devices and lab tests answer different questions | Use proper technique and repeat when appropriate |",
            "| Symptoms | Symptoms can make a number more urgent | Seek medical guidance for concerning symptoms |",
            "| Medication changes | Recent changes can shift blood pressure, glucose, or lipid values | Review changes with a clinician |",
            "| Trend over time | Repeated patterns matter more than one isolated value | Track and compare against prior readings |",
            "",
            f"This table follows the blueprint table type: **{table_type}**. It should not be used as a diagnostic chart by itself.",
        ])
    return "\n".join([
        "## Comparison Table: Claim vs. What To Verify",
        "",
        "| Claim or decision point | What to verify | Why it matters |",
        "|---|---|---|",
        "| Fast results | Whether the result is fat loss, water weight, appetite change, or habit replacement | Early changes can be misread |",
        "| Natural or simple method | Dose, consistency, safety, and whether it replaces a higher-calorie habit | Natural does not automatically mean effective |",
        "| Product reviews | Evidence, ingredients, warnings, and refund terms | Reviews can miss safety and fit |",
        "| Medication or supplement option | Clinician guidance, interactions, and realistic expectations | Medical context changes the decision |",
        "| Viral trend | What actually changes in the routine | Popularity is not proof |",
        "",
        f"This table follows the blueprint table type: **{table_type}** and should be customized further when verified product or clinical details are available.",
    ])


def faq_section(row: dict[str, str]) -> str:
    category = clean_category(row)
    keyword = normalize(row.get("keyword"))
    faq_keywords = split_pipe(row.get("faq_keywords"))
    semantic_keywords = split_pipe(row.get("semantic_keywords"))
    seeds = faq_keywords + semantic_keywords
    if not seeds:
        seeds = [keyword]
    try:
        target_count = max(4, min(8, int(float(row.get("faq_count") or 6))))
    except ValueError:
        target_count = 6
    seeds = seeds[:target_count]

    parts = ["## Frequently Asked Questions"]
    for seed in seeds:
        q = question_from_keyword(seed, category)
        if category == "cbd":
            a = (
                f"{q.rstrip('?')} depends on the product type, serving amount, testing quality, and the reason someone is considering CBD. A useful answer should avoid cure-style promises and focus on what can be checked: CBD amount, THC exposure, product spectrum, third-party testing, and personal risk factors.\n\n"
                "If the person uses medications, has a medical condition, is pregnant, or may be drug tested, the safer next step is to ask a qualified clinician and verify the product label before using it."
            )
        elif category == "blood":
            a = (
                f"{q.rstrip('?')} should be interpreted with context rather than as a standalone answer. Timing, repeat readings, symptoms, medication use, recent meals, stress, hydration, and testing method can all change what the result means.\n\n"
                "If a number is very abnormal, worsening, or paired with concerning symptoms, medical guidance is more important than general online information."
            )
        else:
            a = (
                f"{q.rstrip('?')} can matter, but the useful answer depends on mechanism and fit. Ask what the method actually changes: appetite, calories, protein, activity, medication response, consistency, or water weight.\n\n"
                "The safer way to evaluate it is to look for realistic limits, possible downsides, and whether the approach can be repeated without creating a new problem."
            )
        parts.append(f"### {q}\n\n{a}")
    return "\n\n".join(parts)


def protocol_section(row: dict[str, str]) -> str:
    category = clean_category(row)
    protocol = normalize(row.get("protocol_type"))
    if category == "cbd":
        steps = [
            "Define the reason for considering CBD before comparing products.",
            "Check the certificate of analysis, serving size, spectrum type, and THC disclosure.",
            "Review medications, drug-testing risk, pregnancy status, and medical conditions before use.",
            "Start with cautious expectations and track whether the intended outcome changes in a meaningful way.",
        ]
    elif category == "blood":
        steps = [
            "Measure or review the number under consistent conditions whenever possible.",
            "Look for a repeated pattern rather than reacting to one isolated reading.",
            "Write down symptoms, medication changes, meals, sleep, stress, and activity around the reading.",
            "Discuss persistent, very abnormal, or symptom-linked results with a qualified clinician.",
        ]
    else:
        steps = [
            "Identify the specific claim before acting on it.",
            "Check what mechanism would realistically create the result.",
            "Look for the tradeoff: cost, safety, hunger, side effects, consistency, or maintenance.",
            "Choose the next step that can be repeated and measured without relying on hype.",
        ]
    lines = [f"## Practical Protocol: {title_case(protocol.replace('_', ' '))}", ""]
    for i, step in enumerate(steps, start=1):
        lines.append(f"{i}. **{step}**")
    lines.append("")
    lines.append("This protocol is intentionally conservative. It is designed to help the reader make a cleaner next decision, not to replace professional care or promise a specific outcome.")
    return "\n".join(lines)


def final_takeaway(row: dict[str, str]) -> str:
    category = clean_category(row)
    keyword = normalize(row.get("keyword"))
    if category == "cbd":
        return (
            "## Final Takeaway\n\n"
            f"For **{keyword}**, the strongest article angle is not hype; it is verification. CBD content becomes more useful when it explains product type, dose, testing, safety, interactions, and realistic expectations. If those pieces are missing, the claim should be treated as incomplete."
        )
    if category == "blood":
        return (
            "## Final Takeaway\n\n"
            f"For **{keyword}**, the responsible answer is context first. A number, reading, or symptom pattern can be useful, but it should be interpreted alongside timing, repeat measurements, symptoms, medical history, and clinician guidance. The goal is not to guess faster; it is to understand what the next safe step should be."
        )
    return (
        "## Final Takeaway\n\n"
        f"For **{keyword}**, the best answer is usually less dramatic than the search results make it look. Focus on the mechanism, the tradeoff, and the part that tends to fail after the initial excitement. That is where the real decision becomes clearer."
    )


def disclaimer(row: dict[str, str]) -> str:
    category = clean_category(row)
    if category == "cbd":
        return (
            "## Important Note\n\n"
            "This article is for educational purposes only and does not provide medical advice. CBD may interact with medications, may not be appropriate for every person, and product quality can vary. Speak with a qualified healthcare professional before using CBD for a health condition, combining it with medication, or using it when pregnant, breastfeeding, or subject to drug testing."
        )
    if category == "blood":
        return (
            "## Important Note\n\n"
            "This article is for educational purposes only and is not a diagnosis or treatment plan. Blood pressure, blood sugar, cholesterol, oxygen, and other blood-related readings require clinical context. Seek urgent medical care for severe symptoms, very abnormal readings, or rapidly worsening patterns, and discuss persistent concerns with a qualified healthcare professional."
        )
    return (
        "## Important Note\n\n"
        "This article is for educational purposes only and does not provide medical advice. Weight-loss medications, supplements, diet changes, and exercise plans may not be appropriate for every person. Speak with a qualified healthcare professional before starting a medication, supplement, or major health routine, especially if you have a medical condition or take daily medications."
    )


def build_markdown(row: dict[str, str]) -> str:
    title = normalize(row.get("title") or row.get("keyword") or "Article")
    slug = slugify(row.get("keyword") or title)
    h2s = [normalize(row.get(f"h2_{i}")) for i in range(1, 9) if normalize(row.get(f"h2_{i}"))]

    parts = [
        front_matter(row, slug),
        f"# {title}",
        "",
        f"Last updated: {last_updated()}",
        "",
        intro(row),
        "",
        short_version(row),
        "",
    ]
    for i, h2 in enumerate(h2s, start=1):
        parts.append(section_paragraphs(row, h2, i))
        parts.append("")
    parts.extend([
        comparison_table(row),
        "",
        protocol_section(row),
        "",
        faq_section(row),
        "",
        final_takeaway(row),
        "",
        disclaimer(row),
        "",
    ])
    return "\n".join(parts).strip() + "\n"


def quality_check(markdown: str, row: dict[str, str]) -> tuple[str, bool, list[str]]:
    notes: list[str] = []
    wc = word_count(markdown)
    try:
        target = int(float(row.get("target_word_count") or 1800))
    except ValueError:
        target = 1800
    h2_count = len(re.findall(r"^## ", markdown, flags=re.M))
    faq_ok = "## Frequently Asked Questions" in markdown
    short_ok = "## The Short Version" in markdown
    disclaimer_ok = "## Important Note" in markdown

    if wc < int(target * 0.65):
        notes.append(f"word_count_below_target:{wc}/{target}")
    if h2_count < 5:
        notes.append(f"too_few_h2:{h2_count}")
    if not faq_ok:
        notes.append("missing_faq")
    if not short_ok:
        notes.append("missing_short_version")
    if not disclaimer_ok:
        notes.append("missing_disclaimer")
    if re.search(r"\b(guaranteed|miracle cure|cures?|detoxes?|burns fat instantly)\b", markdown, flags=re.I):
        notes.append("unsafe_claim_language")

    status = "PASS" if not notes else "REVIEW"
    publish_ready = status == "PASS"
    return status, publish_ready, notes


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate complete Markdown article drafts from body_blueprint CSV.")
    parser.add_argument("input", help="Input body_blueprint_audit CSV")
    parser.add_argument("--articles-dir", default=DEFAULT_ARTICLES_DIR)
    parser.add_argument("--queue-output", default=DEFAULT_QUEUE_OUTPUT)
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    article_dir = Path(args.articles_dir)
    article_dir.mkdir(parents=True, exist_ok=True)
    rows = read_csv(input_path)
    queue_rows: list[dict[str, Any]] = []

    for row in rows:
        if row.get("publish_role", "primary_article") != "primary_article":
            continue
        title = normalize(row.get("title") or row.get("keyword") or "Article")
        slug = slugify(row.get("keyword") or title)
        path = article_dir / f"{slug}.md"
        markdown = build_markdown(row)
        status, publish_ready, notes = quality_check(markdown, row)
        path.write_text(markdown, encoding="utf-8")
        queue_rows.append({
            "category": clean_category(row),
            "keyword": row.get("keyword", ""),
            "title": title,
            "slug": slug,
            "markdown_path": str(path),
            "word_count": word_count(markdown),
            "target_word_count": row.get("target_word_count", ""),
            "body_template": row.get("body_template", ""),
            "quality_status": status,
            "publish_ready": "yes" if publish_ready else "review",
            "quality_notes": " | ".join(notes),
        })

    fields = ["category", "keyword", "title", "slug", "markdown_path", "word_count", "target_word_count", "body_template", "quality_status", "publish_ready", "quality_notes"]
    write_csv(Path(args.queue_output), queue_rows, fields)

    pass_count = sum(1 for row in queue_rows if row["quality_status"] == "PASS")
    print(f"Wrote {len(queue_rows)} Markdown articles to {article_dir}")
    print(f"Wrote publish queue to {args.queue_output}")
    print(f"Quality: {pass_count} PASS · {len(queue_rows) - pass_count} REVIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
