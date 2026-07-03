#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Editorial segmented generation controller.

This controller makes Stage 2 section-by-section by default so the finished
article is closer to an expert-process feature: direct answer, real friction,
process breakdown, scenario, table, action steps, thick FAQ, and a clear next
step.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re
from typing import Iterable

from pipeline_controller import PipelineController, PipelineResult, ProgressCallback
from preview_renderer import render_preview_html
from publish_articles import load_article


class EditorialPipelineController(PipelineController):
    """PipelineController variant that makes segmented Stage 2 the default."""

    INVALID_SECTION_TOKENS = (
        "understanding",
        "key findings",
        "mechanism",
        "clinical evidence",
        "contraindications",
        "benefits",
        "risks",
        "safety profile",
        "overview",
        "explained",
        "current studies",
        "conclusion",
    )

    def build_markdown_from_plan(
        self,
        keyword: str,
        stage1_2: dict,
        category_id: int | None = None,
        keyword_id: int | None = None,
        style: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> Path:
        if progress:
            progress("Fact_Checking", 45, "Rendering Stage 2 with editorial segmented generation")

        slug = self._slugify(keyword)
        markdown_path = self.output_root / f"ui_{slug}.md"
        draft_markdown_path = self.output_root / f"ui_{slug}.draft.md"
        node = self._select_best_stage2_node(keyword, stage1_2)
        cr = node.setdefault("cr", {})
        title = self._normalize_final_title(str(node.get("t", keyword)), keyword)
        description = self._truncate_description(str(cr.get("s") or self._build_description(keyword)))
        category_value = self._normalize_category_id(category_id if category_id is not None else node.get("category_id"))
        resolved_keyword_id = keyword_id if keyword_id is not None else node.get("keyword_id")
        article_style = style if style in self.ARTICLE_STYLE_RULES else self.suggest_title_styles(keyword)[0]

        body = self._run_editorial_segmented_stage2(keyword, node, article_style, strict=False, progress=progress)
        if body is None or not self._passes_editorial_shape(body):
            if progress:
                progress("Fact_Checking", 55, "Segmented draft was weak, retrying stricter section generation")
            body = self._run_editorial_segmented_stage2(keyword, node, article_style, strict=True, progress=progress)

        if body is None or not self._is_usable_stage2_body(body):
            if progress:
                progress("Fact_Checking", 56, "Segmented generation failed, using recovery writer once")
            body = self._run_stage2_recovery_llm(keyword, node, article_style)

        if body is None or not self._is_usable_stage2_body(body):
            if progress:
                progress("Fact_Checking", 57, "Recovery failed, using local emergency article builder")
            body = self._build_article_body_from_plan(keyword, markdown_path, node)

        draft_body = self._normalize_media_blocks(body, markdown_path, keyword)
        draft_body = self._ensure_standard_tail(draft_body, keyword, node)
        draft_content = self._compose_markdown_document(
            keyword,
            title,
            description,
            category_value,
            resolved_keyword_id,
            draft_body,
        )
        draft_markdown_path.write_text(draft_content, encoding="utf-8")
        if progress:
            progress("Fact_Checking", 59, f"Saved draft markdown: {draft_markdown_path.name}")

        final_body = self._normalize_article_voice(draft_body, title, keyword)
        final_body = self._rewrite_references(final_body, title, keyword, category_value)
        final_content = self._compose_markdown_document(
            keyword,
            title,
            description,
            category_value,
            resolved_keyword_id,
            final_body,
        )
        markdown_path.write_text(final_content, encoding="utf-8")
        load_article(markdown_path)
        if progress:
            progress("SEO_Optimizing", 65, f"Rendered final markdown: {markdown_path.name}")
        return markdown_path

    def _run_editorial_segmented_stage2(
        self,
        keyword: str,
        node: dict,
        style: str,
        strict: bool = False,
        progress: ProgressCallback | None = None,
    ) -> str | None:
        cr = node.get("cr", {}) or {}
        sections = self._normalize_planning_sections(cr.get("st", []) or [], keyword)[:6]
        key_points = self._normalize_planning_key_points(cr.get("kp", []) or [], keyword)
        if len(sections) < 4:
            sections = self._planning_sections_from_keyword(keyword, self._infer_query_type(keyword))[:5]

        title = self._normalize_final_title(str(node.get("t", keyword)), keyword)
        summary = str(cr.get("s") or self._build_description(keyword)).strip()
        persona = str(cr.get("author_bio") or self._default_author_bio(keyword)).strip()
        personal_story = str(cr.get("personal_story") or self._default_personal_story(keyword)).strip()
        style_rule = self.ARTICLE_STYLE_RULES.get(style, self.ARTICLE_STYLE_RULES["question"])
        updated_line = f"Last updated: {datetime.now().strftime('%A, %B %d, %Y')}"
        intro = self._build_expert_process_opening(keyword, summary, personal_story)

        if progress:
            mode = "strict retry" if strict else "primary pass"
            progress("Fact_Checking", 46, f"Stage2 {mode}: outline ready with {len(sections)} sections")

        section_blocks: list[str] = []
        prior_context = intro
        total_sections = max(1, len(sections))
        for index, section in enumerate(sections):
            if progress:
                percent = 47 + int((index / total_sections) * 7)
                progress("Fact_Checking", percent, f"Generating section {index + 1}/{len(sections)}: {section[:80]}")
            point = key_points[index] if index < len(key_points) else summary
            must_include = self._section_requirement(index, len(sections), section)
            section_body = self._generate_editorial_section(
                keyword=keyword,
                title=title,
                summary=summary,
                section=section,
                point=point,
                persona=persona,
                prior_context=prior_context,
                style_rule=style_rule,
                must_include=must_include,
                strict=strict,
            )
            if not section_body:
                if progress:
                    progress("Fact_Checking", 47 + int((index / total_sections) * 7), f"Using local fallback for section {index + 1}/{len(sections)}")
                section_body = self._compose_section_paragraph(keyword, section, summary, key_points, index)
            section_body = self._clean_segmented_section_body(section_body)
            section_body = self._repair_section_if_needed(keyword, section_body, index, len(sections))

            media_prefix = ""
            if index == 0:
                media_prefix = f"[IMAGE: {keyword} real process]\n\n"
            if index == min(2, len(sections) - 1):
                media_prefix += f"[YOUTUBE_VIDEO: {keyword} expert explanation real results]\n\n"

            block = f"## {section}\n\n{media_prefix}{section_body.strip()}"
            section_blocks.append(block)
            prior_context = "\n\n".join(section_blocks[-2:])

        if progress:
            progress("Fact_Checking", 54, "Assembling table, action steps, and section transitions")
        joined_sections = "\n\n".join(section_blocks)
        joined_sections = self._ensure_table_exists(keyword, joined_sections)
        joined_sections = self._ensure_action_steps_exist(keyword, joined_sections)

        if progress:
            progress("Fact_Checking", 55, "Generating thick FAQ section")
        faq = self._generate_editorial_faq(keyword, title, summary, persona, strict=strict)
        closing = self._build_editorial_closing(keyword)
        toc_lines = ["## Table of Contents"] + [f"- [{section}](#{self._slugify(section)})" for section in sections]
        toc_lines.append("- [What To Do Next If You Want A Real-World Answer](#what-to-do-next-if-you-want-a-real-world-answer)")
        toc_lines.append("- [Frequently Asked Questions](#frequently-asked-questions)")
        toc_lines.append("- [The Next Step Without Guesswork](#the-next-step-without-guesswork)")

        if progress:
            progress("Fact_Checking", 56, "Finalizing segmented article body")
        body = "\n\n".join(
            [
                "> **Disclaimer:** This content is for general educational purposes only and does not replace individualized professional advice.",
                updated_line,
                "\n".join(toc_lines),
                intro,
                joined_sections,
                faq,
                closing,
            ]
        )
        return body.strip()

    def _normalize_planning_sections(self, raw_sections: Iterable[object], keyword: str) -> list[str]:
        cleaned: list[str] = []
        for raw in raw_sections:
            heading = re.sub(r"\s+", " ", str(raw or "")).strip().strip("#:- ")
            if not heading:
                continue
            lowered = heading.lower()
            if any(token in lowered for token in self.INVALID_SECTION_TOKENS):
                continue
            heading = heading.replace(":", "")
            if heading not in cleaned:
                cleaned.append(heading)
        if len(cleaned) >= 4:
            return cleaned[:6]
        return self._planning_sections_from_keyword(keyword, self._infer_query_type(keyword))

    def _normalize_planning_key_points(self, raw_points: Iterable[object], keyword: str) -> list[str]:
        cleaned: list[str] = []
        for raw in raw_points:
            point = re.sub(r"\s+", " ", str(raw or "")).strip()
            if point and point not in cleaned:
                cleaned.append(point)
        if cleaned:
            return cleaned[:6]
        return self._planning_key_points_from_keyword(keyword, self._infer_query_type(keyword))

    def _infer_query_type(self, keyword: str) -> str:
        parent = getattr(super(), "_infer_query_type", None)
        if callable(parent):
            try:
                return str(parent(keyword))
            except Exception:
                pass
        lowered = keyword.lower()
        if any(token in lowered for token in (" vs ", " versus ", "compare", "comparison", "better than")):
            return "comparison"
        if any(token in lowered for token in ("symptom", "cause", "why", "pain", "after eating", "high", "low")):
            return "symptom"
        if any(token in lowered for token in ("celebrity", "before and after", "transformation")):
            return "celebrity"
        return "review"

    def _heading_subject(self, keyword: str) -> str:
        parent = getattr(super(), "_heading_subject", None)
        if callable(parent):
            try:
                return str(parent(keyword))
            except Exception:
                pass
        return re.sub(r"\s+", " ", keyword).strip().strip(" ?") or "this topic"

    def _planning_sections_from_keyword(self, keyword: str, query_type: str) -> list[str]:
        parent = getattr(super(), "_planning_sections_from_keyword", None)
        if callable(parent):
            try:
                return list(parent(keyword, query_type))
            except Exception:
                pass
        phrase = self._heading_subject(keyword)
        if query_type == "comparison":
            return [
                f"What {phrase} Actually Looks Like Side By Side",
                "Where The Tradeoff Gets Real",
                "Who Usually Fits Each Option Better",
                "The Downside That Changes The Decision",
                "What To Check Before You Choose",
            ]
        if query_type == "symptom":
            return [
                f"What {phrase} May Be Trying To Tell You",
                "Why This Pattern Gets Missed At First",
                "The Clues That Matter More Than People Think",
                "When This Stops Being Something To Brush Off",
                "What To Do Next Instead Of Guessing",
            ]
        return [
            f"The Real Process Behind {phrase}",
            "Why The First Result Can Be Misleading",
            "The Tradeoff Most People Miss",
            "Who Is Most Likely To Regret It",
            "What To Do Next Before You Commit",
        ]

    def _planning_key_points_from_keyword(self, keyword: str, query_type: str) -> list[str]:
        parent = getattr(super(), "_planning_key_points_from_keyword", None)
        if callable(parent):
            try:
                return list(parent(keyword, query_type))
            except Exception:
                pass
        phrase = self._heading_subject(keyword)
        return [
            f"The useful answer on {phrase} depends on fit, friction, and what changes after the first few weeks.",
            "The real-world process matters more than the clean promise in the headline.",
            "Readers need concrete tradeoffs, warning signs, and a next-step plan.",
            "A good decision should be based on sustainability, not only the first visible result.",
        ]

    def _default_author_bio(self, keyword: str) -> str:
        parent = getattr(super(), "_default_author_bio", None)
        if callable(parent):
            try:
                return str(parent(keyword))
            except Exception:
                pass
        return "I write evidence-aware health and wellness explainers that translate search hype into practical, real-world decisions."

    def _default_personal_story(self, keyword: str) -> str:
        parent = getattr(super(), "_default_personal_story", None)
        if callable(parent):
            try:
                return str(parent(keyword))
            except Exception:
                pass
        phrase = self._heading_subject(keyword)
        return f"I kept seeing {phrase} framed like a clean shortcut, but the more useful question is what actually happens once the process meets real life."

    def _build_description(self, keyword: str) -> str:
        parent = getattr(super(), "_build_description", None)
        if callable(parent):
            try:
                return str(parent(keyword))
            except Exception:
                pass
        return self._truncate_description(f"A real-world look at {keyword}, including process, tradeoffs, side effects, cost, and what to check before acting.")

    def _call_gemini_with_retry(self, prompt: str, attempts: int = 2) -> str | None:
        caller = getattr(self, "_call_gemini", None)
        if not callable(caller):
            return None
        for _ in range(max(1, attempts)):
            try:
                text = caller(prompt)
            except Exception:
                text = None
            if text and str(text).strip():
                return str(text).strip()
        return None

    def _extract_markdown_body(self, text: str) -> str:
        parent = getattr(super(), "_extract_markdown_body", None)
        if callable(parent):
            try:
                return str(parent(text))
            except Exception:
                pass
        text = str(text or "").strip()
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def _clean_segmented_section_body(self, text: str) -> str:
        text = self._extract_markdown_body(text)
        text = re.sub(r"^##\s+.*\n+", "", text, flags=re.MULTILINE).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _compose_section_paragraph(self, keyword: str, section: str, summary: str, key_points: list[str], index: int) -> str:
        point = key_points[index % len(key_points)] if key_points else summary
        return (
            f"In practice, this part of {keyword} is where the simple answer starts to get more useful. {point} "
            "The reader should not only ask whether the idea sounds promising, but what changes after the first few days, what friction appears, and what would make the plan hard to sustain.\n\n"
            "A realistic scenario usually looks less polished than the headline. The first week may feel clear because motivation is high. By the second or third week, the real test is whether the routine still works with normal meals, work stress, cost, symptoms, travel, or social pressure. That turning point is where a good decision becomes more practical than a good promise."
        )

    def _build_expert_process_opening(self, keyword: str, summary: str, personal_story: str) -> str:
        search_line = (
            f"Searching {keyword} usually means the reader is not looking for a dictionary definition. "
            "They are trying to decide whether the promise holds up once real life gets involved."
        )
        short_version = f"Here is the short version: {summary}"
        return f"{personal_story.strip()}\n\n{search_line}\n\n{short_version}".strip()

    def _section_requirement(self, index: int, total: int, section: str) -> str:
        lowered = section.lower()
        if index == 0 or "process" in lowered or "step" in lowered or "actually happens" in lowered:
            return "Include a process breakdown with clear steps, checkpoints, or stages."
        if index == 1 or "miss" in lowered or "disappoint" in lowered or "regret" in lowered:
            return "Include a realistic scenario with timeline, friction, turning point, and result."
        if index == 2 or "tradeoff" in lowered or "compare" in lowered or "cost" in lowered:
            return "Include a useful markdown comparison table if it fits the section."
        if index >= total - 1 or "next" in lowered or "check" in lowered:
            return "Include concrete action steps or a practical decision checklist."
        return "Use expert-process detail, concrete examples, and search-intent judgment."

    def _generate_editorial_section(
        self,
        keyword: str,
        title: str,
        summary: str,
        section: str,
        point: str,
        persona: str,
        prior_context: str,
        style_rule: str,
        must_include: str,
        strict: bool,
    ) -> str | None:
        strict_note = "Be stricter than normal: no thin paragraphs, no generic caution filler, no textbook structure. " if strict else ""
        prompt = (
            "Write one thick markdown section for a YMYL editorial article. Return only the body of this section, not the H2 heading. "
            "The target feel is a real, unfiltered expert-process article, similar to a practitioner walking the reader through what actually happens. "
            "Use concrete details, process language, timeline, friction, and practical judgment. "
            "Do not invent fake private client records, fake studies, fake doctors, fake clinics, or fake credentials. Composite scenarios are allowed if clearly realistic and not presented as verified private data. "
            "Avoid academic, clinical-review, abstract, or textbook phrasing. "
            "Write 2 to 5 substantial paragraphs, or 1 to 2 paragraphs plus a strong list/table if that better fits the section. "
            f"{strict_note}"
            f"Required section element: {must_include}\n\n"
            f"Article title: {title}\n"
            f"Keyword: {keyword}\n"
            f"Editorial summary: {summary}\n"
            f"Author persona: {persona}\n"
            f"Section heading: {section}\n"
            f"Section key point: {point}\n"
            f"Article style rule: {style_rule}\n"
            f"Recent context:\n{prior_context}\n\n"
            "Return plain markdown only."
        )
        return self._call_gemini_with_retry(prompt, attempts=2)

    def _repair_section_if_needed(self, keyword: str, body: str, index: int, total: int) -> str:
        repaired = body.strip()
        if index == 1 and not re.search(r"\b(week|month|day|client|reader|scenario|timeline|turning point)\b", repaired, re.IGNORECASE):
            repaired += "\n\nA realistic reader scenario makes the point clearer. In week one, the change can look simple because the first friction has not arrived yet. By week three or four, the hidden cost usually appears: planning, symptoms, money, schedule pressure, or the realization that the old habit was solving a real emotional or logistical problem. The turning point is not the first result. It is whether the person can adjust the system without abandoning the goal."
        if index >= total - 1 and not re.search(r"^\s*\d+\.\s+", repaired, re.MULTILINE):
            repaired += self._fallback_action_steps(keyword)
        return repaired

    def _ensure_table_exists(self, keyword: str, text: str) -> str:
        if "|" in text and re.search(r"\|\s*---", text):
            return text
        table = (
            f"\n\n| Decision Point | What To Look For | Why It Changes The Outcome |\n"
            "|---|---|---|\n"
            f"| Fit | Whether {keyword} matches the reader's actual problem | A poor fit turns a promising idea into frustration |\n"
            "| Friction | Cost, time, symptoms, access, or daily routine pressure | Friction is usually what breaks consistency |\n"
            "| Tracking | What changes across weeks, not just the first reaction | Early excitement can hide a weak long-term plan |\n"
            "| Exit plan | What happens when the plan stops, changes, or becomes harder | Maintenance decides whether the result survives |\n"
        )
        return text.rstrip() + table

    def _ensure_action_steps_exist(self, keyword: str, text: str) -> str:
        if re.search(r"^##\s+What To Do", text, flags=re.MULTILINE):
            return text
        return text.rstrip() + self._fallback_action_steps(keyword)

    def _ensure_action_guide(self, body: str, keyword: str) -> str:
        """Override parent behavior so the final contract sees a real What To Do H2."""
        if re.search(r"^##\s+What To Do", body, flags=re.MULTILINE):
            return body
        return body.rstrip() + self._fallback_action_steps(keyword)

    def _fallback_action_steps(self, keyword: str) -> str:
        subject = self._heading_subject(keyword)
        return (
            f"\n\n## What To Do Next If You Want A Real-World Answer\n\n"
            f"A useful action guide for {subject} should turn the promise into a decision you can actually check. Use these steps before treating the idea like a finished plan.\n\n"
            "1. **Define the real decision.** Write down whether you are trying to solve results, side effects, cost, access, consistency, or confusion.\n"
            "2. **Track the friction for two weeks.** Watch the moments where the plan becomes hard, not only the moments where it seems to work.\n"
            "3. **Compare the tradeoff before escalating.** Ask whether the expected benefit is worth the time, money, symptoms, or routine change required.\n"
            "4. **Get qualified input when the topic touches health or medication.** Do not turn a search result into a personal protocol without professional review."
        )

    def _generate_editorial_faq(self, keyword: str, title: str, summary: str, persona: str, strict: bool) -> str:
        strict_note = "Every answer must be at least 100 words and must include a concrete example or decision point. " if strict else ""
        prompt = (
            "Write a markdown FAQ section for a high-CTR YMYL editorial article. "
            "Return the heading `## Frequently Asked Questions` followed by at least 4 H3 questions and substantial answers. "
            "Questions must sound like real People Also Ask, social-search, comparison, regret, side-effect, cost, or next-step queries. "
            "Do not write generic glossary questions unless they are truly central to the keyword. "
            "Each answer should normally be 100 to 180 words, specific, practical, and close to the original search intent. "
            "Do not invent private data, fake studies, fake doctors, or fake credentials. "
            f"{strict_note}\n"
            f"Article title: {title}\n"
            f"Keyword: {keyword}\n"
            f"Summary: {summary}\n"
            f"Author persona: {persona}\n"
            "Return plain markdown only."
        )
        text = self._call_gemini_with_retry(prompt, attempts=2)
        if text:
            faq = self._extract_markdown_body(text)
            if self._faq_is_thick(faq):
                return faq.strip()
        return self._fallback_faq(keyword)

    def _faq_is_thick(self, faq: str) -> bool:
        questions = re.findall(r"^###\s+.+", faq, flags=re.MULTILINE)
        if len(questions) < 4:
            return False
        parts = re.split(r"^###\s+.+$", faq, flags=re.MULTILINE)[1:]
        if len(parts) < 4:
            return False
        return all(len(re.findall(r"\b\w+\b", answer)) >= 80 for answer in parts[:4])

    def _fallback_faq(self, keyword: str) -> str:
        subject = self._heading_subject(keyword)
        return f"""## Frequently Asked Questions

### Does {subject} actually work in real life

The honest answer is that it depends on what someone means by `work`. A result that looks impressive in the first few weeks can still fail if the routine is expensive, uncomfortable, confusing, or impossible to maintain. The better way to judge {subject} is to track both the visible outcome and the hidden friction. Look at what changes after the first excitement fades: energy, appetite, symptoms, cost, social life, consistency, and whether the person can keep the core behavior without feeling trapped by it.

### Who is most likely to regret {subject}

The people most likely to regret {subject} are usually the ones who start with a result fantasy but no plan for the tradeoffs. That might mean no budget plan, no symptom plan, no maintenance plan, or no understanding of what the process actually requires. Regret can also show up when someone copies a viral version of the idea without checking whether it fits their health background, schedule, preferences, or risk tolerance. A good decision starts by asking what could make the plan fail, not just what could make it work.

### What should I track before deciding whether to continue

Track the parts that reveal whether the process is sustainable. The scale or headline outcome is only one signal. Watch your energy, sleep, cravings, mood, digestion, spending, and the moments where the plan feels hardest to follow. A two-week pattern tells you more than a single good day. If the plan touches medication, medical nutrition, supplements, or a health condition, bring those notes to a qualified professional instead of trying to interpret every signal alone.

### What is the next step if I am still unsure

The next step is to slow the decision down and turn it into a checklist. First, define the outcome you want. Second, list the friction you are willing and unwilling to tolerate. Third, compare the plan against your actual life rather than the best version shown online. Fourth, get qualified input if the topic touches diagnosis, medication, symptoms, labs, or long-term health. That sequence keeps the decision practical and reduces the chance of chasing a promise that was never built for your situation."""

    def _build_editorial_closing(self, keyword: str) -> str:
        return (
            "## The Next Step Without Guesswork\n\n"
            f"The useful move after searching {keyword} is not to copy the most confident claim. It is to translate the claim into a real decision. Ask what problem you are trying to solve, what friction you can realistically tolerate, and what evidence or professional input you need before acting. A strong plan should make the next step clearer, not just make the promise louder."
        )

    def _passes_editorial_shape(self, body: str) -> bool:
        if not self._is_usable_stage2_body(body):
            return False
        if "## Frequently Asked Questions" not in body:
            return False
        if not self._faq_is_thick(body.split("## Frequently Asked Questions", 1)[-1]):
            return False
        if "|" not in body or not re.search(r"\|\s*---", body):
            return False
        if not re.search(r"^##\s+What To Do", body, flags=re.MULTILINE):
            return False
        return True


def run_cli() -> int:
    parser = argparse.ArgumentParser(description="Run editorial segmented article generation")
    parser.add_argument("keyword", help="Input search keyword")
    parser.add_argument("--workspace", default=".", help="Workspace root containing references/prompts")
    parser.add_argument("--output", default=".", help="Output directory for generated markdown")
    parser.add_argument("--category", type=int, default=1, help="Article category_id")
    parser.add_argument("--keyword-id", type=int, default=None, help="Optional CMS keyword_id")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    controller = EditorialPipelineController(workspace, output_root=output)
    result: PipelineResult = controller.run_generation(
        args.keyword,
        category_id=args.category,
        keyword_id=args.keyword_id,
    )
    preview_path = render_preview_html(result.markdown_path)
    article = load_article(result.markdown_path)
    print(f"Markdown: {result.markdown_path}")
    print(f"Preview: {preview_path}")
    print(f"Title: {article.get('title')}")
    print(f"Category: {article.get('category_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
