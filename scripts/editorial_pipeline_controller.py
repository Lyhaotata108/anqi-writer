#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Editorial segmented generation controller.

This controller makes Stage 2 section-by-section by default so the finished
article is closer to a high-performing decision article: direct answer, real
friction, realistic scenario, comparison table, action guide, thick FAQ, and a
clear next step.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
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
        "market landscape",
        "clinical pipeline",
        "pipeline data",
        "phase iii",
        "fda approved",
        "receptor activation",
        "dual-hormone targeting",
        "metabolic repair",
    )

    MEDICATION_TOKENS = (
        "mounjaro",
        "tirzepatide",
        "ozempic",
        "semaglutide",
        "wegovy",
        "zbound",
        "glp-1",
        "glp 1",
        "metformin",
        "weight loss drug",
        "weight loss medication",
        "prescription weight loss",
    )

    UNSUPPORTED_CLAIM_PATTERNS = (
        r"\bphase\s+(i|ii|iii|1|2|3)\b",
        r"\bfda[-\s]?approved\b",
        r"\bfda\s+cleared\b",
        r"\btrial\s+data\b",
        r"\bclinical\s+pipeline\b",
        r"\bmarket\s+availability\b",
        r"\b\d+(?:\.\d+)?\s?%\s*(?:average|body|weight|reduction|loss)\b",
    )

    def run_stage1_1(self, keyword: str, progress: ProgressCallback | None = None) -> tuple[dict, Path]:
        """Run Stage 1-1, but do not kill the batch if Gemini is temporarily unavailable."""
        try:
            return super().run_stage1_1(keyword, progress)
        except RuntimeError as error:
            if "Stage 1-1" not in str(error):
                raise
            if progress:
                progress("Pending", 12, "Stage 1-1 Gemini failed; using local fallback expansion")
            slug = self._slugify(keyword)
            payload = self._build_stage1_1_fallback(keyword)
            path = self.output_root / f"ui_{slug}.stage1_1.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload, path

    def run_stage1_2(
        self,
        keyword: str,
        stage1_1: dict,
        category_id: int | None = None,
        keyword_id: int | None = None,
        progress: ProgressCallback | None = None,
    ) -> tuple[dict, Path]:
        """Run Stage 1-2, with a local outline fallback for batch stability."""
        try:
            return super().run_stage1_2(keyword, stage1_1, category_id, keyword_id, progress)
        except RuntimeError as error:
            if "Stage 1-2" not in str(error):
                raise
            if progress:
                progress("Drafting", 30, "Stage 1-2 Gemini failed; using local fallback outline")
            slug = self._slugify(keyword)
            payload = self._build_stage1_2_fallback(keyword, category_id=category_id, keyword_id=keyword_id)
            path = self.output_root / f"ui_{slug}.stage1_2.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload, path

    def _build_stage1_1_fallback(self, keyword: str) -> dict:
        phrase = self._heading_subject(keyword)
        return {
            "qs": [
                {
                    "q": keyword,
                    "i": f"The searcher wants a practical, real-world answer about {phrase}, including results, tradeoffs, risks, and what to do next.",
                    "tm": "false",
                    "ymyl_level": True,
                }
            ],
            "sq": keyword,
            "tm": "false",
            "ymyl_level": True,
            "language": "English",
            "fallback": True,
        }

    def _build_stage1_2_fallback(self, keyword: str, category_id: int | None = None, keyword_id: int | None = None) -> dict:
        query_type = self._infer_query_type(keyword)
        node = {
            "t": self._planning_title_from_keyword(keyword, query_type),
            "mty": "Semantic",
            "cs": {"ty": "Editorial Desk", "ac": "US", "ar": "", "al": ""},
            "category_id": self._normalize_category_id(category_id),
            "cr": {
                "tl": "Keep the piece practical, decision-led, and careful on YMYL claims.",
                "s": self._planning_summary_from_keyword(keyword, query_type),
                "wc": 2200,
                "st": self._planning_sections_from_keyword(keyword, query_type),
                "kp": self._planning_key_points_from_keyword(keyword, query_type),
                "af": "The first 120 words must answer the query directly, name the main tradeoff, and tell the reader what to check before acting.",
                "gfm": {"lsr": True},
                "author_bio": self._default_author_bio(keyword),
                "personal_story": self._default_personal_story(keyword),
            },
        }
        if keyword_id is not None:
            node["keyword_id"] = keyword_id
        return {
            "dsq": [
                {
                    "q": keyword,
                    "i": f"The searcher wants a real-world editorial answer for {keyword}, not a generic explainer.",
                    "mt": [node],
                }
            ],
            "fallback": True,
        }

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
            progress("Fact_Checking", 45, "Rendering Stage 2 with viral decision structure")

        slug = self._slugify(keyword)
        markdown_path = self.output_root / f"ui_{slug}.md"
        draft_markdown_path = self.output_root / f"ui_{slug}.draft.md"
        node = self._select_best_stage2_node(keyword, stage1_2)
        node = self._sanitize_stage2_node_for_viral_style(keyword, node)
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
        final_body = self._repair_viral_contract_after_parent_normalization(final_body, keyword)
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
        summary = self._sanitize_summary(str(cr.get("s") or self._build_description(keyword)).strip(), keyword)
        persona = str(cr.get("author_bio") or self._default_author_bio(keyword)).strip()
        personal_story = self._sanitize_personal_story(str(cr.get("personal_story") or self._default_personal_story(keyword)).strip(), keyword)
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
            section_body = self._remove_unsupported_claims(section_body, keyword)
            section_body = self._repair_section_if_needed(keyword, section_body, index, len(sections))

            media_prefix = ""
            if index == 0:
                media_prefix = f"[IMAGE: {keyword} real decision]\n\n"
            if index == min(2, len(sections) - 1):
                media_prefix += f"[YOUTUBE_VIDEO: {keyword} real-world decision side effects cost]\n\n"

            block = f"## {section}\n\n{media_prefix}{section_body.strip()}"
            section_blocks.append(block)
            prior_context = "\n\n".join(section_blocks[-2:])

        if progress:
            progress("Fact_Checking", 54, "Assembling comparison table and action guide")
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

    def _sanitize_stage2_node_for_viral_style(self, keyword: str, node: dict) -> dict:
        node = dict(node)
        cr = dict(node.get("cr", {}) or {})
        query_type = self._infer_query_type(keyword)
        if self._is_medication_keyword(keyword):
            node["t"] = self._planning_title_from_keyword(keyword, query_type)
            cr["s"] = self._planning_summary_from_keyword(keyword, query_type)
            cr["st"] = self._planning_sections_from_keyword(keyword, query_type)
            cr["kp"] = self._planning_key_points_from_keyword(keyword, query_type)
            cr["personal_story"] = self._default_personal_story(keyword)
            cr["author_bio"] = self._default_author_bio(keyword)
        else:
            cr["s"] = self._sanitize_summary(str(cr.get("s") or self._build_description(keyword)), keyword)
            cr["personal_story"] = self._sanitize_personal_story(str(cr.get("personal_story") or self._default_personal_story(keyword)), keyword)
        node["cr"] = cr
        return node

    def _is_medication_keyword(self, keyword: str) -> bool:
        lowered = keyword.lower()
        return any(token in lowered for token in self.MEDICATION_TOKENS)

    def _normalize_final_title(self, title: str, keyword: str) -> str:
        parent = getattr(super(), "_normalize_final_title", None)
        try:
            cleaned = str(parent(title, keyword)) if callable(parent) else str(title or keyword)
        except Exception:
            cleaned = str(title or keyword)
        lowered = cleaned.lower()
        bad_tokens = (
            "clinical evidence",
            "effectiveness",
            "analyzed",
            "explained",
            "research review",
            "market",
            "pipeline",
            "phase iii",
            "fda",
        )
        if self._is_medication_keyword(keyword) and any(token in lowered for token in bad_tokens):
            return self._planning_title_from_keyword(keyword, self._infer_query_type(keyword))
        cleaned = cleaned.replace(":", "")
        return cleaned.strip() or self._planning_title_from_keyword(keyword, self._infer_query_type(keyword))

    def _sanitize_summary(self, summary: str, keyword: str) -> str:
        text = re.sub(r"\s+", " ", str(summary or "")).strip()
        text = re.sub(r"^The short answer is that\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^Here is the short version:\s*", "", text, flags=re.IGNORECASE)
        text = self._remove_unsupported_claims(text, keyword)
        if self._is_medication_keyword(keyword):
            phrase = self._heading_subject(keyword)
            return f"{phrase} can still look compelling, but the useful decision depends on fit, side effects, access, cost, adherence, and what happens after the first wave of progress slows down."
        if not text:
            return self._build_description(keyword)
        return text

    def _sanitize_personal_story(self, story: str, keyword: str) -> str:
        text = re.sub(r"\s+", " ", str(story or "")).strip()
        bad_markers = (
            "clinical pipeline data",
            "market data",
            "phase iii",
            "fda-approved",
            "biotech journalist",
            "pharmaceutical market analyst",
        )
        if not text or any(marker in text.lower() for marker in bad_markers) or self._is_medication_keyword(keyword):
            return self._default_personal_story(keyword)
        return text

    def _remove_unsupported_claims(self, text: str, keyword: str) -> str:
        if not self._is_medication_keyword(keyword):
            return text
        cleaned = str(text or "")
        for pattern in self.UNSUPPORTED_CLAIM_PATTERNS:
            cleaned = re.sub(pattern, "source-dependent claim", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(undisputed|definitive|guaranteed|biological supremacy|nothing matches)\b", "potential", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bdrinking it\b|\bdrink it\b|\bdrank it\b", "using the medication", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(two|three|2|3)\s+times\s+a\s+day\b", "on the prescribed schedule", cleaned, flags=re.IGNORECASE)
        return cleaned

    def _normalize_planning_sections(self, raw_sections: Iterable[object], keyword: str) -> list[str]:
        if self._is_medication_keyword(keyword):
            return self._planning_sections_from_keyword(keyword, self._infer_query_type(keyword))
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
        if self._is_medication_keyword(keyword):
            return self._planning_key_points_from_keyword(keyword, self._infer_query_type(keyword))
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

    def _planning_title_from_keyword(self, keyword: str, query_type: str) -> str:
        phrase = self._format_title_subject(self._heading_subject(keyword))
        if self._is_medication_keyword(keyword):
            return f"{phrase} Still Looks Powerful But This Is The Part People Miss"
        parent = getattr(super(), "_planning_title_from_keyword", None)
        if callable(parent):
            try:
                return str(parent(keyword, query_type))
            except Exception:
                pass
        return f"I Looked Closely At {phrase} Here Is What Actually Matters"

    def _format_title_subject(self, subject: str) -> str:
        text = re.sub(r"\s+", " ", str(subject or "")).strip(" -?")
        if not text:
            return "This Topic"
        minor = {"a", "an", "and", "as", "at", "by", "for", "in", "is", "of", "on", "or", "the", "to", "vs", "with"}
        words = []
        for i, word in enumerate(text.lower().split()):
            if i > 0 and word in minor:
                words.append(word)
            else:
                words.append(word[:1].upper() + word[1:])
        return " ".join(words)

    def _planning_summary_from_keyword(self, keyword: str, query_type: str) -> str:
        phrase = self._heading_subject(keyword)
        if self._is_medication_keyword(keyword):
            return f"{phrase} can still be a serious weight-loss option for some people, but the real decision is not just whether it works. It is whether the side effects, prescription access, refill reliability, insurance friction, cost, and long-term maintenance plan make sense for the person considering it."
        parent = getattr(super(), "_planning_summary_from_keyword", None)
        if callable(parent):
            try:
                return str(parent(keyword, query_type))
            except Exception:
                pass
        return f"The useful answer on {phrase} depends on fit, friction, cost, consistency, and what happens after the first promising impression fades."

    def _planning_sections_from_keyword(self, keyword: str, query_type: str) -> list[str]:
        phrase = self._format_title_subject(self._heading_subject(keyword))
        if self._is_medication_keyword(keyword):
            return [
                f"The Short Answer On {phrase} Is Strong But Conditional",
                "Where The Promise Still Holds Up In Real Life",
                "The Friction That Usually Shows Up After The First Month",
                "The Case That Shows Why The Decision Is Not Just About Results",
                "The Practical Comparison Most People Actually Need",
                "What To Do Before You Choose This Path",
            ]
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
        phrase = self._heading_subject(keyword)
        if self._is_medication_keyword(keyword):
            return [
                f"The real decision around {phrase} is not raw hype. It is fit, tolerance, access, cost, and maintenance.",
                "The first month can feel convincing, but the harder test begins when side effects, refills, and routine pressure show up.",
                "A medication choice should be discussed with a qualified clinician, especially when other conditions or prescriptions are involved.",
                "Insurance friction and refill reliability can change the practical value of a medication even when the clinical promise sounds strong.",
                "The better article should help the reader ask smarter questions, not tell them what to take.",
            ]
        parent = getattr(super(), "_planning_key_points_from_keyword", None)
        if callable(parent):
            try:
                return list(parent(keyword, query_type))
            except Exception:
                pass
        return [
            f"The useful answer on {phrase} depends on fit, friction, and what changes after the first few weeks.",
            "The real-world process matters more than the clean promise in the headline.",
            "Readers need concrete tradeoffs, warning signs, and a next-step plan.",
            "A good decision should be based on sustainability, not only the first visible result.",
        ]

    def _default_author_bio(self, keyword: str) -> str:
        if self._is_medication_keyword(keyword):
            return "Evidence-Aware Wellness Editor"
        parent = getattr(super(), "_default_author_bio", None)
        if callable(parent):
            try:
                return str(parent(keyword))
            except Exception:
                pass
        return "Evidence-Aware Wellness Editor"

    def _default_personal_story(self, keyword: str) -> str:
        phrase = self._heading_subject(keyword)
        if self._is_medication_keyword(keyword):
            return f"I would not judge {phrase} by the loudest success story. I would judge it by what happens after the first month, when side effects, refills, insurance, appetite changes, and daily routine start making the decision less simple."
        parent = getattr(super(), "_default_personal_story", None)
        if callable(parent):
            try:
                return str(parent(keyword))
            except Exception:
                pass
        return f"I kept seeing {phrase} framed like a clean shortcut, but the more useful question is what actually happens once the process meets real life."

    def _build_description(self, keyword: str) -> str:
        if self._is_medication_keyword(keyword):
            return self._truncate_description(f"A real-world decision guide to {keyword}, including fit, side effects, cost, access, insurance friction, and what to ask before choosing it.")
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
        if self._is_medication_keyword(keyword):
            return self._compose_medication_section_paragraph(keyword, section, summary, key_points, index)
        point = key_points[index % len(key_points)] if key_points else summary
        return (
            f"In practice, this part of {keyword} is where the simple answer starts to get more useful. {point} "
            "The reader should not only ask whether the idea sounds promising, but what changes after the first few days, what friction appears, and what would make the plan hard to sustain.\n\n"
            "A realistic scenario usually looks less polished than the headline. The first week may feel clear because motivation is high. By the second or third week, the real test is whether the routine still works with normal meals, work stress, cost, symptoms, travel, or social pressure. That turning point is where a good decision becomes more practical than a good promise."
        )

    def _compose_medication_section_paragraph(self, keyword: str, section: str, summary: str, key_points: list[str], index: int) -> str:
        phrase = self._heading_subject(keyword)
        blocks = [
            (
                f"The honest answer on {phrase} is that it can look like one of the stronger options in the weight-loss conversation, but that does not automatically make it the best choice for every reader. The useful question is not just whether people can lose weight on it. The useful question is whether the person considering it can handle the prescription process, side effects, follow-up, cost, access, and maintenance plan without turning the first good month into a long-term struggle.\n\n"
                "That distinction matters because medication decisions get messy fast. A clean headline can make the result sound simple, but real life adds refill timing, nausea or constipation, dose changes, insurance approvals, and the possibility of regaining weight if the broader plan is weak. This article should help a reader prepare better questions for a qualified clinician, not self-prescribe from a search result."
            ),
            (
                f"Where {phrase} still holds up is in the way it can change appetite pressure for some people who have not been able to manage weight through willpower alone. That is the part readers usually care about first: less food noise, more control around portions, and a feeling that the body is not fighting every meal. But the result is only useful if the person can stay with the plan safely and consistently.\n\n"
                "The part that gets overstated is the idea that the medication carries the whole outcome by itself. Food quality, protein intake, muscle preservation, sleep, activity, medical history, and follow-up still matter. A prescription can make the process easier for some people, but it does not erase the need for a maintenance system."
            ),
            (
                "The real-life friction usually shows up after the first month, not on day one. At first, the excitement of lower appetite can make the choice feel obvious. Then the normal problems arrive: a refill is delayed, the dose increase feels rough, constipation becomes annoying, a restaurant meal feels different, or the monthly cost suddenly becomes harder to justify.\n\n"
                "That is why the first checkpoint should not be only the number on the scale. A better checkpoint is whether the person can live with the routine. If the medication creates constant anxiety around side effects, payment, or access, the practical value changes even when the weight trend looks promising."
            ),
            self._build_medication_case_study(keyword).split("\n\n", 1)[-1],
            (
                "A practical comparison should stay focused on what a reader can actually verify before making a decision. The question is not which option sounds most powerful in a headline. The question is which option fits the person's medical situation, risk tolerance, insurance reality, and ability to keep going when the early momentum slows down.\n\n"
                "Use the table below as a discussion starter, not a prescription. A qualified clinician can help interpret medical history, other medications, and individual risk factors in a way a general article cannot."
            ),
            (
                f"Before choosing {phrase}, slow the decision down and turn it into a checklist. A strong plan should make the next step clearer, not just make the promise louder.\n\n"
                "The safest next move is to collect the practical facts: what your insurance will cover, what side effects you are willing to tolerate, how follow-up will work, what happens if access is interrupted, and what maintenance habits will support the result if appetite control changes."
            ),
        ]
        return blocks[index] if index < len(blocks) else blocks[-1]

    def _build_expert_process_opening(self, keyword: str, summary: str, personal_story: str) -> str:
        if self._is_medication_keyword(keyword):
            phrase = self._heading_subject(keyword)
            return (
                f"{personal_story.strip()}\n\n"
                f"The short answer is this: {phrase} can still be a serious option for some people, but it is not a magic ranking problem where the strongest headline automatically wins. The real decision lives in the unglamorous details: side effects, prescription access, refill reliability, insurance coverage, cost, medical history, and whether there is a plan for maintenance after the first wave of progress slows down."
            ).strip()
        search_line = (
            f"The real question behind {keyword} is not the dictionary definition. "
            "It is whether the promise still holds up once normal life gets involved."
        )
        return f"{personal_story.strip()}\n\n{search_line}\n\nThe short answer: {summary}".strip()

    def _section_requirement(self, index: int, total: int, section: str) -> str:
        lowered = section.lower()
        if index == 0 or "short answer" in lowered:
            return "Give the direct verdict first, then name the main friction or limitation."
        if "case" in lowered or index == 3:
            return "Include a realistic composite scenario with timeline, friction, turning point, and lesson."
        if "comparison" in lowered or index == 4:
            return "Include a useful markdown comparison table if it fits the section."
        if index >= total - 1 or "what to do" in lowered or "check" in lowered:
            return "Include concrete action steps or a practical decision checklist."
        return "Use reader-first decision detail, concrete examples, and search-intent judgment."

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
        medication_note = ""
        if self._is_medication_keyword(keyword):
            medication_note = (
                "Medication-specific constraints: do not invent FDA approvals, trial names, exact percentages, market dates, or unsupported superiority claims. "
                "Do not describe an injectable medication as something a person drinks, eats, or takes like a supplement. "
                "Focus on real-world decision friction: prescription access, titration, side effects, refill reliability, insurance coverage, cost, follow-up, and maintenance. "
                "Do not tell the reader to start, stop, change, or choose a medication; tell them what to discuss with a qualified clinician. "
            )
        prompt = (
            "Write one thick markdown section for a high-performing YMYL decision article. Return only the body of this section, not the H2 heading. "
            "The target feel is a serious human editor walking the reader through what actually happens, not a clinical review or market report. "
            "Use concrete details, friction, timeline, tradeoffs, and practical judgment. "
            "Do not invent fake private client records, fake studies, fake doctors, fake clinics, or fake credentials. Composite scenarios are allowed if clearly realistic and not presented as verified private data. "
            "Avoid academic, clinical-review, abstract, investor-note, or textbook phrasing. "
            "Write 2 to 5 substantial paragraphs, or 1 to 2 paragraphs plus a strong list/table if that better fits the section. "
            f"{medication_note}"
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
        if self._is_medication_keyword(keyword):
            repaired = self._remove_unsupported_claims(repaired, keyword)
        if index == 3 and not re.search(r"\b(week|month|refill|dose|side effect|insurance|coverage|turning point|follow-up)\b", repaired, re.IGNORECASE):
            repaired = self._build_medication_case_study(keyword).split("\n\n", 1)[-1] if self._is_medication_keyword(keyword) else repaired
        if index >= total - 1 and not re.search(r"^\s*\d+\.\s+", repaired, re.MULTILINE):
            repaired += self._fallback_action_steps(keyword)
        return repaired

    def _ensure_table_exists(self, keyword: str, text: str) -> str:
        if "|" in text and re.search(r"\|\s*---", text):
            return text
        if self._is_medication_keyword(keyword):
            table = (
                "\n\n| Decision Point | What To Check | Why It Matters |\n"
                "|---|---|---|\n"
                "| Fit | Whether your medical history and current medications make the option appropriate to discuss with a clinician | A strong headline does not equal a safe personal fit |\n"
                "| Side effects | How you would handle nausea, constipation, appetite changes, or dose adjustments | Tolerability often decides whether the plan survives normal life |\n"
                "| Access | Prescription path, refill reliability, pharmacy availability, and follow-up schedule | Interrupted access can turn a promising plan into a stressful one |\n"
                "| Cost | Insurance coverage, prior authorization, coupon limits, and out-of-pocket risk | A plan that is unaffordable is not a durable plan |\n"
                "| Maintenance | Food, protein, resistance training, sleep, and rebound planning | Long-term results need more than appetite suppression |\n"
            )
            return text.rstrip() + table
        table = (
            f"\n\n| Decision Point | What To Look For | Why It Changes The Outcome |\n"
            "|---|---|---|\n"
            f"| Fit | Whether {keyword} matches the reader's actual problem | A poor fit turns a promising idea into frustration |\n"
            "| Friction | Cost, time, symptoms, access, or daily routine pressure | Friction is usually what breaks consistency |\n"
            "| Tracking | What changes across weeks, not just the first reaction | Early excitement can hide a weak long-term plan |\n"
            "| Exit plan | What happens when the plan stops, changes, or becomes harder | Maintenance decides whether the result survives |\n"
        )
        return text.rstrip() + table

    def _ensure_comparison_table(self, body: str, keyword: str) -> str:
        if "|" in body and re.search(r"\|\s*---", body):
            return body
        return self._ensure_table_exists(keyword, body)

    def _ensure_case_study_block(self, body: str, keyword: str) -> str:
        if re.search(r"^##\s+(The Case|The Real-Life Pattern|What Happened When)\b", body, re.MULTILINE | re.IGNORECASE):
            return self._remove_wrong_modality_phrases(body, keyword)
        if self._is_medication_keyword(keyword):
            return body.rstrip() + "\n\n" + self._build_medication_case_study(keyword)
        parent = getattr(super(), "_ensure_case_study_block", None)
        if callable(parent):
            try:
                return str(parent(body, keyword))
            except Exception:
                pass
        return body

    def _build_medication_case_study(self, keyword: str) -> str:
        phrase = self._heading_subject(keyword)
        return (
            "## The Case That Shows Why The Decision Is Not Just About Results\n\n"
            f"A realistic composite scenario looks like this. A reader starts looking into {phrase} after months of feeling stuck, and the first few weeks sound encouraging because appetite feels easier to manage. The turning point does not come from a dramatic before-and-after photo. It comes around the second or third refill, when the routine becomes more practical than exciting: the pharmacy needs extra time, the insurance approval is not as simple as expected, constipation becomes harder to ignore, and the reader realizes the medication decision is now tied to budget, follow-up, and a maintenance plan.\n\n"
            "That kind of scenario is why I would not judge the choice by early momentum alone. The better question is whether the person has medical guidance, a plan for side effects, a realistic refill path, and habits that protect the result if appetite control changes. The lesson is not that the medication is good or bad for everyone. The lesson is that the real decision begins when the headline promise meets ordinary life."
        )

    def _remove_wrong_modality_phrases(self, body: str, keyword: str) -> str:
        if not self._is_medication_keyword(keyword):
            return body
        cleaned = body
        cleaned = re.sub(r"\b(drinking|drink|drank)\s+it\b", "using the medication", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bdrinking\s+[^\.]+\s+(two|three|2|3)\s+times\s+a\s+day\b", "following the prescribed schedule", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\btea|smoothie|ritual drink|sweet coffee\b", "routine", cleaned, flags=re.IGNORECASE)
        return cleaned

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
        if self._is_medication_keyword(keyword):
            return (
                "\n\n## What To Do Before You Choose This Path\n\n"
                f"A useful next step for {subject} is not to chase the strongest claim. It is to turn the decision into a set of questions you can take to a qualified clinician.\n\n"
                "1. **Check personal fit first.** Write down your medical history, current medications, previous side effects, and the reason you are considering this option.\n"
                "2. **Check the access path.** Confirm prescription requirements, follow-up schedule, refill reliability, insurance coverage, prior authorization, and realistic monthly cost.\n"
                "3. **Plan for tolerability.** Ask what side effects should be expected, what warning signs deserve attention, and what to do if the dose feels hard to tolerate.\n"
                "4. **Build the maintenance layer.** Discuss protein intake, strength training, sleep, long-term eating patterns, and what happens if the medication is paused or stopped."
            )
        return (
            f"\n\n## What To Do Next If You Want A Real-World Answer\n\n"
            f"A useful action guide for {subject} should turn the promise into a decision you can actually check. Use these steps before treating the idea like a finished plan.\n\n"
            "1. **Define the real decision.** Write down whether you are trying to solve results, side effects, cost, access, consistency, or confusion.\n"
            "2. **Track the friction for two weeks.** Watch the moments where the plan becomes hard, not only the moments where it seems to work.\n"
            "3. **Compare the tradeoff before escalating.** Ask whether the expected benefit is worth the time, money, symptoms, or routine change required.\n"
            "4. **Get qualified input when the topic touches health or medication.** Do not turn a search result into a personal protocol without professional review."
        )

    def _generate_editorial_faq(self, keyword: str, title: str, summary: str, persona: str, strict: bool) -> str:
        if self._is_medication_keyword(keyword):
            text = self._generate_medication_faq(keyword, title, summary, persona, strict)
            if text:
                return text
            return self._fallback_faq(keyword)
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

    def _generate_medication_faq(self, keyword: str, title: str, summary: str, persona: str, strict: bool) -> str | None:
        prompt = (
            "Write a markdown FAQ section for a medication-related YMYL decision article. "
            "Return `## Frequently Asked Questions` plus at least 4 H3 questions. "
            "Do not invent FDA dates, trial names, exact percentages, or medical instructions. "
            "Questions should sound like real searches about effectiveness, side effects, insurance, stopping, plateauing, and whether it is worth the hassle. "
            "Each answer should be 100 to 180 words and should push the reader toward clinician discussion, practical tracking, and realistic expectations.\n\n"
            f"Article title: {title}\n"
            f"Keyword: {keyword}\n"
            f"Summary: {summary}\n"
            f"Author persona: {persona}\n"
            "Return plain markdown only."
        )
        text = self._call_gemini_with_retry(prompt, attempts=2)
        if text:
            faq = self._extract_markdown_body(text)
            faq = self._remove_unsupported_claims(faq, keyword)
            if self._faq_is_thick(faq):
                return faq.strip()
        return None

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
        if self._is_medication_keyword(keyword):
            return f"""## Frequently Asked Questions

### Is {subject} still worth considering if the side effects sound hard

It may be worth discussing with a qualified clinician, but side effects should not be treated like a small footnote. The practical question is not only whether the medication can help with weight loss. It is whether the person can tolerate the process safely enough to stay consistent. Nausea, constipation, appetite changes, fatigue, dose adjustments, and other individual reactions can change the decision quickly. A realistic next step is to ask what side effects are common, what would be a warning sign, what can be managed, and when the plan should be paused or reassessed. The best decision is usually made before the person is desperate for results, not after side effects have already become a crisis.

### What should I ask before starting {subject}

The most useful questions are practical. Ask whether your medical history, current medications, weight-loss history, and goals make this option appropriate to discuss. Ask how follow-up will work, what dose changes might involve, what side effects should be tracked, and what happens if access is interrupted. You should also ask about cost, insurance coverage, prior authorization, refill timing, and realistic maintenance planning. The key is to avoid treating the medication as the entire strategy. A strong plan also includes protein, resistance training, sleep, eating patterns, and a clear idea of what happens if progress slows or the medication is stopped.

### Why do some people feel disappointed with {subject}

Disappointment usually appears when the expectation is cleaner than the reality. Some people expect fast, effortless progress, then run into side effects, cost, refill delays, or a plateau that makes the process feel less exciting. Others lose weight early but never build the habits that protect the result. The medication may reduce appetite pressure, but it does not automatically solve food quality, strength loss, sleep, emotional eating, or long-term maintenance. A better standard is not whether the first few weeks feel impressive. It is whether the plan still makes sense after ordinary life returns and the person has to manage the boring details.

### What happens if access to {subject} gets interrupted

An access interruption can make the plan more stressful because the routine depends on prescription, pharmacy, insurance, and follow-up timing. If a refill is delayed or coverage changes, the person may face renewed appetite pressure, uncertainty about the next dose, and anxiety about losing progress. This is why access planning matters before starting. Ask how refills are handled, how early to request the next fill, what to do if a dose is unavailable, and who to contact if insurance denies coverage. Do not improvise medication changes from online advice. A qualified clinician or pharmacist should guide any interruption, restart, or adjustment."""
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
        if self._is_medication_keyword(keyword):
            return (
                "## The Next Step Without Guesswork\n\n"
                f"The useful move after searching {keyword} is not to crown a winner from a headline. It is to collect the practical facts that decide whether the option is realistic for you: medical fit, side-effect tolerance, access, coverage, follow-up, cost, and maintenance. Bring those questions to a qualified clinician before turning a search result into a personal plan."
            )
        return (
            "## The Next Step Without Guesswork\n\n"
            f"The useful move after searching {keyword} is not to copy the most confident claim. It is to translate the claim into a real decision. Ask what problem you are trying to solve, what friction you can realistically tolerate, and what evidence or professional input you need before acting. A strong plan should make the next step clearer, not just make the promise louder."
        )

    def _repair_viral_contract_after_parent_normalization(self, body: str, keyword: str) -> str:
        repaired = self._remove_wrong_modality_phrases(body, keyword)
        repaired = self._remove_unsupported_claims(repaired, keyword)
        repaired = self._ensure_case_study_block(repaired, keyword)
        repaired = self._ensure_comparison_table(repaired, keyword)
        repaired = self._ensure_action_guide(repaired, keyword)
        repaired = self._ensure_faq_block(repaired, keyword)
        return repaired.strip()

    def _passes_editorial_shape(self, body: str) -> bool:
        if not self._is_usable_stage2_body(body):
            return False
        if not re.search(r"^##\s+Frequently Asked Questions\s*$", body, flags=re.MULTILINE):
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
