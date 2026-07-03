#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Editorial segmented generation controller.

This controller keeps the existing pipeline stages, but changes Stage 2 into the
workflow we actually want for production quality:

1. Use the Stage 1-2 title, summary, H2s, key points, and persona as a shared outline.
2. Generate the article section by section instead of hoping one full-page call holds together.
3. Generate FAQ as its own thick section.
4. Always save a `.draft.md` first.
5. Only then normalize the final body and write the final `.md`.

The goal is not a generic explainer. The goal is the expert-process article
style: direct answer, real friction, process breakdown, scenario, table, action
steps, thick FAQ, and a clear next step.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re

from pipeline_controller import PipelineController, PipelineResult, ProgressCallback
from preview_renderer import render_preview_html
from publish_articles import load_article


class EditorialPipelineController(PipelineController):
    """PipelineController variant that makes segmented Stage 2 the default."""

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
        title = self._normalize_final_title(node["t"], keyword)
        description = self._truncate_description(str(node["cr"]["s"]))
        category_value = self._normalize_category_id(category_id if category_id is not None else node.get("category_id"))
        resolved_keyword_id = keyword_id if keyword_id is not None else node.get("keyword_id")
        article_style = style if style in self.ARTICLE_STYLE_RULES else self.suggest_title_styles(keyword)[0]

        body = self._run_editorial_segmented_stage2(keyword, node, article_style, strict=False)
        if body is None or not self._passes_editorial_shape(body):
            if progress:
                progress("Fact_Checking", 51, "Segmented draft was weak, retrying stricter section generation")
            body = self._run_editorial_segmented_stage2(keyword, node, article_style, strict=True)

        if body is None or not self._is_usable_stage2_body(body):
            if progress:
                progress("Fact_Checking", 54, "Segmented generation failed, using recovery writer once")
            body = self._run_stage2_recovery_llm(keyword, node, article_style)

        if body is None or not self._is_usable_stage2_body(body):
            if progress:
                progress("Fact_Checking", 56, "Recovery failed, using local emergency article builder")
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

    def _run_editorial_segmented_stage2(self, keyword: str, node: dict, style: str, strict: bool = False) -> str | None:
        cr = node.get("cr", {}) or {}
        sections = self._normalize_planning_sections(cr.get("st", []) or [], keyword)[:6]
        key_points = self._normalize_planning_key_points(cr.get("kp", []) or [], keyword)
        if len(sections) < 4:
            sections = self._planning_sections_from_keyword(keyword, self._infer_query_type(keyword))[:5]

        title = self._normalize_final_title(str(node.get("t", keyword)), keyword)
        summary = str(cr.get("s", self._build_description(keyword))).strip()
        persona = str(cr.get("author_bio", self._default_author_bio(keyword))).strip()
        personal_story = str(cr.get("personal_story", self._default_personal_story(keyword))).strip()
        style_rule = self.ARTICLE_STYLE_RULES.get(style, self.ARTICLE_STYLE_RULES["question"])
        updated_line = f"Last updated: {datetime.now().strftime('%A, %B %-d, %Y')}"
        intro = self._build_expert_process_opening(keyword, summary, personal_story)

        section_blocks: list[str] = []
        prior_context = intro
        for index, section in enumerate(sections):
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

        joined_sections = "\n\n".join(section_blocks)
        joined_sections = self._ensure_table_exists(keyword, joined_sections)
        joined_sections = self._ensure_action_steps_exist(keyword, joined_sections)

        faq = self._generate_editorial_faq(keyword, title, summary, persona, strict=strict)
        closing = self._build_editorial_closing(keyword)
        toc_lines = ["## Table of Contents"] + [f"- [{section}](#{self._slugify(section)})" for section in sections]
        toc_lines.append("- [Frequently Asked Questions](#frequently-asked-questions)")
        toc_lines.append("- [The Next Step Without Guesswork](#the-next-step-without-guesswork)")

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
            return "Include concrete action steps or a practical decision protocol."
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
        text = self._call_gemini_with_retry(prompt, attempts=2)
        if not text:
            return None
        return text

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
        if len(re.findall(r"^\s*\d+\.\s+", text, flags=re.MULTILINE)) >= 3:
            return text
        return text.rstrip() + self._fallback_action_steps(keyword)

    def _fallback_action_steps(self, keyword: str) -> str:
        return (
            f"\n\nA practical next-step protocol for {keyword} looks like this:\n\n"
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
        short_answers = 0
        for answer in parts[:4]:
            words = re.findall(r"\b\w+\b", answer)
            if len(words) < 80:
                short_answers += 1
        return short_answers == 0

    def _fallback_faq(self, keyword: str) -> str:
        subject = self._heading_subject(keyword)
        return f"""## Frequently Asked Questions

### Does {subject} actually work in real life

The honest answer is that it depends on what someone means by `work`. A result that looks impressive in the first few weeks can still fail if the routine is expensive, uncomfortable, confusing, or impossible to maintain. The better way to judge {subject} is to track both the visible outcome and the hidden friction. Look at what changes after the first excitement fades: energy, appetite, symptoms, cost, social life, consistency, and whether the person can keep the core behavior without feeling trapped by it.

### Who is most likely to regret {subject}

The people most likely to regret {subject} are usually the ones who start with a result fantasy but no plan for the tradeoffs. That might mean no budget plan, no symptom plan, no maintenance plan, or no understanding of what the process actually requires. Regret can also show up when someone copies a viral version of the idea without checking whether it fits their health background, schedule, preferences, or risk tolerance. A good decision starts by asking what could make the plan fail, not just what could make it work.

### What should I track before deciding whether to continue

Track the parts that reveal whether the process is sustainable. The scale or headline outcome is only one signal. Watch your energy, sleep, cravings, mood, digestion, spending, skipped routines, and the moments where the plan feels hardest to follow. A two-week pattern tells you more than a single good day. If the plan touches medication, medical nutrition, supplements, or a health condition, bring those notes to a qualified professional instead of trying to interpret every signal alone.

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
        if len(re.findall(r"^\s*\d+\.\s+", body, flags=re.MULTILINE)) < 3:
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
