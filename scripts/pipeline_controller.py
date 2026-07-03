#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thin orchestration layer for local UI generation, preview, and CMS import."""

from __future__ import annotations

from dataclasses import dataclass
import copy
import json
import os
from pathlib import Path
import re
from typing import Callable

import requests

from media_enrichment import MultimediaEnricher
from preview_renderer import render_preview_html
from publish_articles import build_media_root, load_article, parse_mdx_frontmatter, publish_article


ProgressCallback = Callable[[str, int, str], None]


@dataclass(frozen=True)
class PipelineResult:
    """Final result returned to the local UI.

    Attributes:
        keyword: Input keyword.
        stage1_1_path: Stage 1-1 JSON path.
        stage1_2_path: Stage 1-2 JSON path.
        markdown_path: Generated markdown file path.
        preview_path: Generated preview HTML path.
        title: Final article title.
        description: Final article description.
        publish_result: Optional publish result object.
    """

    keyword: str
    stage1_1_path: Path
    stage1_2_path: Path
    markdown_path: Path
    preview_path: Path
    title: str
    description: str
    publish_result: dict | None


@dataclass(frozen=True)
class TitlePlan:
    """Title-generation result used by batch workflows."""

    source_keyword: str
    title: str
    topic_category: str
    style: str
    candidate_styles: tuple[str, ...]


class PipelineController:
    """Run local preview and CMS publish steps with progress callbacks."""

    TITLE_STYLE_RULES: dict[str, str] = {
        'question': 'Use a direct question headline that sounds like a real search query. Prefer patterns like "Does X Actually Work?" or "What Really Happens With X?".',
        'versus': 'Use a comparison headline with a clear contrast or tradeoff. Prefer patterns like "X vs. Y" or "X or Y".',
        'truth': 'Use a truth/reality-check headline with skepticism or clarification. Prefer patterns like "The Truth About X" or "X: What the Data Really Shows".',
        'test': 'Use a test or verdict headline that implies evaluation under real conditions. Prefer patterns like "X Put to the Test" or "I Looked at X" without sounding fake-personal.',
        'best': 'Use a buyer-intent or selection headline that helps the reader choose. Prefer patterns like "Best X" or "Which X Is Worth It?".',
    }
    TITLE_STYLE_ORDER: tuple[str, ...] = ('question', 'versus', 'truth', 'test', 'best')
    ARTICLE_STYLE_RULES: dict[str, str] = {
        'question': 'Open by answering the reader\'s core question in the first paragraph. Keep the tone direct, practical, and search-intent-led. Every section should feel like it is resolving a real user question, not writing a detached explainer.',
        'versus': 'Frame the article around a real comparison and tradeoff. Emphasize differences, decision points, pros and cons, and where each option fits better. Use contrast language naturally throughout the article.',
        'truth': 'Write with a skeptical, myth-checking editorial voice. Surface what is overstated, what is unsupported, and what survives closer scrutiny. The tone should feel like a calm correction, not a lecture.',
        'test': 'Write like a real-world evaluation. Emphasize what was checked, what holds up, what falls apart, and what the practical verdict is. The tone should feel active and review-driven, not abstract.',
        'best': 'Write for a reader trying to choose among options. Surface selection criteria early, keep the article decision-oriented, and make the practical ranking logic or recommendation standard very clear.',
    }

    def __init__(self, workspace_root: Path, output_root: Path | None = None) -> None:
        self.workspace_root = workspace_root
        self.output_root = output_root or workspace_root
        self.output_root.mkdir(parents=True, exist_ok=True)

    def generate_title_plan(self, keyword: str, style: str | None = None, topic_category: str | None = None) -> TitlePlan | None:
        """Generate a cleaned article title and internal topic category.

        Args:
            keyword: Raw batch keyword.
            style: Optional requested title style.

        Returns:
            Normalized title plan, or None when Gemini fails twice.
        """
        candidate_styles = self.suggest_title_styles(keyword)
        selected_style = style if style in self.TITLE_STYLE_RULES else candidate_styles[0]
        style_rule = self.TITLE_STYLE_RULES[selected_style]
        normalized_topic = self._normalize_topic_category(keyword, topic_category)
        prompt = self._build_title_candidates_prompt(keyword, selected_style, candidate_styles, style_rule, normalized_topic)
        text = self._call_gemini(prompt)
        if not text:
            text = self._call_gemini(prompt)
        if not text:
            return None
        data = self._extract_json_object(text)
        if not isinstance(data, dict):
            return None
        titles = self._extract_title_candidates(data)
        chosen_title, rejected_titles = self._select_best_title_candidate(keyword, titles, selected_style)
        if not chosen_title:
            retry_prompt = self._build_title_retry_prompt(
                keyword,
                selected_style,
                candidate_styles,
                style_rule,
                normalized_topic,
                titles,
                rejected_titles,
            )
            retry_text = self._call_gemini(retry_prompt)
            if not retry_text:
                return None
            retry_data = self._extract_json_object(retry_text)
            if not isinstance(retry_data, dict):
                return None
            retry_titles = self._extract_title_candidates(retry_data)
            chosen_title, rejected_titles = self._select_best_title_candidate(keyword, retry_titles, selected_style)
            if not chosen_title:
                return None
            data = retry_data
        detected_topic = str(data.get('topic_category') or data.get('category') or '').strip().upper()
        final_topic = normalized_topic if normalized_topic in {'WEIGHT_LOSS', 'BLOOD', 'CBD'} else detected_topic
        return TitlePlan(
            source_keyword=keyword,
            title=chosen_title,
            topic_category=final_topic if final_topic in {'WEIGHT_LOSS', 'BLOOD', 'CBD'} else 'WEIGHT_LOSS',
            style=selected_style,
            candidate_styles=candidate_styles,
        )

    def _build_title_candidates_prompt(self, keyword: str, selected_style: str, candidate_styles: tuple[str, ...], style_rule: str, topic_category: str) -> str:
        return (
            'You are an elite high-conversion SEO title editor for a health and lifestyle publisher. '
            'Transform the raw keyword into multiple highly clickable but still credible H1 title candidates for a YMYL-aware article. '
            'The titles should feel like a magazine editor wrote them after actually testing, tracking, coaching, or reviewing the topic in real life. '
            'Before writing the titles, infer the search intent behind the keyword: what problem the user is trying to solve, what answer they want, what claim they are checking, or what trend they are trying to decode. '
            'The final titles must preserve that search intent clearly instead of drifting into broad magazine headlines. '
            'Also classify the topic into exactly one internal topic_category: WEIGHT_LOSS, BLOOD, or CBD.\n\n'
            '[Gold-standard title patterns to imitate]\n'
            '1. First-person test / reveal:\n'
            '- I Tried X for 30 Days — Here\'s What Actually Happened\n'
            '- I Drank X Every Morning — The Unfiltered Truth\n'
            '- I Tracked X So You Don\'t Have To\n'
            '2. Real-world verdict:\n'
            '- Does X Actually Work — Or Is the Hype Doing All the Heavy Lifting?\n'
            '- What Really Happens When You Stick With X\n'
            '- The Real Reason X Seems to Work for Some People\n'
            '3. Comparison / tradeoff:\n'
            '- I Compared X vs Y — Here\'s the Tradeoff Most People Miss\n'
            '- X or Y for Weight Loss — The Better Pick Depends on This\n'
            '- I Looked at X vs Y Side by Side — Here\'s Where the Choice Gets Real\n'
            '4. Myth-bust with lived experience:\n'
            '- Why X Feels Like a Shortcut — But Usually Isn\'t\n'
            '- The X Trend Sounds Smart Until You Look at What\'s Really Happening\n'
            '- What X Gets Right — And Where It Falls Apart\n'
            '5. Search-intent answer with story energy:\n'
            '- If You\'re Wondering Whether X Works, Start Here\n'
            '- The Honest Answer on X After Looking Past the Marketing\n'
            '- What I\'d Want to Know Before Trying X Myself\n\n'
            '[Critical rules]\n'
            '- These title rules are mandatory, not optional. Any title that violates them is invalid.\n'
            '- High click-through is good, but do not sound fake, hysterical, or tabloid.\n'
            '- Candidate 1 MUST be a first-person reveal, test, tracking, or unfiltered-truth title unless the keyword is a comparison or symptom query where a stronger reveal-style editorial verdict fits better.\n'
            '- Invalid titles include anything that sounds like a journal abstract, clinical summary, dictionary entry, evidence review, encyclopedia heading, or bland explainer.\n'
            '- Invalid wording includes phrases like "Separating Fact from Fiction", "An Evidence-Based Review", "A Comprehensive Guide", "Understanding the Rumors", "Reviewing the Clinical Evidence", "What the Clinical Evidence Shows", "Efficacy Review", "Clinical Trial Results", "Effectiveness", "Analyzed", or "Explained" unless the keyword explicitly asks for clinical trials or evidence summaries.\n'
            '- Prefer conflict, curiosity, stakes, a test, a personal verdict, or a revealing editorial angle.\n'
            '- The title must stay tightly aligned with the keyword\'s search intent. If the user is searching for whether something works, whether something is a scam, what caused a result, or what went wrong, the title must answer that exact intent rather than broadening the topic.\n'
            '- Preserve the main search phrase or its closest natural-language form near the front of the title whenever possible.\n'
            '- Use Title Case.\n'
            '- Do not overpromise outcomes or imply medical certainty that the article cannot support.\n'
            '- Do not default to a colon title structure. Prefer clean single-flow titles, em-dash reveal titles, questions, or natural comparison phrasing unless a colon is clearly the strongest fit.\n'
            '- Avoid repeating the same punctuation skeleton across outputs. Do not treat "X: Y" as the standard fallback shape.\n'
            '- If a candidate sounds generic, academic, or weakly clickable, replace it with a stronger reveal-driven version before returning JSON.\n'
            '- Use this required primary style for the first candidate: ' + style_rule + '\n'
            '- These other acceptable styles also fit the keyword for the remaining candidates: ' + ', '.join(candidate_styles) + '.\n'
            '- Keep every candidate tightly inside the requested topic lane. Do not drift across lanes. Weight-loss topics must stay about fat loss, body weight, metabolism, GLP-1, diet, or exercise. Blood topics must stay about blood sugar, glucose, A1C, insulin, blood pressure, cholesterol, circulation, or blood markers. CBD topics must stay about cannabidiol, hemp, gummies, tinctures, safety, effects, or legality.\n'
            '- Return strict JSON only with keys "topic_category" and "titles", where "titles" is an array of exactly 5 distinct candidate strings.\n'
            '- Candidate 1 must follow the requested primary style. The other 4 candidates should vary their structure and avoid repeating the same skeleton.\n\n'
            f'Requested style: {selected_style}\n'
            f'Requested topic_category: {topic_category}\n'
            f'Candidate styles: {", ".join(candidate_styles)}\n'
            f'Input keyword: {keyword}'
        )

    def _build_title_retry_prompt(
        self,
        keyword: str,
        selected_style: str,
        candidate_styles: tuple[str, ...],
        style_rule: str,
        topic_category: str,
        previous_titles: list[str],
        rejection_reasons: list[str],
    ) -> str:
        failure_notes = '; '.join(rejection_reasons) if rejection_reasons else 'all previous titles were rejected by local quality rules'
        previous_list = '\n'.join(f'- {title}' for title in previous_titles) if previous_titles else '- none returned'
        return (
            self._build_title_candidates_prompt(keyword, selected_style, candidate_styles, style_rule, topic_category)
            + '\n\n[Retry Feedback]\n'
            + 'The previous batch of titles was rejected. Do not repeat the same structures or phrasing.\n'
            + 'Rejected titles:\n'
            + previous_list
            + '\nFailure reasons: '
            + failure_notes
            + '\nThis retry must avoid colon-default titles and must avoid clinical-review phrasing. '
            + 'Return 5 fresh titles that are structurally different from the rejected ones.'
        )

    def _normalize_topic_category(self, keyword: str, topic_category: str | None = None) -> str:
        normalized = str(topic_category or '').strip().upper()
        if normalized in {'WEIGHT_LOSS', 'BLOOD', 'CBD'}:
            return normalized
        lowered = keyword.lower()
        if any(token in lowered for token in ('cbd', 'cannabidiol', 'hemp', 'tincture', 'gummies', 'gummy')):
            return 'CBD'
        if any(token in lowered for token in ('blood', 'glucose', 'a1c', 'hemoglobin', 'cholesterol', 'triglycerides', 'insulin', 'bp', 'blood pressure', 'sugar')):
            return 'BLOOD'
        return 'WEIGHT_LOSS'

    def suggest_title_styles(self, keyword: str) -> tuple[str, ...]:
        lowered = keyword.lower()
        scores = {style: 0 for style in self.TITLE_STYLE_ORDER}

        def bump(styles: tuple[str, ...], amount: int) -> None:
            for name in styles:
                scores[name] += amount

        if any(token in lowered for token in (' vs ', ' versus ', 'compare', 'comparison')):
            bump(('versus', 'question'), 4)
        if any(token in lowered for token in ('best ', 'top ', 'for men', 'for women', 'for seniors', 'worth it', 'which ')):
            bump(('best', 'question'), 4)
        if any(token in lowered for token in ('scam', 'fake', 'hoax', 'truth', 'real', 'legit', 'marketing', 'claim')):
            bump(('truth', 'question'), 4)
        if any(token in lowered for token in ('review', 'tested', 'trial', 'results', 'data', 'study', 'studies')):
            bump(('test', 'truth'), 3)
        if any(token in lowered for token in ('does ', 'do ', 'can ', 'is ', 'what ', 'why ', 'how ')):
            bump(('question',), 3)
        if any(token in lowered for token in ('tea', 'gummies', 'supplements', 'pill', 'pills', 'drops', 'powder', 'product', 'products')):
            bump(('test', 'best'), 2)
        if any(token in lowered for token in ('glp-1', 'injectable', 'injection', 'oral', 'prescription', 'medication', 'medications')):
            bump(('versus', 'question', 'truth'), 2)
        if any(token in lowered for token in ('belly fat', 'midlife', 'hormonal', 'weight loss', 'fat loss')):
            bump(('question', 'truth'), 1)

        ordered = sorted(self.TITLE_STYLE_ORDER, key=lambda name: (-scores[name], self.TITLE_STYLE_ORDER.index(name)))
        top_score = scores[ordered[0]]
        chosen = [name for name in ordered if scores[name] == top_score]
        for name in ordered:
            if name not in chosen and len(chosen) < 3 and scores[name] >= max(1, top_score - 1):
                chosen.append(name)
        if not chosen:
            return ('question', 'truth', 'test')
        if len(chosen) == 1:
            for fallback in ('truth', 'test', 'best', 'versus'):
                if fallback not in chosen:
                    chosen.append(fallback)
                if len(chosen) == 3:
                    break
        elif len(chosen) == 2:
            for fallback in self.TITLE_STYLE_ORDER:
                if fallback not in chosen:
                    chosen.append(fallback)
                    break
        return tuple(chosen[:3])

    def run_stage1_1(self, keyword: str, progress: ProgressCallback | None = None) -> tuple[dict, Path]:
        """Generate a local Stage 1-1 payload and persist it.

        Args:
            keyword: Input keyword/title.
            progress: Optional progress callback.

        Returns:
            Stage 1-1 payload and saved path.
        """
        if progress:
            progress("Pending", 5, "Running Stage 1-1 keyword expansion")
        slug = self._slugify(keyword)
        payload = self._run_stage1_1_llm(keyword)
        if payload is None:
            raise RuntimeError("Gemini Stage 1-1 failed twice; skipped without fallback template")
        payload = self._normalize_stage1_1_payload(payload, keyword)
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
        """Generate a local Stage 1-2 planning payload and persist it.

        Args:
            keyword: Input keyword/title.
            stage1_1: Stage 1-1 payload.
            category_id: Optional category id.
            keyword_id: Optional keyword id.
            progress: Optional progress callback.

        Returns:
            Stage 1-2 payload and saved path.
        """
        if progress:
            progress("Drafting", 25, "Running Stage 1-2 outline planning")
        slug = self._slugify(keyword)
        category_value = self._normalize_category_id(category_id)
        keyword_value = keyword_id
        payload = self._run_stage1_2_llm(stage1_1)
        if payload is None:
            raise RuntimeError("Gemini Stage 1-2 failed twice; skipped without fallback template")
        payload = self._normalize_stage1_2_payload(payload, keyword)
        for item in payload.get("dsq", []):
            for mt in item.get("mt", []):
                mt["category_id"] = self._normalize_category_id(category_id if category_id is not None else mt.get("category_id"))
                if keyword_id is not None:
                    mt["keyword_id"] = keyword_id
        path = self.output_root / f"ui_{slug}.stage1_2.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, path

    def build_markdown_from_plan(
        self,
        keyword: str,
        stage1_2: dict,
        category_id: int | None = None,
        keyword_id: int | None = None,
        style: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> Path:
        """Render final markdown from the Stage 1-2 plan.

        Args:
            keyword: Input keyword/title.
            stage1_2: Stage 1-2 payload.
            category_id: Optional category id.
            keyword_id: Optional keyword id.
            style: Optional article style.
            progress: Optional progress callback.

        Returns:
            Markdown path.
        """
        if progress:
            progress("Fact_Checking", 45, "Rendering Stage 2 long-form article")
        slug = self._slugify(keyword)
        markdown_path = self.output_root / f"ui_{slug}.md"
        draft_markdown_path = self.output_root / f"ui_{slug}.draft.md"
        node = self._select_best_stage2_node(keyword, stage1_2)
        title = self._normalize_final_title(node["t"], keyword)
        description = self._truncate_description(str(node["cr"]["s"]))
        category_value = self._normalize_category_id(category_id if category_id is not None else node.get("category_id"))
        resolved_keyword_id = keyword_id if keyword_id is not None else node.get("keyword_id")
        article_style = style if style in self.ARTICLE_STYLE_RULES else self.suggest_title_styles(keyword)[0]

        body = self._run_stage2_llm(keyword, node, article_style)
        if body is None or not self._is_usable_stage2_body(body):
            if progress:
                progress("Fact_Checking", 50, "Stage 2 primary draft failed, retrying Gemini once")
            body = self._run_stage2_recovery_llm(keyword, node, article_style)
        if body is None or not self._is_usable_stage2_body(body):
            if progress:
                progress("Fact_Checking", 53, "Stage 2 full-page draft failed, switching to shared-outline section generation")
            body = self._run_stage2_segmented_llm(keyword, node, article_style)
        if body is None:
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
            progress("Fact_Checking", 57, f"Saved draft markdown: {draft_markdown_path.name}")

        final_body = self._normalize_article_voice(draft_body, title, keyword)
        final_body = self._rewrite_references(final_body, title, keyword, category_value)
        content = self._compose_markdown_document(
            keyword,
            title,
            description,
            category_value,
            resolved_keyword_id,
            final_body,
        )
        markdown_path.write_text(content, encoding="utf-8")
        if progress:
            progress("SEO_Optimizing", 60, f"Rendered final markdown: {markdown_path.name}")
        return markdown_path

    def _compose_markdown_document(
        self,
        keyword: str,
        title: str,
        description: str,
        category_value: int,
        keyword_id: int | None,
        body: str,
    ) -> str:
        keyword_line = f"keyword_id: {keyword_id}" if keyword_id is not None else ""
        extra = f"{keyword_line}\n" if keyword_line else ""
        return f"""---
title: {title}
description: {description}
keywords: {self._build_keywords(keyword)}
category_id: {category_value}
{extra}tag: ymyl content, evidence aware guide
country: US
region:
locality:
---

{body}
"""

    def run_generation(
        self,
        keyword: str,
        category_id: int | None = None,
        keyword_id: int | None = None,
        style: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> PipelineResult:
        """Generate stage artifacts, markdown, and preview from a keyword."""
        stage1_1, stage1_1_path = self.run_stage1_1(keyword, progress)
        stage1_2, stage1_2_path = self.run_stage1_2(keyword, stage1_1, category_id, keyword_id, progress)
        markdown_path = self.build_markdown_from_plan(keyword, stage1_2, category_id, keyword_id, style, progress)
        if progress:
            progress("Enriching", 75, "Rendering preview HTML")
        preview_path = render_preview_html(markdown_path)
        article = load_article(markdown_path)
        if progress:
            progress("Ready_to_Publish", 90, "Preview ready and CMS payload validated")
        return PipelineResult(
            keyword=keyword,
            stage1_1_path=stage1_1_path,
            stage1_2_path=stage1_2_path,
            markdown_path=markdown_path,
            preview_path=preview_path,
            title=str(article.get("title", keyword)),
            description=str(article.get("description", "")),
            publish_result=None,
        )

    def publish_existing(self, markdown_path: Path, progress: ProgressCallback | None = None) -> dict:
        """Publish a prepared markdown file to CMS."""
        if progress:
            progress("Publishing", 92, f"Publishing {markdown_path.name} to CMS")
        article = load_article(markdown_path)
        result = publish_article(article)
        if result.get("ok"):
            if progress:
                progress("Published", 100, f"Published successfully. Remote ID: {result.get('remote_id')}")
        else:
            if progress:
                progress("Failed", 100, f"Publish failed: {result.get('message')}")
        return result

    def _normalize_stage1_1_payload(self, payload: dict, keyword: str) -> dict:
        queries = payload.get('qs') or []
        invalid_tokens = (
            'clinical evidence',
            'clinical efficacy',
            'trial data',
            'documented safety profile',
            'contraindications',
            'mechanism of action',
            'systematic review',
        )
        cleaned_queries: list[str] = []
        for query in queries:
            text = re.sub(r'\s+', ' ', str(query)).strip()
            if not text:
                continue
            lowered = text.lower()
            if any(token in lowered for token in invalid_tokens):
                continue
            cleaned_queries.append(text)
        if not cleaned_queries:
            cleaned_queries = self._fallback_queries_for_keyword(keyword)
        payload['qs'] = cleaned_queries[:5]
        return payload

    def _normalize_stage1_2_payload(self, payload: dict, keyword: str) -> dict:
        normalized_items = []
        for item in payload.get('dsq', []):
            item_query = str(item.get('q') or keyword).strip() or keyword
            normalized_mt = []
            for mt in item.get('mt', []):
                normalized_mt.append(self._normalize_stage1_2_node(mt, item_query))
            if not normalized_mt:
                normalized_mt.append(self._fallback_stage1_2_node(item_query))
            item['mt'] = normalized_mt[:3]
            normalized_items.append(item)
        if not normalized_items:
            payload['dsq'] = [{'q': keyword, 'i': f'Reader wants a clear answer on {keyword}', 'mt': [self._fallback_stage1_2_node(keyword)]}]
        return payload

    def _fallback_queries_for_keyword(self, keyword: str) -> list[str]:
        phrase = self._heading_subject(keyword)
        query_type = self._infer_query_type(keyword)
        if query_type == 'comparison':
            return [
                f'{phrase} which one is the better fit',
                f'{phrase} side effects and tradeoffs',
                f'{phrase} what most people get wrong',
            ]
        if query_type == 'symptom':
            return [
                f'why {phrase} keeps happening',
                f'{phrase} when should i worry',
                f'{phrase} what clues matter most',
            ]
        if query_type == 'celebrity':
            return [
                f'{phrase} what really caused the change',
                f'{phrase} what people copy wrong',
                f'{phrase} is it the routine or the hype',
            ]
        return [
            f'does {phrase} actually work',
            f'{phrase} what really happens in real life',
            f'{phrase} who ends up disappointed',
        ]

    def _normalize_stage1_2_node(self, mt: dict, keyword: str) -> dict:
        node = copy.deepcopy(mt)
        cr = node.setdefault('cr', {})
        query_type = self._infer_query_type(keyword)

        raw_title = str(node.get('t') or '').strip()
        raw_summary = str(cr.get('s') or '').strip()
        raw_sections = [str(item).strip() for item in (cr.get('st') or []) if str(item).strip()]
        raw_key_points = [str(item).strip() for item in (cr.get('kp') or []) if str(item).strip()]

        invalid_title_tokens = ('clinical', 'efficacy', 'evidence review', 'mechanism', 'contraindication')
        invalid_section_tokens = ('understanding', 'key findings', 'mechanism', 'clinical evidence', 'contraindications', 'benefits', 'risks', 'safety profile')

        if not raw_title or any(token in raw_title.lower() for token in invalid_title_tokens):
            node['t'] = self._planning_title_from_keyword(keyword, query_type)
        else:
            node['t'] = self._normalize_final_title(raw_title, keyword)

        if not raw_summary or any(token in raw_summary.lower() for token in ('clinical', 'trial', 'efficacy', 'mechanism of action')):
            cr['s'] = self._planning_summary_from_keyword(keyword, query_type)
        else:
            cr['s'] = raw_summary

        if not raw_sections or any(any(token in section.lower() for token in invalid_section_tokens) for section in raw_sections):
            cr['st'] = self._planning_sections_from_keyword(keyword, query_type)
        else:
            cr['st'] = raw_sections[:5]

        if not raw_key_points:
            cr['kp'] = self._planning_key_points_from_keyword(keyword, query_type)
        else:
            cr['kp'] = raw_key_points[:5]

        cr['wc'] = str(cr.get('wc') or 1800)
        cr['af'] = 'The opening must answer the question directly, surface the main tradeoff, and tell the reader what matters before they act.'
        cr['author_bio'] = str(cr.get('author_bio') or self._default_author_bio(keyword)).strip()
        cr['personal_story'] = str(cr.get('personal_story') or self._default_personal_story(keyword)).strip()
        return node

    def _fallback_stage1_2_node(self, keyword: str) -> dict:
        phrase = self._heading_subject(keyword)
        return {
            't': self._normalize_planning_title('', keyword),
            'mty': 'Semantic',
            'cs': {'ty': 'Editorial Desk', 'ac': 'US', 'ar': '', 'al': ''},
            'cr': {
                'tl': 'Keep the piece current, practical, and tied to real-world reader decisions.',
                's': self._normalize_planning_summary('', keyword),
                'wc': '1800',
                'st': self._normalize_planning_sections([], keyword),
                'kp': self._normalize_planning_key_points([], keyword),
                'af': 'The opening must answer the question directly, surface the main tradeoff, and tell the reader what matters before they act.',
                'gfm': {'lsr': True},
                'author_bio': self._default_author_bio(keyword),
                'personal_story': self._default_personal_story(keyword),
            },
        }

    def _default_author_bio(self, keyword: str) -> str:
        query_type = self._infer_query_type(keyword)
        if query_type == 'celebrity':
            return 'I cover celebrity wellness claims and weight-loss trends with a focus on what readers can actually use in real life.'
        if query_type == 'comparison':
            return 'I write practical health explainers that help readers compare options without getting lost in hype.'
        if query_type == 'symptom':
            return 'I translate health patterns and warning signs into plain English so readers can act earlier and panic less.'
        return 'I cover weight-loss products, routines, and health claims with a focus on what actually changes results in real life.'

    def _default_personal_story(self, keyword: str) -> str:
        phrase = self._heading_subject(keyword)
        query_type = self._infer_query_type(keyword)
        if query_type == 'celebrity':
            return f'I keep seeing {phrase} packaged like a clean transformation story, even when the real answer is usually messier than the headline.'
        if query_type == 'comparison':
            return f'I have seen readers freeze on {phrase} because both options sound persuasive until the real-world tradeoffs start showing up.'
        if query_type == 'symptom':
            return f'I keep seeing {phrase} treated like a random annoyance when the more useful question is what pattern it may be pointing to.'
        return f'I kept seeing {phrase} framed like an easy shortcut, so I stayed with the harder question of what actually changes outcomes in real life.'

    def _format_title_subject(self, subject: str) -> str:
        text = re.sub(r'\s+', ' ', str(subject)).strip()
        if not text:
            return text
        text = re.sub(r'^does\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^is\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^why\s+is\s+my\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^what\s+causes\s+', '', text, flags=re.IGNORECASE)
        text = text.strip(' ?-')
        lowered = text.lower()
        minor = {'a', 'an', 'and', 'as', 'at', 'by', 'for', 'in', 'is', 'my', 'of', 'on', 'or', 'the', 'to', 'vs'}
        words = []
        for index, part in enumerate(re.split(r'(\s+)', lowered)):
            if not part or part.isspace():
                words.append(part)
                continue
            if index == 0 or part not in minor:
                words.append(part[0].upper() + part[1:])
            else:
                words.append(part)
        return ''.join(words)

    def _pick_title_variant(self, keyword: str, query_type: str, subject: str) -> str:
        subject = self._format_title_subject(subject)
        pools = {
            'comparison': [
                f'I Compared {subject} Side By Side Here\'s The Tradeoff Most People Miss',
                f'{subject} Look Close On Paper But The Real-Life Tradeoff Is Not',
                f'Choosing Between {subject} Usually Comes Down To This One Friction Point',
                f'{subject} Which One Holds Up Better Once The Hype Wears Off',
            ],
            'symptom': [
                f'I Looked Closer At {subject} Here\'s What The Pattern May Actually Mean',
                f'Why {subject} Keeps Happening And The Clue People Miss First',
                f'{subject} Can Look Small At First Until This Pattern Starts Repeating',
                f'Before You Brush Off {subject} Check This Part First',
            ],
            'celebrity': [
                f'I Looked Past The Headlines On {subject} Here\'s What Actually Matters',
                f'{subject} Looks Simple In The Headlines But The Real Story Is Not',
                f'People Keep Copying {subject} For The Wrong Reason',
                f'The Part Of {subject} Most People Get Wrong First',
            ],
            'review': [
                f'I Looked Closely At {subject} Here\'s What Actually Matters',
                f'Does {subject} Actually Hold Up Once Real Life Gets Involved',
                f'{subject} Sounded Promising Until The Tradeoffs Got Real',
                f'Before You Bet On {subject} Read This Part First',
            ],
        }
        variants = pools.get(query_type, pools['review'])
        seed = sum(ord(char) for char in keyword.lower().strip())
        return variants[seed % len(variants)]

    def _planning_title_from_keyword(self, keyword: str, query_type: str) -> str:
        phrase = self._heading_subject(keyword)
        return self._pick_title_variant(keyword, query_type, phrase)

    def _planning_summary_from_keyword(self, keyword: str, query_type: str) -> str:
        phrase = self._heading_subject(keyword)
        if query_type == 'comparison':
            return f'The short answer is that {phrase} is not really about finding one universal winner. It is about which option fits your body, budget, tolerance, and day-to-day routine with the least regret once the hype wears off. The real decision usually gets clearer when you look at side effects, convenience, and what kind of downside you are least willing to absorb.'
        if query_type == 'symptom':
            return f'The short answer is that {phrase} can point to more than one cause, and the useful question is not just what it is called but what pattern sits around it. Timing, repeat triggers, other small warning signs, and how fast the pattern is changing usually matter more than a single abstract explanation.'
        if query_type == 'celebrity':
            return f'The short answer is that {phrase} usually gets flattened into one clean public story, even when the real explanation is a stack of routines, tradeoffs, support, and timing that never makes it into the headline. The useful takeaway is not to copy the visible trick too fast without checking what probably mattered more behind the scenes.'
        return f'The short answer is that {phrase} may help in some situations, but the real story depends on tradeoffs, side effects, cost, adherence, and what happens once the routine stops feeling new. The best read on it usually comes from what changes in real life, not from the clean promise in the headline.'

    def _planning_sections_from_keyword(self, keyword: str, query_type: str) -> list[str]:
        phrase = self._heading_subject(keyword)
        if query_type == 'comparison':
            return [
                f'Similar Promise Different Tradeoff How {phrase} Really Splits',
                'Why This Choice Gets Messy Faster Than People Expect',
                'Who Usually Does Better With Each Option',
                'The Downside That Changes The Decision',
                'What To Do Next Before You Choose',
            ]
        if query_type == 'symptom':
            return [
                f'What {phrase} May Be Trying To Tell You',
                'Why This Pattern Gets Missed At First',
                'The Clues That Matter More Than People Think',
                'When This Stops Being Something To Brush Off',
                'What To Do Next Instead Of Guessing',
            ]
        if query_type == 'celebrity':
            return [
                f'Headline Change Real Life Mess What {phrase} Actually Tells Us',
                'Why People Copy The Wrong Part First',
                'What The Public Story Leaves Out',
                'The Tradeoff Hidden Behind The Transformation',
                'What To Do Instead Of Copying The Headline',
            ]
        return [
            f'Hype Not Proof What Actually Matters About {phrase}',
            'Why People Keep Falling For The Easy Story',
            'What Usually Changes Results In Real Life',
            'Where The Disappointment Shows Up Fast',
            'What To Do Instead If You Want Real Results',
        ]

    def _planning_key_points_from_keyword(self, keyword: str, query_type: str) -> list[str]:
        phrase = self._heading_subject(keyword)
        if query_type == 'comparison':
            return [
                f'The real decision around {phrase} is fit, not just headline strength.',
                'Side effects, cost, and routine friction usually matter more than the first impression.',
                'The better option is often the one someone can actually stay with.'
            ]
        if query_type == 'symptom':
            return [
                f'The useful question around {phrase} is what pattern sits around it.',
                'Repeat timing and other small clues matter more than abstract theory.',
                'A growing pattern deserves more attention than a one-off annoyance.'
            ]
        if query_type == 'celebrity':
            return [
                f'{phrase} usually gets flattened into one clean public story.',
                'Readers often copy the visible habit and miss the invisible support system.',
                'The safer takeaway is to translate the story into something realistic for ordinary life.'
            ]
        return [
            f'{phrase} is rarely as simple as the headline promise makes it sound.',
            'The tradeoffs usually become obvious only after routine, cost, and side effects show up together.',
            'Readers need a real-world verdict, not a polished abstract.'
        ]

    def _build_description(self, keyword: str) -> str:
        description = f"I looked closely at {keyword} to separate the easy promise from what actually matters in real life."
        return self._truncate_description(description)

    def _truncate_description(self, description: str, limit: int = 160) -> str:
        normalized = re.sub(r'\s+', ' ', description).strip()
        if len(normalized) <= limit:
            return normalized
        shortened = normalized[:limit].rstrip(' ,;:-')
        if ' ' in shortened:
            shortened = shortened.rsplit(' ', 1)[0]
        return shortened.rstrip(' ,;:-') + '...'

    def _build_keywords(self, keyword: str) -> str:
        query_type = self._infer_query_type(keyword)
        phrase = self._heading_subject(keyword)
        if query_type == 'comparison':
            base = [keyword, f"{phrase} comparison", f"{phrase} tradeoffs"]
        elif query_type == 'symptom':
            base = [keyword, f"{phrase} causes", f"{phrase} warning signs"]
        elif query_type == 'celebrity':
            base = [keyword, f"{phrase} reality check", f"{phrase} routine"]
        else:
            base = [keyword, f"{phrase} real results", f"{phrase} side effects and cost"]
        return ", ".join(base)

    def _build_article_body(self, keyword: str, markdown_path: Path) -> str:
        overview_video = self._build_video_block(markdown_path, f"{keyword} explainer")
        return f"""> **Disclaimer:** This content is for general educational purposes only and does not replace individualized medical or nutrition advice.

## Table of Contents
- [Overview](#overview)
- [What the headline suggests](#what-the-headline-suggests)
- [What can actually be inferred](#what-can-actually-be-inferred)
- [Why caution matters](#why-caution-matters)
- [Bottom line](#bottom-line)

This topic usually looks simpler from a headline than it does in real life. {keyword} often gets framed as a neat before-and-after story, but the useful part is almost always in the missing context: timing, tradeoffs, health background, and what cannot actually be proven from a public narrative.

## Overview
<!-- IMAGE: {keyword} overview concept -->
At a glance, this story looks like a clean before-and-after result. In practice, stories like this are almost never that simple. A headline can summarize pounds lost, but it rarely explains what happened across diet changes, activity, medication context, stress, disease burden, or long-term follow-through.

## What the headline suggests
Most readers interpret a headline like this as proof that one method worked. That is the first place caution matters. Public retellings often compress a long process into a single cause, and that flattening effect is what makes the story more clickable than useful.

A stronger reading is to treat the headline as a prompt for questions, not an answer. What was actually said publicly? What was inferred by media summaries? Which parts relate to health management, and which parts are just audience projection? Those distinctions matter more than the raw number in the title.

## What can actually be inferred
There are still useful takeaways, even without pretending certainty. Significant body-weight change often reflects multiple overlapping forces: eating pattern changes, reduced intake, increased structure, disease management, improved adherence, medication shifts, or simply time. None of that proves a single diet trick or one universally repeatable plan.

| Question | More careful interpretation | Risk of oversimplifying |
|---|---|---|
| Does the headline prove one method worked? | No, it usually summarizes an outcome rather than a verified mechanism. | Treating publicity as proof. |
| Can readers still learn something? | Yes, mainly about caution, context, and realistic expectations. | Copying a celebrity narrative as if it were a treatment plan. |
| Is a public weight change the same as medical evidence? | No, visual change and medical explanation are not the same thing. | Confusing appearance with verified health guidance. |

A short video explanation is more useful here than near the opening because the framing questions are already on the table and the reader has enough context to judge what the clip adds.
{overview_video}

## Why caution matters
This kind of topic sits inside YMYL territory because readers may try to imitate what they think happened. That is where poor summaries become genuinely unhelpful. If disease context, medication use, or treatment history is involved, then the right lesson is not "do the same thing." The right lesson is to understand how incomplete public health narratives can be.

That is also why a careful article should resist moralizing. Body changes are not proof of discipline, failure, or hidden shortcuts on their own. They are observations. Interpretation requires more context than a headline usually gives.

## Bottom line
The safest takeaway from {keyword} is not that one visible result contains a full method. It is that health-related transformation stories become more useful when we slow them down, separate verifiable information from projection, and treat disease or treatment context as something that cannot be reduced to one dramatic number.

## AI Disclosure
This draft was prepared with AI assistance and structured using a YMYL-oriented editorial workflow.

## References
- [National Institutes of Health](https://www.nih.gov)
- [Centers for Disease Control and Prevention](https://www.cdc.gov)

## Author
**Evidence-Aware Wellness Editor**

I write practical explainers for high-sensitivity health topics by translating viral claims into calmer, more reviewable questions."""

    def _build_article_body_from_plan(self, keyword: str, markdown_path: Path, node: dict) -> str:
        cr = node.get('cr', {}) or {}
        sections = self._normalize_planning_sections(cr.get('st', []) or [], keyword)
        key_points = self._normalize_planning_key_points(cr.get('kp', []) or [], keyword)
        personal_story = str(cr.get('personal_story', self._default_personal_story(keyword))).strip()
        summary = self._truncate_description(str(cr.get('s', self._build_description(keyword))), limit=240)
        toc_lines = ['## Table of Contents'] + [f'- [{section}](#{self._slugify(section)})' for section in sections]
        opening = [
            '> **Disclaimer:** This content is for general educational purposes only and does not replace individualized medical or nutrition advice.',
            '',
            '\n'.join(toc_lines),
            '',
            personal_story,
            '',
            summary,
            '',
        ]
        body_parts = opening
        for index, section in enumerate(sections):
            body_parts.append(f'## {section}')
            if index == 0:
                body_parts.append(f'[IMAGE: {keyword}]')
            body_parts.append(self._compose_section_paragraph(keyword, section, summary, key_points, index))
            body_parts.append('')
        body_parts.extend([
            '## AI Disclosure',
            'This draft was prepared with AI assistance and structured using a YMYL-oriented editorial workflow.',
            '',
            '## References',
            '- [National Institutes of Health](https://www.nih.gov)',
            '- [Centers for Disease Control and Prevention](https://www.cdc.gov)',
            '',
            '## Author',
            f'**{self._default_author_bio(keyword)}**',
        ])
        return '\n'.join(body_parts).strip()

    def _compose_section_paragraph(self, keyword: str, section: str, summary: str, key_points: list[str], index: int) -> str:
        point = key_points[index] if index < len(key_points) else summary
        phrase = self._heading_subject(keyword)
        section_lower = section.lower()
        if any(token in section_lower for token in ('hype', 'proof', 'headline', 'real life mess')):
            return f'This is the part most readers actually care about first. {phrase} usually sounds cleaner from the outside than it feels once routine, cost, side effects, or patience enter the picture. {point}'
        if any(token in section_lower for token in ('falling', 'copy', 'messy', 'miss')):
            return f'People usually get pulled in by the simplest version of the story. The trouble is that {phrase} often works very differently in real life than it does in a headline, and that gap is where most disappointment starts. {point}'
        if any(token in section_lower for token in ('results', 'better', 'clues', 'support system')):
            return f'What changes the outcome is usually more practical than dramatic. Readers tend to do better when they focus on the boring but powerful details behind {phrase}, instead of chasing the most marketable claim. {point}'
        if any(token in section_lower for token in ('disappointment', 'downside', 'warning', 'brush off')):
            return f'This is where the tradeoff becomes real. {phrase} can look promising until the harder part shows up, whether that is side effects, routine friction, missed warning signs, or a result that is less portable than it first looked. {point}'
        if any(token in section_lower for token in ('what to do next', 'what to do instead', 'choose')):
            return f'The useful next move is not to panic or copy the loudest story. It is to turn {phrase} into a smarter decision, one that fits real life instead of just sounding good on paper. {point}'
        query_type = self._infer_query_type(keyword)
        if query_type == 'comparison':
            return f'This comparison only becomes useful once you look past the headline differences. {phrase} usually comes down to tolerance, cost, consistency, and which downside starts to matter first. {point}'
        if query_type == 'symptom':
            return f'The smartest read on {phrase} starts with pattern recognition, not panic. What matters most is which clues travel together, what keeps repeating, and what would make the situation harder to ignore. {point}'
        if query_type == 'celebrity':
            return f'The public version of {phrase} is almost always cleaner than the real story. The important question is what is actually visible, what is being guessed, and what people copy badly when they chase the headline. {point}'
        return f'The real question with {phrase} is whether it holds up once everyday friction shows up. That is where hype usually falls away and a more honest answer starts to appear. {point}'

    def _build_video_block(self, markdown_path: Path, keyword: str) -> str:
        enricher = MultimediaEnricher(build_media_root(markdown_path), article_title=markdown_path.stem)
        video = enricher._resolve_video_asset(keyword)
        iframe_html = ""
        if video.embed_url:
            iframe_html = (
                f'\n<iframe width="560" height="315" src="{video.embed_url}" '
                f'title="YouTube video player" frameborder="0" '
                f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
                f'referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>\n\n'
            )
        commentary = f'> **Editor’s note:** {video.commentary}\n\n' if video.commentary else ""
        return iframe_html + commentary

    def _select_best_stage2_node(self, keyword: str, stage1_2: dict) -> dict:
        candidates: list[dict] = []
        for dsq in stage1_2.get('dsq', []):
            for mt in dsq.get('mt', []):
                candidates.append(mt)
        if not candidates:
            raise ValueError('Stage 1-2 payload does not contain any title plans')
        keyword_tokens = self._tokenize(keyword)
        return max(candidates, key=lambda mt: self._score_stage2_node(mt, keyword_tokens))

    def _score_stage2_node(self, node: dict, keyword_tokens: set[str]) -> int:
        title = str(node.get('t', ''))
        summary = str((node.get('cr') or {}).get('s', ''))
        score = len(self._tokenize(title) & keyword_tokens) * 4
        score += len(self._tokenize(summary) & keyword_tokens)
        if node.get('mty') == 'Exact':
            score += 2
        return score

    def _tokenize(self, value: str) -> set[str]:
        return {token for token in re.findall(r'[a-z0-9]+', value.lower()) if len(token) > 2}

    def _run_stage1_1_llm(self, keyword: str) -> dict | None:
        prompt = self._read_prompt('stage1_1_anqicms.md')
        if not prompt:
            return None
        rendered = (
            prompt.replace('{sq}', keyword)
            .replace('{language}', 'English')
            .replace('{current_year}', '2026')
        )
        text = self._call_gemini(rendered)
        if not text:
            return None
        return self._extract_json_object(text)

    def _run_stage1_2_llm(self, stage1_1: dict) -> dict | None:
        prompt = self._read_prompt('stage1_2_anqicms.md')
        if not prompt:
            return None
        rendered = (
            prompt.replace('{p1}', json.dumps(stage1_1, ensure_ascii=False))
            .replace('{language}', 'English')
            .replace('{current_year}', '2026')
        )
        text = self._call_gemini(rendered)
        if not text:
            return None
        return self._extract_json_object(text)

    def _run_stage2_llm(self, keyword: str, node: dict, style: str) -> str | None:
        prompt = self._read_prompt('stage2_anqicms.md')
        if not prompt:
            return None
        style_rule = self.ARTICLE_STYLE_RULES.get(style, self.ARTICLE_STYLE_RULES['question'])
        content_rules = (
            '\n[Override Rule]\n'
            'These instructions are mandatory. If the draft misses them, rewrite the full draft before returning it. '
            'Treat the keyword as a live search-intent query, not a broad topic. Every section must help the reader solve the exact question behind that query. '
            'If the query asks whether something works, focus on verdict, proof, real-world results, tradeoffs, disappointment points, and who it fits. '
            'If the query is a comparison, focus on differences, tradeoffs, fit, side effects, cost, and who each option suits better. '
            'If the query is about a cause, symptom, or warning sign, focus on what may be behind it, what clues matter, what gets missed, and when not to ignore it. '
            'If the query is about a celebrity, trend, or viral claim, focus on what is actually known, what is speculation, what behavior matters most, and what readers should not blindly copy. '
            'The article must read like a polished, high-conversion magazine feature, not a textbook explainer. '
            'The opening must contain at least 2 substantial paragraphs. Each major H2 section must contain at least 2 full paragraphs or 1 full paragraph plus a meaningful list or table. Thin sections are invalid. '
            'Use a first-person or editor-near first-person voice when it helps the piece feel tested, observed, or lived-in. '
            'Include at least one vivid, concrete client or reader case with specific habit details, a realistic timeline, and a clear outcome or consequence. '
            'Include at least one comparison table that helps the reader judge tradeoffs quickly. '
            'Include one practical replacement plan, protocol, or action guide with at least 3 concrete steps so the reader knows what to do next. '
            'End with a Frequently Asked Questions section that contains at least 4 real-search-sounding long-tail variants of the keyword. '
            'Do not drift into generic background sections, broad health explainers, or long educational detours unless they directly help answer the search intent. '
            'Do not pad the article with generalized mechanism writing just to sound authoritative. '
            'Use exactly one image placeholder and one YouTube video placeholder in the entire article. '
            'Do not place multimedia in every H2. Keep all remaining sections text-only. '
            'The writing must feel like a real editor wrote it: less polished, less repetitive, less templated, and less like compliance copy. '
            'Do not use stock openings like "I approached this topic" or "many readers want to know". '
            'Do not add separator lines such as --- inside the body. '
            'Do not include internal-link placeholders anywhere in the article. '
            'Return plain markdown only, with no code fences. '
            'Use this article style: ' + style_rule
        )
        rendered = self._render_stage2_prompt(keyword, node, prompt + content_rules)
        text = self._call_gemini(rendered)
        if not text:
            return None
        return self._extract_markdown_body(text)

    def _run_stage2_recovery_llm(self, keyword: str, node: dict, style: str) -> str | None:
        prompt = self._read_prompt('stage2_anqicms.md')
        if not prompt:
            return None
        style_rule = self.ARTICLE_STYLE_RULES.get(style, self.ARTICLE_STYLE_RULES['question'])
        recovery_rules = (
            '\n[Recovery Rule]\n'
            'The previous draft failed the output contract. Rewrite the article from scratch in a stricter, more magazine-like, more search-intent-locked form. '
            'Keep the article tightly locked to the keyword\'s search intent instead of broadening it into a general health explainer. '
            'Use exactly five H2 sections, keep paragraphs short, include only one image placeholder in the whole article, and do not manually include YouTube commentary lines. '
            'Even in recovery mode, the article still needs one vivid case study, one comparison table, one practical action guide with at least 3 steps, and one FAQ section with at least 4 real-search-sounding questions. '
            'The opening still needs 2 substantial paragraphs. Thin sections are invalid. '
            'The H2s must sound like a magazine editor wrote them, using contrast, tension, or a real-world hook instead of textbook phrasing. '
            'If the rewrite still sounds academic, generic, or too short, rewrite it again before returning the output. '
            'Return plain markdown only without code fences or frontmatter. '
            'If the keyword is asking whether something works, the rewrite should stay verdict-driven. If it is a comparison, stay choice-driven. If it is asking why something happens, stay cause-driven. If it is celebrity or trend driven, stay reality-check driven. '
            'Keep this article style: ' + style_rule
        )
        rendered = self._render_stage2_prompt(keyword, node, prompt + recovery_rules)
        text = self._call_gemini(rendered)
        if not text:
            return None
        return self._extract_markdown_body(text)

    def _run_stage2_segmented_llm(self, keyword: str, node: dict, style: str) -> str | None:
        prompt = self._read_prompt('stage2_anqicms.md')
        if not prompt:
            return None
        cr = node.get('cr', {}) or {}
        sections = self._normalize_planning_sections(cr.get('st', []) or [], keyword)
        key_points = self._normalize_planning_key_points(cr.get('kp', []) or [], keyword)
        if not sections:
            return None

        title = self._normalize_final_title(str(node.get('t', keyword)), keyword)
        summary = str(cr.get('s', self._build_description(keyword))).strip()
        persona = str(cr.get('author_bio', self._default_author_bio(keyword))).strip()
        personal_story = str(cr.get('personal_story', self._default_personal_story(keyword))).strip()
        style_rule = self.ARTICLE_STYLE_RULES.get(style, self.ARTICLE_STYLE_RULES['question'])
        intro = self._build_segmented_opening(keyword, title, summary, personal_story)
        segments: list[str] = []
        section_bodies: list[str] = []

        for index, section in enumerate(sections[:5]):
            point = key_points[index] if index < len(key_points) else summary
            previous_text = '\n\n'.join(section_bodies[-2:]) if section_bodies else intro
            segment_prompt = (
                'Write one markdown section for a high-CTR YMYL editorial article. Return only the section body paragraphs and optional list or table. '
                'Do not include frontmatter. Do not include the H2 heading in your answer. Do not include AI disclosure, references, or author blocks. '
                'Stay tightly aligned with the assigned section heading and the article search intent. '
                'The writing must sound like a grounded editor, not a textbook or compliance memo. '
                'Use concrete detail, natural rhythm, and direct judgment. '
                'This is part of a larger shared-outline article, so keep continuity with the title, summary, prior sections, and persona. '
                'If this section is the one about action or next steps, include a concrete numbered list with at least 3 steps. '
                'If this section is the one about tradeoffs or comparison, include a meaningful markdown table when useful. '
                'If this section is about a case, regret, disappointment, or what people miss, include vivid real-life specifics such as timeline, habits, friction, side effects, or turning points. '
                'Avoid generic filler and avoid repeating the same opener sentence structure. '
                'Use this article style: ' + style_rule + '\n\n'
                f'Article title: {title}\n'
                f'Keyword: {keyword}\n'
                f'Editorial summary: {summary}\n'
                f'Author persona: {persona}\n'
                f'Personal story seed: {personal_story}\n'
                f'Section heading: {section}\n'
                f'Section key point: {point}\n'
                f'Previous article context:\n{previous_text}\n\n'
                'Return 2 to 4 substantial paragraphs, or 1 substantial paragraph plus a strong table/list if that better fits the section.'
            )
            text = self._call_gemini_with_retry(segment_prompt, attempts=2)
            if not text:
                section_body = self._compose_section_paragraph(keyword, section, summary, key_points, index)
            else:
                section_body = self._clean_segmented_section_body(text)
            if (
                not section_body.strip()
                or self._section_has_clinical_tone(section_body)
                or self._section_has_query_drift(section_body, keyword)
            ):
                section_body = self._compose_section_paragraph(keyword, section, summary, key_points, index)
            section_bodies.append(section_body.strip())
            media_prefix = ''
            if index == 0:
                media_prefix = f'[IMAGE: {keyword}]\n\n'
            if index == 2:
                media_prefix = media_prefix + f'[YOUTUBE_VIDEO: {keyword} review results side effects]\n\n'
            segments.append(f'## {section}\n\n{media_prefix}{section_body.strip()}')

        toc_lines = ['## Table of Contents'] + [f'- [{section}](#{self._slugify(section)})' for section in sections[:5]]
        body = '\n\n'.join([
            '> **Disclaimer:** This content is for general educational purposes only and does not replace individualized professional advice.',
            '',
            '\n'.join(toc_lines),
            '',
            intro,
            '',
            '\n\n'.join(segments),
        ])
        return body.strip()

    def _build_segmented_opening(self, keyword: str, title: str, summary: str, personal_story: str) -> str:
        phrase = self._heading_subject(keyword)
        second_paragraph = (
            f'The short answer on {phrase} is rarely as clean as the headline makes it sound. '
            f'{summary}'
        )
        return f'{personal_story}\n\n{second_paragraph}'.strip()

    def _clean_segmented_section_body(self, text: str) -> str:
        body = self._extract_markdown_body(text)
        body = re.sub(r'^##\s+[^\n]+\s*\n+', '', body, count=1, flags=re.MULTILINE)
        body = re.sub(r'^#{1,6}\s+[^\n]+\s*\n+', '', body, flags=re.MULTILINE)
        body = re.sub(r'\n##\s+(AI Disclosure|References|Author)\s*[\s\S]*$', '', body, flags=re.IGNORECASE)
        body = re.sub(r'\b(clinical intervention|dual agonism|glp-1 receptors|gip|clinical trials?|documented safety profile|mechanism of action|efficacy|contraindications?)\b', '', body, flags=re.IGNORECASE)
        body = re.sub(r'\s{2,}', ' ', body)
        return body.strip()

    def _section_has_clinical_tone(self, text: str) -> bool:
        lowered = text.lower()
        banned = (
            'clinical trial',
            'clinical intervention',
            'dual agonism',
            'glp-1 receptor',
            'gip',
            'documented safety profile',
            'mechanism of action',
            'contraindication',
            'efficacy',
            'systematic review',
        )
        return any(token in lowered for token in banned)

    def _section_has_query_drift(self, text: str, keyword: str) -> bool:
        lowered = text.lower()
        keyword_lower = keyword.lower()
        drift_map = {
            'celebrity': ('celebrity', 'headline gossip', 'copy a celebrity', 'star routine'),
            'drink': ('soda', 'sweet drinks', 'coffee creamer', 'belly fat drink'),
            'timing': ('morning or later in the day', 'empty stomach', 'bedtime drink'),
        }
        if not any(token in keyword_lower for token in ('celebrity', 'actor', 'singer', "'s weight loss")):
            if any(token in lowered for token in drift_map['celebrity']):
                return True
        if not any(token in keyword_lower for token in ('drink', 'tea', 'coffee', 'smoothie', 'juice', 'soda')):
            if any(token in lowered for token in drift_map['drink']):
                return True
        if not any(token in keyword_lower for token in ('morning', 'night', 'timing', 'when should')):
            if any(token in lowered for token in drift_map['timing']):
                return True
        return False

    def _ensure_standard_tail(self, body: str, keyword: str, node: dict) -> str:
        cleaned = body.strip()
        cleaned = re.sub(r'\n##\s+AI Disclosure\s*[\s\S]*$', '', cleaned, flags=re.IGNORECASE)
        author_bio = str((node.get('cr') or {}).get('author_bio', self._default_author_bio(keyword))).strip()
        tail = (
            '## AI Disclosure\n'
            'This article draft was prepared with AI assistance and reviewed through a structured editorial workflow.\n\n'
            '## Author\n'
            f'**{author_bio}**'
        )
        return cleaned.rstrip() + '\n\n' + tail

    def _render_stage2_prompt(self, keyword: str, node: dict, prompt: str) -> str:
        cr = node.get('cr', {})
        cs = node.get('cs', {})
        return (
            prompt
            .replace('{title}', str(node.get('t', keyword)))
            .replace('{q}', keyword)
            .replace('{summary}', str(cr.get('s', self._build_description(keyword))))
            .replace('{sections}', json.dumps(cr.get('st', []), ensure_ascii=False))
            .replace('{key_points}', json.dumps(cr.get('kp', []), ensure_ascii=False))
            .replace('{ac}', str(cs.get('ac', 'US')))
            .replace('{ar}', str(cs.get('ar', '')))
            .replace('{al}', str(cs.get('al', '')))
            .replace('{tm}', 'false')
            .replace('{ymyl_level}', 'true')
            .replace('{author_bio}', str(cr.get('author_bio', 'Evidence-Aware Wellness Editor')))
            .replace('{personal_story}', str(cr.get('personal_story', f'I kept seeing {keyword} framed too neatly, so I stayed with the harder question of what a reader actually needs to know before acting on it.')))
            .replace('{current_year}', '2026')
            .replace('{url}', '/')
        )

    def _is_usable_stage2_body(self, body: str) -> bool:
        normalized = body.strip()
        if len(normalized) < 1200:
            return False
        if normalized.count('## ') < 4:
            return False
        if '## Table of Contents' not in normalized:
            return False
        if not re.search(r'\n##\s+[^\n]+\n\n.+', normalized, re.DOTALL):
            return False
        if normalized.rstrip().endswith('-'):
            return False
        return True

    def _read_prompt(self, name: str) -> str | None:
        path = self.workspace_root / 'references' / 'prompts' / name
        if not path.is_file():
            return None
        return path.read_text(encoding='utf-8')

    def _call_gemini(self, prompt: str) -> str | None:
        config = self._load_llm_config()
        api_key = config.get('GEMINI_API_KEY') or config.get('ANQICMS_GEMINI_API_KEY')
        model = config.get('GEMINI_MODEL') or 'gemini-2.5-pro'
        base_url = config.get('GEMINI_BASE_URL') or config.get('ANQICMS_GEMINI_BASE_URL')
        if not api_key or not base_url:
            return None
        url = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent"
        payload = {
            'contents': [
                {
                    'parts': [
                        {'text': prompt}
                    ]
                }
            ],
            'generationConfig': {
                'temperature': 0.3,
                'topP': 0.9,
                'maxOutputTokens': 8192,
            },
        }
        try:
            response = requests.post(url, params={'key': api_key}, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            return None
        candidates = data.get('candidates') or []
        for candidate in candidates:
            parts = ((candidate.get('content') or {}).get('parts')) or []
            text = ''.join(part.get('text', '') for part in parts if isinstance(part, dict))
            if text.strip():
                return text.strip()
        return None

    def _call_gemini_with_retry(self, prompt: str, attempts: int = 2) -> str | None:
        for _ in range(max(1, attempts)):
            text = self._call_gemini(prompt)
            if text:
                return text
        return None

    def _load_llm_config(self) -> dict[str, str]:
        config: dict[str, str] = {}
        candidate_paths = [
            self.workspace_root / 'local_api_keys.json',
            self.workspace_root / 'scripts' / 'local_api_keys.json',
        ]
        for path in candidate_paths:
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding='utf-8'))
                except json.JSONDecodeError:
                    data = {}
                if isinstance(data, dict):
                    for key, value in data.items():
                        if isinstance(value, str) and value.strip():
                            config[key] = value.strip()
                break
        for key in (
            'GEMINI_API_KEY',
            'ANQICMS_GEMINI_API_KEY',
            'GEMINI_MODEL',
            'GEMINI_BASE_URL',
            'ANQICMS_GEMINI_BASE_URL',
        ):
            value = os.environ.get(key)
            if value and value.strip():
                config[key] = value.strip()
        return config

    def _extract_json_object(self, text: str) -> dict | None:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _extract_title_candidates(self, data: dict) -> list[str]:
        raw_titles = data.get('titles')
        if not isinstance(raw_titles, list):
            single = str(data.get('title', '')).strip()
            return [single] if single else []
        titles: list[str] = []
        for item in raw_titles:
            title = str(item).strip()
            if title and title not in titles:
                titles.append(title)
        return titles

    def _select_best_title_candidate(self, keyword: str, titles: list[str], style: str) -> tuple[str | None, list[str]]:
        if not titles:
            return None, ['no title candidates returned']
        banned_phrases = (
            'reviewing the clinical evidence',
            'what the clinical evidence shows',
            'clinical evidence safely shows',
            'efficacy review',
            'clinical trial results',
            'effectiveness',
            'explained',
            'eligibility',
            'the clinical evidence',
        )
        keyword_tokens = self._tokenize(keyword)
        accepted: list[str] = []
        rejected_reasons: list[str] = []

        def reject_reason(title: str) -> str | None:
            lowered = title.lower()
            if any(phrase in lowered for phrase in banned_phrases):
                return f'rejected banned clinical-review phrasing: {title}'
            if len(title) > 82:
                return f'rejected too long: {title}'
            return None

        def score(title: str) -> int:
            lowered = title.lower()
            value = len(self._tokenize(title) & keyword_tokens) * 5
            if ':' not in title:
                value += 2
            else:
                value -= 1
            if style == 'question':
                value += 8 if '?' in title else -3
            if style == 'versus':
                value += 8 if (' vs ' in lowered or ' versus ' in lowered) else -2
            if style == 'truth':
                value += 8 if any(token in lowered for token in ('truth', 'scam', 'gets wrong', 'really', 'myth', 'hype')) else -2
            if style == 'test':
                value += 8 if any(token in lowered for token in ('put to the test', 'holds up', 'tested', 'verdict', 'actually work', 'worth it', 'tried')) else -2
            if style == 'best':
                value += 8 if any(token in lowered for token in ('best ', 'which ', 'worth it')) else -2
            if any(phrase in lowered for phrase in banned_phrases):
                value -= 20
            return value

        for title in titles:
            reason = reject_reason(title)
            if reason:
                rejected_reasons.append(reason)
                continue
            accepted.append(title)

        if not accepted:
            return None, rejected_reasons
        ranked = sorted(accepted, key=score, reverse=True)
        return ranked[0], rejected_reasons

    def _extract_markdown_body(self, text: str) -> str:
        fenced_blocks = re.findall(r'```markdown\s*(.*?)```', text, re.DOTALL)
        candidates = [block.strip() for block in fenced_blocks if block.strip()]
        candidates.append(text.strip())
        for raw in candidates:
            metadata, body = parse_mdx_frontmatter(raw)
            if body.strip():
                return body.strip()
            if raw.startswith('---'):
                return raw
        return text.strip()

    def _normalize_media_blocks(self, body: str, markdown_path: Path, keyword: str) -> str:
        body = re.sub(r'^```markdown\s*', '', body, flags=re.MULTILINE)
        body = re.sub(r'\n```\s*$', '', body, flags=re.MULTILINE)
        body = re.sub(r'^---\s*\n.*?\n---\s*\n', '', body, count=1, flags=re.DOTALL)
        body = re.sub(r'[^\n.?!]*\[INTERNAL_LINK:[^\]]+\][^\n.?!]*[.?!]?', '', body)
        body = re.sub(r'\[INTERNAL_LINK:[^\]]+\]', '', body)
        image_match = re.search(r'<!--\s*IMAGE:.*?-->', body)
        if not image_match:
            image_block = f'<!-- IMAGE: {keyword} overview concept -->'
            first_body_heading = self._find_first_body_heading(body)
            if first_body_heading:
                insert_at = first_body_heading.end()
                body = body[:insert_at] + '\n' + image_block + body[insert_at:]
        body = self._strip_extra_image_placeholders(body)
        body = self._replace_video_placeholders_with_real_block(body, markdown_path, keyword)
        body = self._strip_extra_video_blocks(body)
        body = self._sanitize_references(body)
        return body.strip()

    def _strip_extra_image_placeholders(self, body: str) -> str:
        seen = 0
        kept: list[str] = []
        for line in body.splitlines():
            if '<!-- IMAGE:' in line:
                seen += 1
                if seen > 1:
                    continue
            kept.append(line)
        return '\n'.join(kept)

    def _replace_video_placeholders_with_real_block(self, body: str, markdown_path: Path, keyword: str) -> str:
        pattern = re.compile(r'(?:\*\*|__|\*)?\s*(?:<!--\s*YOUTUBE_VIDEO:\s*(.*?)\s*-->|\[YOUTUBE_VIDEO:\s*(.*?)\s*\])\s*(?:\*\*|__|\*)?')
        seen = 0

        def repl(match: re.Match[str]) -> str:
            nonlocal seen
            seen += 1
            if seen > 1:
                return ''
            video_keyword = (match.group(1) or match.group(2) or '').strip() or f'{keyword} explainer'
            return self._build_video_block(markdown_path, video_keyword)

        converted = pattern.sub(repl, body)
        if seen == 0 and 'youtube.com/embed' not in converted and '[Watch on YouTube](' not in converted:
            insert_at = self._find_video_insertion_point(converted)
            if insert_at is not None:
                converted = converted[:insert_at] + '\n\n' + self._build_video_block(markdown_path, f'{keyword} explainer') + converted[insert_at:]
        return converted

    def _strip_extra_video_blocks(self, body: str) -> str:
        lines = body.splitlines()
        iframe_seen = 0
        watch_seen = 0
        filtered: list[str] = []
        skipping_video_tail = False
        for line in lines:
            stripped = line.strip()
            if '<iframe ' in stripped and 'youtube.com/embed' in stripped:
                iframe_seen += 1
                if iframe_seen > 1:
                    skipping_video_tail = True
                    continue
                skipping_video_tail = False
                filtered.append(line)
                continue
            if stripped.startswith('[Watch on YouTube]('):
                watch_seen += 1
                if watch_seen > 1 or skipping_video_tail:
                    skipping_video_tail = False
                    continue
                filtered.append(line)
                continue
            filtered.append(line)
        return '\n'.join(filtered)

    def _find_first_body_heading(self, body: str) -> re.Match[str] | None:
        matches = re.finditer(r'(^##\s+[^\n]+\s*$)', body, re.MULTILINE)
        for match in matches:
            title = match.group(0)[3:].strip().lower()
            if title != 'table of contents':
                return match
        return None

    def _find_video_insertion_point(self, body: str) -> int | None:
        matches = list(re.finditer(r'^##\s+[^\n]+\s*$', body, re.MULTILINE))
        body_matches = [m for m in matches if m.group(0)[3:].strip().lower() != 'table of contents']
        if len(body_matches) >= 2:
            return body_matches[1].start()
        if body_matches:
            return len(body)
        return None

    def _sanitize_references(self, body: str) -> str:
        return re.sub(
            r'\[([^\]]+)\]\(\[?(https?://[^)\]]+)\]?\([^)]*\)\)',
            r'[\1](\2)',
            body,
        )

    def _normalize_article_voice(self, body: str, title: str, keyword: str) -> str:
        body = re.sub(r'\bIn conclusion,\s*', '', body)
        body = re.sub(r'\bFurthermore,\s*', '', body)
        body = re.sub(r'\bIt is important to note that\s*', '', body, flags=re.IGNORECASE)
        body = re.sub(r'\bThis topic usually looks simpler from a headline than it does in real life\.\s*', '', body)
        body = re.sub(r'(?m)^(online|some users)\b', lambda m: m.group(1).capitalize(), body)

        preamble = self._extract_body_preamble(body)
        tail = self._extract_body_tail(body)
        sections = self._split_body_sections(body)
        rebuilt_sections = [
            f'## {self._normalize_section_heading(heading, keyword, index)}\n\n{self._align_section_content_to_intent(content.strip(), keyword, index)}'
            for index, (heading, content) in enumerate(sections[:5])
            if content.strip()
        ]

        parts = []
        if preamble:
            parts.append(preamble)
        if rebuilt_sections:
            parts.append('\n\n'.join(rebuilt_sections))
        body = '\n\n'.join(part for part in parts if part).strip()
        body = self._ensure_case_study_block(body, keyword)
        body = self._ensure_comparison_table(body, keyword)
        body = self._ensure_action_guide(body, keyword)
        body = self._ensure_faq_block(body, keyword)
        body = self._enforce_single_image_placeholder(body, keyword)
        body = self._enforce_single_video_block(body, keyword)
        body = self._normalize_table_of_contents(body)
        body = self._validate_article_contract(body, title, keyword)
        if tail:
            body = body.rstrip() + '\n\n' + tail
        return body.strip()

    def _normalize_section_heading(self, heading: str, keyword: str, index: int) -> str:
        cleaned = re.sub(r'\s+', ' ', heading).strip(' -')
        if not cleaned:
            cleaned = self._fallback_heading_for_index(keyword, index)
        lowered = cleaned.lower()
        generic_headings = {
            'the short answer most people want first',
            'why this keeps coming up',
            'which details matter before you sign up',
            'what can go wrong if you ignore the tradeoffs',
            'the bottom line before you make a change',
        }
        dry_tokens = (
            'overview',
            'mechanism',
            'research review',
            'clinical evidence',
            'current studies',
            'effectiveness',
            'safety profile',
        )
        if lowered in generic_headings or any(token == lowered for token in dry_tokens):
            return self._fallback_heading_for_index(keyword, index)
        if ':' in cleaned:
            cleaned = cleaned.replace(':', '')
        return cleaned

    def _fallback_heading_for_index(self, keyword: str, index: int) -> str:
        phrase = self._heading_subject(keyword)
        intent = self._infer_search_intent(keyword)
        template_map = {
            'verdict': [
                f'Hype, Not Proof What {phrase} Really Has Going For It',
                f'Why People Keep Falling for the Easy Story Around {phrase}',
                f'What to Check Before You Spend Money on {phrase}',
                f'Where {phrase} Can Let You Down Fast',
                f'The Honest Bottom Line on {phrase}',
            ],
            'comparison': [
                f'Similar Promise, Different Tradeoff How {phrase} Really Splits',
                f'Why This Comparison Gets Confusing Fast',
                f'Which Tradeoffs Matter Before You Choose',
                f'Who Usually Regrets Picking the Wrong One',
                f'The Smarter Pick for Most Buyers',
            ],
            'best': [
                f'What Separates the Better {phrase} Options',
                f'Why So Many {phrase} Lists Miss the Point',
                f'What to Check Before You Buy',
                f'Where Cheap Picks Usually Backfire',
                f'The Shortlist I Would Build First',
            ],
            'cause': [
                f'What May Really Be Behind {phrase}',
                f'Why This Pattern Shows Up So Often',
                f'Which Clues Matter More Than People Think',
                f'What Gets Missed When You Brush It Off',
                f'When {phrase} Deserves More Attention',
            ],
            'how_to': [
                f'How {phrase} Usually Works in Real Life',
                f'Why This Approach Sounds Easier Than It Is',
                f'What to Set Up Before You Start',
                f'Where People Get Tripped Up',
                f'The Simplest Way to Think About {phrase}',
            ],
        }
        templates = template_map.get(intent, [
            f'Why {phrase} Sounds Smarter Than It Usually Is',
            f'What People Miss When They Bet on {phrase}',
            f'What to Check Before You Try {phrase}',
            f'Where {phrase} Can Disappoint You Fast',
            f'The Honest Call on {phrase}',
        ])
        if 0 <= index < len(templates):
            return templates[index]
        return f'What Matters Most About {phrase}'

    def _infer_search_intent(self, keyword: str) -> str:
        lowered = keyword.lower()
        if any(token in lowered for token in (' vs ', ' versus ', 'compare', 'comparison')):
            return 'comparison'
        if any(token in lowered for token in ('best', 'top ', 'better', 'which one', 'which is better')):
            return 'best'
        if any(token in lowered for token in ('why', 'cause', 'causes', 'reason', 'trigger', 'symptom')):
            return 'cause'
        if any(token in lowered for token in ('how to', 'how do', 'steps', 'routine', 'plan')):
            return 'how_to'
        if any(token in lowered for token in ('does', 'work', 'worth it', 'scam', 'legit', 'real', 'actually', 'reviews')):
            return 'verdict'
        if any(token in lowered for token in ('weight loss', 'fat loss', 'blood sugar', 'glucose', 'cbd', 'gummies', 'supplement', 'recipe', 'drink')):
            return 'verdict'
        return 'default'

    def _infer_query_type(self, keyword: str) -> str:
        lowered = keyword.lower()
        comparison_tokens = (
            ' vs ',
            ' versus ',
            'compare',
            'comparison',
            'better than',
            'which is better',
            'which one is better',
        )
        if any(token in lowered for token in comparison_tokens):
            if 'or do you gain it all back' not in lowered:
                return 'comparison'
        if (
            ('which is better' in lowered or 'which one is better' in lowered)
            and re.search(r'\b[a-z0-9][a-z0-9\- ]+\s+or\s+[a-z0-9][a-z0-9\- ]+\b', lowered)
        ):
            return 'comparison'
        if any(token in lowered for token in ('why', 'cause', 'causes', 'reason', 'trigger', 'symptom')):
            return 'symptom'
        if any(token in lowered for token in ('celebrity', 'star', 'singer', 'actor')):
            return 'celebrity'
        if re.search(r"\b[a-z]+\s+[a-z]+['’]s\b", lowered):
            return 'celebrity'
        if any(token in lowered for token in ('trend', 'viral', 'tiktok', 'instagram', 'hack')):
            return 'celebrity'
        if any(token in lowered for token in ('does', 'work', 'worth it', 'scam', 'legit', 'reviews', 'actually')):
            return 'review'
        return 'review'

    def _align_section_content_to_intent(self, content: str, keyword: str, index: int) -> str:
        intent = self._infer_search_intent(keyword)
        lowered = content.lower()
        generic_markers = (
            'clinical data shows',
            'for decades',
            'traditionally used',
            'the mechanism',
            'this topic sits inside ymyl territory',
            'in practice, stories like this are almost never that simple',
        )
        if not any(marker in lowered for marker in generic_markers):
            return content
        phrase = self._heading_subject(keyword)
        if intent == 'verdict':
            fallbacks = [
                f'This is the part most readers care about first: whether {phrase} holds up outside the marketing. The useful answer is usually not a flat yes or no, but how strong the real-world payoff looks, what the catch is, and who is most likely to feel underwhelmed.',
                f'Questions about {phrase} keep spreading because the promise sounds cleaner than the lived experience. Once money, side effects, time, or adherence enter the picture, the gap between the pitch and the likely result gets easier to see.',
                f'Before someone commits to {phrase}, the decision points are usually practical rather than theoretical: cost, effort, side effects, timeline, and whether the expected payoff is big enough to justify the hassle.',
                f'The disappointment risk with {phrase} usually shows up when buyers assume the headline result will transfer to them without friction. That is where expectations, tolerability, and fit matter more than hype.',
                f'The fairest takeaway on {phrase} is whether the upside looks real enough for the right person and whether the tradeoffs still look acceptable once the excitement wears off.',
            ]
        elif intent == 'comparison':
            fallbacks = [
                f'The real value in comparing {phrase} is not declaring one winner in the abstract. It is seeing where each option feels stronger, where the tradeoffs change, and what kind of user usually does better with one over the other.',
                f'This comparison gets messy because readers often compare headline benefits while skipping over fit, tolerability, cost, and how hard each option is to stay on long enough to matter.',
                f'The smarter way to judge {phrase} is to look at the tradeoffs that actually affect a decision: expected results, side effects, convenience, and what kind of commitment each path demands.',
                f'People usually regret a comparison like {phrase} when they choose based on hype or speed alone. The better choice often depends on what kind of downside they are least willing to deal with.',
                f'The best conclusion on {phrase} is not which option sounds stronger in theory, but which one looks more realistic for the person making the choice.',
            ]
        elif intent == 'cause':
            fallbacks = [
                f'With {phrase}, the first useful move is to think in causes, not labels. Several different patterns can sit behind the same complaint, and the clues around timing, severity, and context usually matter more than a generic explanation.',
                f'This kind of question keeps coming up because the symptom is easy to notice but harder to interpret. Small details often change which cause is most likely and which one deserves faster attention.',
                f'The most useful clues around {phrase} are usually the ones people skip at first: when it happens, what else changed, and what other signs show up alongside it.',
                f'What gets missed with {phrase} is that waiting too long or brushing it off can delay the right response. That matters more when the pattern is getting stronger, more frequent, or harder to explain.',
                f'The bottom line on {phrase} is not to panic over every possibility, but not to flatten a meaningful pattern into a vague everyday annoyance either.',
            ]
        else:
            fallbacks = [
                f'The useful part of {phrase} is not the broad topic itself, but what a reader actually needs to decide, avoid, or understand before acting on it.',
                f'Interest in {phrase} usually rises when the promise sounds easier than the reality. That is where context starts mattering more than the headline.',
                f'Before someone acts on {phrase}, the practical checks usually matter more than extra theory.',
                f'The main mistake around {phrase} is treating a partial story like a complete answer.',
                f'The strongest takeaway on {phrase} is the one that stays closest to the reader\'s actual decision.',
            ]
        if 0 <= index < len(fallbacks):
            return fallbacks[index]
        return content

    def _validate_article_contract(self, body: str, title: str, keyword: str) -> str:
        lowered_title = title.lower()
        invalid_title_tokens = ('clinical evidence', 'effectiveness', 'analyzed', 'explained', 'research review')
        if any(token in lowered_title for token in invalid_title_tokens):
            raise ValueError(f'Generated title failed editorial contract: {title}')
        headings = re.findall(r'^##\s+([^\n]+)\s*$', body, re.MULTILINE)
        invalid_heading_tokens = ('overview', 'mechanism', 'clinical evidence', 'benefits', 'risks', 'explained')
        for heading in headings:
            lowered = heading.lower()
            if any(token in lowered for token in invalid_heading_tokens):
                raise ValueError(f'Generated heading failed editorial contract: {heading}')
        required_checks = [
            ('case study', '## The Case' in body or '## The Real-Life Pattern' in body),
            ('comparison table', '|' in body and re.search(r'^\|.*\|$', body, re.MULTILINE) is not None),
            ('action guide', re.search(r'^## What To Do', body, re.MULTILINE) is not None),
            ('faq block', re.search(r'^## Frequently Asked Questions\s*$', body, re.MULTILINE) is not None),
        ]
        for label, passed in required_checks:
            if not passed:
                raise ValueError(f'Generated article failed editorial contract: missing {label}')
        faq_matches = re.findall(r'^###\s+.+?\n\n(.*?)(?=\n###\s+|\n##\s+|\Z)', body, re.MULTILINE | re.DOTALL)
        if len(faq_matches) < 4:
            raise ValueError('Generated article failed editorial contract: FAQ too thin')
        for answer in faq_matches[:4]:
            if len(re.findall(r'\b\w+\b', answer)) < 100:
                raise ValueError('Generated article failed editorial contract: FAQ answers too short')
        return body

    def _heading_subject(self, keyword: str) -> str:
        cleaned = re.sub(r'\s+', ' ', keyword).strip(' -')
        if not cleaned:
            return 'this option'
        lowered = cleaned.lower()
        special_cases = [
            (r'^does ozempic weight loss actually last or do you gain it all back$', 'Ozempic weight loss over time'),
            (r'^does mounjaro actually work for long[- ]term weight loss$', 'Mounjaro for long-term weight loss'),
            (r'^does hers weight loss actually work$', 'the Hers weight loss program'),
            (r'^does jelly roll\'s weight loss approach actually work for sustained results$', "Jelly Roll's weight loss approach"),
        ]
        for pattern, replacement in special_cases:
            if re.match(pattern, lowered, flags=re.IGNORECASE):
                return replacement
        if ' vs ' in lowered or ' versus ' in lowered:
            parts = re.split(r'\s+(?:vs|versus)\s+', cleaned, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                left = self._heading_subject(parts[0])
                right = self._heading_subject(parts[1])
                return f'{left} vs {right}'
        better_than_match = re.match(r'^(?:is|are|does)?\s*(.+?)\s+better than\s+(.+)$', cleaned, flags=re.IGNORECASE)
        if better_than_match:
            left = self._heading_subject(better_than_match.group(1))
            right = self._heading_subject(better_than_match.group(2))
            return f'{left} vs {right}'
        which_better_match = re.match(r'^which(?:\s+one|\s+option)?\s+is\s+better\s+(.+)$', cleaned, flags=re.IGNORECASE)
        if which_better_match:
            cleaned = which_better_match.group(1)
            or_match = re.match(r'^(?:for\s+[^\s]+\s+)?(.+?)\s+or\s+(.+)$', cleaned, flags=re.IGNORECASE)
            if or_match:
                left = self._heading_subject(or_match.group(1))
                right = self._heading_subject(or_match.group(2))
                suffix = ''
                if cleaned.lower().startswith('for '):
                    suffix = re.match(r'^(for\s+[^\s]+)', cleaned, flags=re.IGNORECASE).group(1)
                    return f'{left} vs {right} {suffix}'.strip()
                return f'{left} vs {right}'
        patterns = [
            r'^does\s+',
            r'^is\s+my\s+',
            r'^is\s+',
            r'^are\s+',
            r'^can\s+',
            r'^should\s+',
            r'^why\s+is\s+my\s+',
            r'^why\s+is\s+',
            r'^why\s+does\s+',
            r'^why\s+do\s+',
            r'^how\s+to\s+',
            r'^how\s+do\s+i\s+',
            r'^how\s+do\s+',
            r'^what\s+is\s+',
            r'^what\s+are\s+',
        ]
        for pattern in patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bor do you gain it all back\b', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(actually|really|work|works|reviews?)\b', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bbetter than\b', 'vs', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\blong term\b', 'long-term', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\blemon water weight loss\b', 'lemon water for weight loss', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bcbd gummies sleep\b', 'CBD gummies for sleep', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bcbd oil better than gummies for sleep\b', 'CBD oil vs gummies for sleep', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bozempic weight loss last\b', 'Ozempic weight loss over time', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip(' -?')
        if not cleaned:
            return 'this option'
        if any(char.islower() for char in cleaned):
            return cleaned[0].lower() + cleaned[1:]
        return cleaned.title()

    def _split_body_sections(self, body: str) -> list[tuple[str, str]]:
        matches = list(re.finditer(r'^##\s+([^\n]+)\s*$', body, re.MULTILINE))
        sections: list[tuple[str, str]] = []
        for index, match in enumerate(matches):
            heading = match.group(1).strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            if heading.lower() in {'table of contents', 'ai disclosure', 'references', 'author'}:
                continue
            sections.append((heading, body[start:end].strip()))
        return sections

    def _ensure_case_study_block(self, body: str, keyword: str) -> str:
        existing_case_heading = re.search(
            r'^##\s+(the case|the real-life pattern|the story|what happened when)\b',
            body,
            re.IGNORECASE | re.MULTILINE,
        )
        if existing_case_heading:
            return body
        phrase = self._heading_subject(keyword)
        query_type = self._infer_query_type(keyword)
        if query_type == 'celebrity':
            block = (
                '## The Real-Life Pattern People Miss When They Copy a Celebrity\n\n'
                f'One reader I heard from tried to mirror a celebrity-style version of {phrase} almost word for word. For six weeks, she copied the headline habits she saw online, cut meals too aggressively on busy days, and assumed the visible transformation meant the plan itself must be enough. Her weight barely moved, but her energy dipped hard by late afternoon and she kept rebounding into convenience eating at night. The useful takeaway was that copying a public result is not the same as copying the real conditions behind it. Most of the invisible support system never makes it into the headline.'
            )
        elif query_type == 'comparison':
            block = (
                '## The Case That Shows Why This Choice Is Not Just About the Headline Promise\n\n'
                f'One reader I worked with kept bouncing between two versions of {phrase} because one sounded faster and the other sounded safer. After about two months of second-guessing, the real issue was not motivation but mismatch: the option she picked first asked more of her schedule and tolerance than she could realistically sustain. Once she chose the path that fit her day-to-day life better, the decision finally stopped feeling chaotic. That is usually the missing layer in a comparison query like this.'
            )
        elif query_type == 'symptom':
            block = (
                '## The Case That Makes This More Than a Throwaway Symptom\n\n'
                f'One reader kept brushing off {phrase} as a random annoyance because it came and went. Over several weeks, the pattern got easier to notice: it happened at similar times, came with other small signs she had ignored, and started disrupting her sleep and routine. What changed the outcome was not panic. It was finally treating the pattern like a clue instead of a quirk.'
            )
        else:
            block = (
                '## The Case That Changed My Mind About the Hype\n\n'
                f'One reader I worked with built a full routine around {phrase} and expected the scale to move fast. She was drinking it two or three times a day, skipping breakfast some mornings, and still grabbing the same sweet coffee on stressful afternoons. After about eight weeks, her weight had barely changed, but her reflux was worse and she had started avoiding certain foods because her stomach felt irritated. The useful lesson was not that she lacked discipline. It was that the ritual looked productive while the real calorie drivers and tolerance issues stayed untouched.'
            )
        return body.rstrip() + '\n\n' + block

    def _ensure_comparison_table(self, body: str, keyword: str) -> str:
        if '|' in body and re.search(r'^\|.*\|$', body, re.MULTILINE):
            return body
        query_type = self._infer_query_type(keyword)
        heading = '## The Side-by-Side Check Most People Actually Need'
        if query_type == 'comparison':
            table = (
                '| Option | Best For | Main Upside | Main Tradeoff | Where People Misjudge It |\n'
                '| --- | --- | --- | --- | --- |\n'
                '| Option A | Readers who want the stronger headline benefit | Can feel more decisive on paper | May ask more in cost, side effects, or routine friction | They assume the stronger claim automatically means the better fit |\n'
                '| Option B | Readers who value steadier day-to-day fit | Often easier to stay with consistently | May look less exciting at first glance | They dismiss it too fast because it sounds less dramatic |\n'
                '| Doing nothing and waiting | Readers tempted to avoid the decision | No immediate disruption | Usually keeps the same confusion alive | They call it caution when it is really indecision |'
            )
        elif query_type == 'celebrity':
            table = (
                '| What People See Online | What May Actually Be Going On | Why The Gap Matters |\n'
                '| --- | --- | --- |\n'
                '| A dramatic public transformation | Multiple invisible supports, scheduling changes, or medical oversight | The visible result is not a plug-and-play plan |\n'
                '| One habit getting all the credit | A bigger stack of food, sleep, movement, or treatment changes | Readers copy the wrong lever |\n'
                '| Fast before-and-after hype | A timeline that leaves out setbacks or tradeoffs | People underestimate the real cost of copying it |'
            )
        elif query_type == 'symptom':
            table = (
                '| Pattern | What It May Point To | Why It Gets Missed |\n'
                '| --- | --- | --- |\n'
                '| Happens occasionally with no other obvious signs | A mild or temporary trigger | People assume inconsistency means irrelevance |\n'
                '| Shows up with other changes or repeat timing | A pattern worth paying closer attention to | The extra clues seem small until they repeat |\n'
                '| Keeps getting stronger or harder to explain | A more meaningful warning sign | People normalize it for too long |'
            )
        else:
            table = (
                '| Option | Calorie Impact | Fullness Effect | Main Upside | Main Downside |\n'
                '| --- | --- | --- | --- | --- |\n'
                '| Flavored ritual drink tied to the keyword | Usually low on its own | Mild at best | Can replace a higher-calorie habit | Easy to over-credit for results |\n'
                '| Plain water before meals | Zero | Often helpful | Supports hydration and portion control | Less exciting, so consistency can slip |\n'
                '| A more strategic replacement habit | Depends on the choice | Can be stronger when matched to the goal | Closer to the real behavior change that moves results | Takes more effort than a simple wellness ritual |'
            )
        return body.rstrip() + f'\n\n{heading}\n\n{table}'

    def _ensure_action_guide(self, body: str, keyword: str) -> str:
        if re.search(r'\b(step 1|protocol|action plan|what to do instead)\b', body, re.IGNORECASE):
            return body
        phrase = self._heading_subject(keyword)
        query_type = self._infer_query_type(keyword)
        if query_type == 'comparison':
            block = (
                '## What To Do Next Before You Choose\n\n'
                f'If you are stuck on {phrase}, the smartest next move is to make the decision smaller and more concrete.\n\n'
                '1. Decide which tradeoff matters most to you first, such as speed, tolerability, cost, or convenience.\n'
                '2. Rule out the option that clashes hardest with your real schedule or risk tolerance.\n'
                '3. Judge the remaining choice by whether you can realistically stay with it long enough for it to matter.'
            )
        elif query_type == 'symptom':
            block = (
                '## What To Do Next Instead Of Guessing\n\n'
                f'If {phrase} keeps showing up, the right move is not to spiral or ignore it. It is to get clearer on the pattern.\n\n'
                '1. Track when it happens, what else is happening around it, and what makes it better or worse.\n'
                '2. Notice whether the pattern is getting more frequent, more intense, or tied to other symptoms.\n'
                '3. Escalate faster if the pattern is repeating in a way that stops feeling random.'
            )
        elif query_type == 'celebrity':
            block = (
                '## What To Do Instead Of Copying The Headline\n\n'
                f'If {phrase} is making you want to copy a celebrity routine, slow the decision down and bring it back to your own life.\n\n'
                '1. Separate the public transformation from the invisible support system that probably helped create it.\n'
                '2. Identify the one habit in your own routine that is more likely to move results than the headline trick.\n'
                '3. Choose a change you can still do on a boring, stressful weekday, not just when motivation is high.'
            )
        else:
            block = (
                '## What To Do Next If You Want A Real-World Answer\n\n'
                f'If you are trying to decide whether {phrase} is worth continuing, make the next move concrete instead of emotional.\n\n'
                '1. Pick one honest success metric such as appetite control, weekly trend, side-effect burden, or consistency over a full month.\n'
                '2. Write down the tradeoff you are tolerating most, like cost, nausea, food noise, schedule friction, or rebound risk.\n'
                '3. Keep or drop the approach based on whether the real payoff still looks worth that tradeoff once the hype wears off.'
            )
        return body.rstrip() + '\n\n' + block

    def _ensure_faq_block(self, body: str, keyword: str) -> str:
        if re.search(r'^## Frequently Asked Questions\s*$', body, re.MULTILINE):
            return self._ensure_long_faq_answers(body, keyword)
        phrase = self._heading_subject(keyword)
        query_type = self._infer_query_type(keyword)
        if query_type == 'comparison':
            block = (
                '## Frequently Asked Questions\n\n'
                f'### Which matters more with {phrase} speed or fit\n\n'
                'Fit usually matters more than headline speed because the better option is the one a person can stay with long enough for it to matter.\n\n'
                f'### Does {phrase} always have one clear winner\n\n'
                'No. The stronger choice often depends on what downside, cost, or routine burden someone is least willing to tolerate.\n\n'
                f'### Why do people get so confused by {phrase}\n\n'
                'Because the public conversation usually compares the sales pitch first and the tradeoffs second. That is the wrong order.\n\n'
                f'### What is the biggest mistake people make in {phrase}\n\n'
                'They choose based on hype, speed, or fear of missing out instead of choosing around real-world fit.'
            )
        elif query_type == 'symptom':
            block = (
                '## Frequently Asked Questions\n\n'
                f'### When does {phrase} stop being something to brush off\n\n'
                'It stops feeling minor when it becomes more frequent, more intense, or starts arriving with other changes you cannot easily explain.\n\n'
                f'### Why does {phrase} seem random at first\n\n'
                'Because the pattern is often easier to see in hindsight than in the moment, especially when the triggers are subtle.\n\n'
                f'### Should I wait and see if {phrase} goes away on its own\n\n'
                'A brief watch-and-track approach can be reasonable, but repeated patterns deserve more attention than a one-off episode.\n\n'
                f'### What is the biggest mistake people make with {phrase}\n\n'
                'They flatten a repeating clue into a vague annoyance and wait too long to connect it to the bigger pattern.'
            )
        elif query_type == 'celebrity':
            block = (
                '## Frequently Asked Questions\n\n'
                f'### Can I copy {phrase} and expect the same result\n\n'
                'Usually not, because the public-facing routine rarely shows the full set of supports, tradeoffs, or constraints behind the result.\n\n'
                f'### Why do celebrity stories like {phrase} spread so fast\n\n'
                'Because they package a complicated outcome into one clean habit, which is emotionally satisfying even when it is incomplete.\n\n'
                f'### What part of {phrase} do readers over-credit most often\n\n'
                'They usually over-credit the visible ritual and under-credit the invisible structure around it.\n\n'
                f'### What is the safest way to read a story like {phrase}\n\n'
                'Treat it like a reality check, not a plug-and-play blueprint for your own body or schedule.'
            )
        else:
            block = (
                '## Frequently Asked Questions\n\n'
                f'### Does {phrase} actually work well enough to justify the hassle\n\n'
                f'That question usually sounds simple at first, but it only gets useful once you define what counts as work in real life. For some readers, that means visible progress on the scale. For others, it means better appetite control, steadier energy, less food noise, or fewer rebound patterns after the first few exciting weeks. The bigger issue is whether {phrase} still feels worth the tradeoffs once routine friction shows up. Cost, side effects, schedule burden, and the emotional wear of sticking with something often matter more than the initial promise. A lot of people say something works when they really mean it sounded promising for a short window. A better standard is whether the result still looks meaningful after the novelty fades and real-life inconsistency enters the picture.\n\n'
                f'### How long does it usually take to know if {phrase} is really helping\n\n'
                f'Most people need longer than they expect, because the first stretch can be noisy. Early motivation, water-weight shifts, temporary appetite suppression, or a burst of tighter habits can all make an approach look stronger than it really is. That is why a quick emotional verdict is usually misleading. The better question is whether {phrase} is still producing a result you can recognize after the first wave of excitement, inconvenience, or discomfort. In practical terms, you want enough time to notice consistency, tolerability, and whether the payoff is still visible once normal life interrupts the routine. If the approach only feels effective when everything is going perfectly, that is already part of the answer. Durable help usually looks steadier, less theatrical, and easier to repeat under ordinary conditions.\n\n'
                f'### Who is most likely to feel disappointed by {phrase}\n\n'
                f'The people most likely to feel let down are usually the ones expecting a clean, dramatic result without much friction attached to it. That often includes readers who came in through hype, before-and-after marketing, or a simplified social version of {phrase} that leaves out the daily tradeoffs. Disappointment also shows up when someone expects one lever to carry the whole outcome while other drivers stay untouched, like eating patterns, routine instability, poor sleep, emotional stress, or unrealistic timelines. In a lot of cases, the issue is not that the approach does nothing. It is that the reader expected it to do more than it realistically could on its own. The more a person needs a shortcut story to be true, the more likely they are to feel frustrated when reality turns out slower, messier, or more conditional.\n\n'
                f'### What is the biggest mistake people make with {phrase}\n\n'
                f'The biggest mistake is treating {phrase} like the whole strategy instead of one variable inside a much larger pattern. People often pour their attention into the visible lever because it feels easier to track, talk about, and believe in. But that can hide the more important question of what is actually driving the outcome day to day. Sometimes the real issue is that the approach never fit the person\'s schedule, tolerance, or budget well enough to last. Other times it is that the surrounding habits never changed, so the headline tool got credit for more than it deserved. A smarter read is to keep asking what is changing underneath the surface: appetite, consistency, rebound behavior, food choices, energy, or side-effect burden. That is usually where the honest verdict starts.'
            )
        return self._ensure_long_faq_answers(body.rstrip() + '\n\n' + block, keyword)

    def _ensure_long_faq_answers(self, body: str, keyword: str) -> str:
        query_type = self._infer_query_type(keyword)

        def expand_answer(question: str, answer: str) -> str:
            word_count = len(re.findall(r'\b\w+\b', answer))
            if word_count >= 100:
                return answer.strip()
            phrase = self._heading_subject(keyword)
            question_lower = question.lower()
            if query_type == 'comparison':
                if 'winner' in question_lower or 'which' in question_lower:
                    return (
                        f'There usually is not one universal winner with {phrase}, even when the marketing makes it sound that way. '
                        'What changes the answer is which tradeoff matters most in ordinary life: speed, tolerability, cost, schedule fit, side effects, or how much friction a person can realistically absorb before the plan starts falling apart. '
                        'A lot of readers compare the headline promise first and the day-to-day burden second, which is backwards. '
                        'The better option is often the one that looks slightly less exciting on paper but is easier to stay with long enough to matter. '
                        'That is why a good comparison should not end at which option sounds stronger. It should end at which choice still feels workable once motivation dips, time gets tight, or the downside becomes harder to ignore.'
                    )
                return (
                    f'The confusing part about {phrase} is that two options can sound similar while asking very different things from the person choosing between them. '
                    'One might offer a stronger promise but come with more burden, while the other may look steadier and easier to sustain over time. '
                    'People get stuck when they treat the decision like a branding contest instead of a fit question. '
                    'The smarter read is to compare routine burden, downside tolerance, and how long someone can realistically stay consistent. '
                    'That frame usually produces a more honest answer than just asking which option seems more powerful in the abstract.'
                )
            if query_type == 'symptom':
                return (
                    f'The useful way to think about {phrase} is not as one isolated moment but as a pattern that may or may not be repeating for a reason. '
                    'A symptom-like query becomes more meaningful when timing, frequency, intensity, or companion clues start lining up in a way that stops feeling random. '
                    'That does not mean every episode points to something severe, but it does mean the pattern deserves more respect than a one-line internet answer can give it. '
                    'What helps most is tracking when it happens, what changes around it, and whether it is becoming easier to predict. '
                    'The more consistent that pattern becomes, the less useful it is to keep dismissing it as a harmless quirk.'
                )
            if query_type == 'celebrity':
                return (
                    f'A celebrity-style question about {phrase} usually spreads because the public version feels neat, emotional, and easy to copy. '
                    'The problem is that the visible routine is often the least useful part of the story. '
                    'What readers do not see is the invisible structure behind the result: schedule control, money, support, treatment access, editing, or a timeline that gets compressed into one dramatic headline. '
                    'That is why copying the obvious habit rarely reproduces the outcome. '
                    'A safer way to read this kind of story is to separate what is confirmed, what is guessed, and what people are projecting onto the transformation because they want one simple explanation to be true.'
                )
            return (
                f'The honest answer on {phrase} is usually more conditional than the question makes it sound. '
                'Readers often want a yes-or-no verdict, but what actually matters is whether the result is strong enough, durable enough, and tolerable enough to stay meaningful once real life enters the picture. '
                'That means looking past the first burst of optimism and asking what happens when cost, routine burden, side effects, inconsistency, or emotional fatigue start showing up. '
                'An approach can sound promising without delivering enough real-world payoff to justify the hassle. '
                'The more practical question is not whether something can help in theory, but whether it holds up well enough under normal conditions to feel worth continuing.'
            )

        pattern = re.compile(r'(^###\s+(.+?)\n\n)(.*?)(?=\n###\s+|\n##\s+|\Z)', re.MULTILINE | re.DOTALL)

        def repl(match: re.Match[str]) -> str:
            prefix = match.group(1)
            question = match.group(2).strip()
            answer = match.group(3).strip()
            return f'{prefix}{expand_answer(question, answer)}\n\n'

        return pattern.sub(repl, body).strip()

    def _extract_body_preamble(self, body: str) -> str:
        first_heading = self._find_first_body_heading(body)
        if not first_heading:
            return body.strip()
        preamble = body[:first_heading.start()].strip()
        preamble = re.sub(r'## Table of Contents\n(?:- .*\n?)+', '', preamble, count=1).strip()
        return preamble

    def _extract_body_tail(self, body: str) -> str:
        match = re.search(r'^## AI Disclosure\s*$', body, re.MULTILINE)
        if match:
            return body[match.start():].strip()
        return ''

    def _enforce_single_image_placeholder(self, body: str, keyword: str) -> str:
        body = re.sub(r'^\[IMAGE:[^\n]+\]\s*$', '', body, flags=re.MULTILINE)
        body = re.sub(r'^<!--\s*IMAGE:.*?-->\s*$', '', body, flags=re.MULTILINE)
        first_heading = self._find_first_body_heading(body)
        image_block = f'[IMAGE: {self._slugify(keyword)} weight loss results]'
        if first_heading:
            insert_at = body.find('\n', first_heading.start())
            if insert_at != -1:
                body = body[:insert_at + 1] + '\n' + image_block + '\n\n' + body[insert_at + 1:]
        return body.strip()

    def _enforce_single_video_block(self, body: str, keyword: str) -> str:
        body = re.sub(r'^<iframe[^\n]*youtube\.com/embed[^\n]*>\s*</iframe>\s*$', '', body, flags=re.MULTILINE)
        body = re.sub(r'^> \*\*Editor[’\']s note:\*\*.*$', '', body, flags=re.MULTILINE)
        body = re.sub(r'^\[YOUTUBE_VIDEO:[^\n]+\]\s*$', '', body, flags=re.MULTILINE)
        sections = self._split_body_sections(body)
        video_block = f'[YOUTUBE_VIDEO: {self._slugify(keyword)} review results side effects]'
        if len(sections) >= 3:
            target_heading = sections[2][0]
            body = re.sub(
                rf'(^##\s+{re.escape(target_heading)}\s*$)',
                rf'\1\n\n{video_block}',
                body,
                count=1,
                flags=re.MULTILINE,
            )
        return re.sub(r'\n{3,}', '\n\n', body).strip()

    def _normalize_table_of_contents(self, body: str) -> str:
        headings = [heading for heading, _ in self._split_body_sections(body)[:5]]
        toc_lines = ['## Table of Contents'] + [f'- [{heading}](#{self._slugify(heading)})' for heading in headings]
        toc_block = '\n'.join(toc_lines)
        if re.search(r'^## Table of Contents\s*$', body, re.MULTILINE):
            return re.sub(r'## Table of Contents\n(?:- .*\n?)+', toc_block, body, count=1)
        return toc_block + '\n\n' + body

    def _rewrite_references(self, body: str, title: str, keyword: str, category_id: int) -> str:
        references = self._select_references(title, keyword, category_id)
        reference_lines = ['## References'] + [f'- [{label}]({url})' for label, url in references]
        reference_block = '\n'.join(reference_lines)
        if re.search(r'^## References\s*$', body, re.MULTILINE):
            return re.sub(r'## References\n(?:- .*\n?)+', reference_block, body, count=1)
        return body.rstrip() + '\n\n' + reference_block + '\n'

    def _select_references(self, title: str, keyword: str, category_id: int) -> list[tuple[str, str]]:
        lowered = f'{title} {keyword}'.lower()
        if category_id == 9:
            references = [
                ('Centers for Disease Control and Prevention - About Diabetes', 'https://www.cdc.gov/diabetes/about/index.html'),
                ('National Heart, Lung, and Blood Institute - High Blood Pressure', 'https://www.nhlbi.nih.gov/health/high-blood-pressure'),
                ('MedlinePlus - Blood Glucose', 'https://medlineplus.gov/bloodglucose.html'),
            ]
            if any(token in lowered for token in ('cholesterol', 'triglyceride', 'lipid')):
                references[1] = ('MedlinePlus - Cholesterol', 'https://medlineplus.gov/cholesterol.html')
            return references
        if category_id == 5:
            references = [
                ('U.S. Food and Drug Administration - Cannabis and Cannabis-Derived Products', 'https://www.fda.gov/consumers/consumer-updates/what-know-and-what-were-working-find-out-about-products-containing-cannabis-or-cannabis-derived'),
                ('National Center for Complementary and Integrative Health - Cannabis and Cannabinoids', 'https://www.nccih.nih.gov/health/cannabis-cannabinoids-and-cannabis-based-products-what-you-need-to-know'),
                ('MedlinePlus - Marijuana and Cannabinoids', 'https://medlineplus.gov/marijuana.html'),
            ]
            return references
        references = [
            ('National Institute of Diabetes and Digestive and Kidney Diseases - Health Risks of Overweight and Obesity', 'https://www.niddk.nih.gov/health-information/weight-management/adult-overweight-obesity/health-risks'),
            ('Centers for Disease Control and Prevention - Healthy Weight', 'https://www.cdc.gov/healthy-weight-growth/healthy-weight/index.html'),
            ('MedlinePlus - Weight Control', 'https://medlineplus.gov/weightcontrol.html'),
        ]
        if any(token in lowered for token in ('glp-1', 'semaglutide', 'tirzepatide')):
            references[0] = ('National Institute of Diabetes and Digestive and Kidney Diseases - Prescription Medications to Treat Overweight and Obesity', 'https://www.niddk.nih.gov/health-information/weight-management/prescription-medications-treat-overweight-obesity')
        return references

    def _normalize_category_id(self, category_id: int | None) -> int:
        if category_id in {1, 5, 9}:
            return int(category_id)
        return 1

    def _normalize_final_title(self, title: str, keyword: str) -> str:
        cleaned = re.sub(r'\s+', ' ', str(title)).strip()
        if ':' in cleaned:
            left, right = [part.strip(' -') for part in cleaned.split(':', 1)]
            if left and right:
                cleaned = f'{left} {right}'
        replacements = {
            r'\bWhat the Clinical Evidence Shows\b': 'What Actually Happens',
            r'\bWhat the Science Shows\b': 'What Actually Happens',
            r'\bWhat Does the Science Say\b': 'What You Should Know',
            r'\bClinical Effectiveness\b': 'Real Results',
            r'\bClinical Evidence\b': 'What Real Buyers Should Know',
            r'\bEvidence-Based\b': 'Straight Talk on',
            r'\bReviews?, Cost, and Common Side Effects\b': 'Reviews Costs and Side Effects',
            r'\bWhat to Expect\b': 'What Real Users Notice',
        }
        for pattern, replacement in replacements.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(effectiveness|efficacy|clinical|study-backed|scientific)\b', '', cleaned, flags=re.IGNORECASE)
        keyword_lower = keyword.lower()
        drift_tokens = ('belly fat', 'morning or later in the day', 'sweet drinks', 'celebrity routine', 'copy a celebrity')
        if any(token in cleaned.lower() for token in drift_tokens) and not any(token in keyword_lower for token in drift_tokens):
            cleaned = ''
        cleaned = re.sub(r'\bwhat the what\b', 'what', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bwhat what\b', 'what', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip(' -')
        return cleaned or self._fallback_title_from_keyword(keyword)

    def _fallback_title_from_keyword(self, keyword: str) -> str:
        cleaned = re.sub(r'\s+', ' ', keyword).strip(' -_')
        if not cleaned:
            return 'Before You Copy This Trend Read This Part First'
        query_type = self._infer_query_type(cleaned)
        subject = self._heading_subject(cleaned)
        return self._pick_title_variant(cleaned, query_type, subject).replace("Here's", 'Here Is')

    @staticmethod
    def _slugify(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-") or "article"
