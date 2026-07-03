#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Locked viral article controller for local AnQiCMS generation.

Final articles are generated with a deterministic PAS-style decision-copy
writer. This avoids Gemini drift, report voice, front-loaded summary answers,
wrong modality examples, long mobile paragraphs, and academic pain-point wording.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re

from pipeline_controller import PipelineController, PipelineResult, ProgressCallback
from preview_renderer import render_preview_html
from publish_articles import load_article


class EditorialPipelineController(PipelineController):
    """PipelineController variant with locked high-conversion article structure."""

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
    CBD_TOKENS = ("cbd", "cannabidiol", "hemp", "gummies", "gummy", "tincture")
    BLOOD_TOKENS = (
        "blood",
        "glucose",
        "a1c",
        "cholesterol",
        "triglycerides",
        "insulin",
        "blood pressure",
        "blood sugar",
        "bp",
    )

    FORBIDDEN_OPENING_PATTERNS = (
        r"\bthe short answer is\b",
        r"\bthe direct verdict is\b",
        r"\bsearching\s+.+?usually means\b",
        r"\bhere is the short version\b",
        r"\bin conclusion\b",
        r"\bfurthermore\b",
        r"\bit is important to note\b",
    )

    def run_stage1_1(self, keyword: str, progress: ProgressCallback | None = None) -> tuple[dict, Path]:
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
        try:
            return super().run_stage1_2(keyword, stage1_1, category_id, keyword_id, progress)
        except RuntimeError as error:
            if "Stage 1-2" not in str(error):
                raise
            if progress:
                progress("Drafting", 30, "Stage 1-2 Gemini failed; using local fallback outline")
            slug = self._slugify(keyword)
            payload = self._build_stage1_2_fallback(keyword, category_id, keyword_id)
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
        if progress:
            progress("Fact_Checking", 45, "Rendering PAS locked viral article")
        slug = self._slugify(keyword)
        markdown_path = self.output_root / f"ui_{slug}.md"
        draft_markdown_path = self.output_root / f"ui_{slug}.draft.md"
        category_value = self._normalize_category_id(category_id)
        title = self._viral_title(keyword)
        description = self._truncate_description(self._viral_description(keyword))
        body = self._build_locked_viral_body(keyword)

        draft_content = self._compose_markdown_document(keyword, title, description, category_value, keyword_id, body)
        draft_markdown_path.write_text(draft_content, encoding="utf-8")
        if progress:
            progress("Fact_Checking", 60, f"Saved PAS locked draft markdown: {draft_markdown_path.name}")

        final_content = self._compose_markdown_document(keyword, title, description, category_value, keyword_id, body)
        markdown_path.write_text(final_content, encoding="utf-8")
        load_article(markdown_path)
        if progress:
            progress("SEO_Optimizing", 70, f"Rendered final markdown: {markdown_path.name}")
        return markdown_path

    def _build_stage1_1_fallback(self, keyword: str) -> dict:
        lane = self._lane(keyword)
        return {
            "sq": keyword,
            "language": "English",
            "tm": "false",
            "ymyl_level": True,
            "lane": lane,
            "qs": [{"q": keyword, "i": self._intent_line(keyword), "tm": "false", "ymyl_level": True}],
            "fallback": True,
        }

    def _build_stage1_2_fallback(self, keyword: str, category_id: int | None, keyword_id: int | None) -> dict:
        node = {
            "t": self._viral_title(keyword),
            "mty": "Semantic",
            "cs": {"ty": "Editorial Desk", "ac": "US", "ar": "", "al": ""},
            "category_id": self._normalize_category_id(category_id),
            "cr": {
                "tl": "PAS hook, mobile copy, pain-first decision article.",
                "s": self._viral_description(keyword),
                "wc": 2200,
                "st": self._viral_headings(keyword),
                "kp": self._viral_key_points(keyword),
                "af": "Start with story pain. Do not reveal the full verdict in the intro.",
                "gfm": {"lsr": True},
                "author_bio": self._author_bio(keyword),
                "personal_story": self._opening_story(keyword),
            },
        }
        if keyword_id is not None:
            node["keyword_id"] = keyword_id
        return {"dsq": [{"q": keyword, "i": self._intent_line(keyword), "mt": [node]}], "fallback": True}

    def _lane(self, keyword: str) -> str:
        lowered = keyword.lower()
        if any(token in lowered for token in self.MEDICATION_TOKENS):
            return "medication"
        if any(token in lowered for token in self.CBD_TOKENS):
            return "cbd"
        if any(token in lowered for token in self.BLOOD_TOKENS):
            return "blood"
        return "weight_loss"

    def _subject(self, keyword: str) -> str:
        subject = self._heading_subject(keyword)
        return re.sub(r"\s+", " ", subject).strip(" -?") or keyword.strip()

    def _title_subject(self, keyword: str) -> str:
        subject = self._subject(keyword)
        minor = {"a", "an", "and", "as", "at", "by", "for", "in", "is", "of", "on", "or", "the", "to", "vs", "with"}
        words: list[str] = []
        for index, word in enumerate(subject.lower().split()):
            if index > 0 and word in minor:
                words.append(word)
            else:
                words.append(word[:1].upper() + word[1:])
        return " ".join(words)

    def _viral_title(self, keyword: str) -> str:
        lane = self._lane(keyword)
        subject = self._title_subject(keyword)
        lowered = keyword.lower()
        if lane == "medication":
            if "metformin" in lowered:
                return "Metformin For Weight Loss Sounds Simple Until The Second Month Gets Messy"
            if "mounjaro" in lowered or "tirzepatide" in lowered:
                return "Mounjaro Weight Loss Looks Powerful Until The Real-Life Friction Shows Up"
            if "ozempic" in lowered or "semaglutide" in lowered:
                return f"{subject} Looks Promising Until The Maintenance Question Shows Up"
            return f"{subject} Sounds Promising Until The Real-Life Tradeoff Shows Up"
        if lane == "cbd":
            if "sleep" in lowered:
                return f"{subject} Sounds Easy Until The Morning After Tells The Truth"
            return f"{subject} Sounds Helpful Until You Track The Tradeoff Closely"
        if lane == "blood":
            if "after eating" in lowered or "blood sugar" in lowered:
                return f"{subject} Looks Random Until You Track This Pattern"
            if "cholesterol" in lowered:
                return f"{subject} Is Easy To Ignore Until The Pattern Gets Serious"
            return f"{subject} Looks Small Until The Pattern Starts Repeating"
        return f"{subject} Sounds Easy Until Real Life Starts Testing It"

    def _viral_description(self, keyword: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        if lane == "medication":
            return f"A PAS-style decision guide to {subject}, including the painful second-month friction, side effects, access, cost, and what to ask before choosing it."
        if lane == "cbd":
            return f"A practical look at {subject}, including expectations, next-day effects, safety questions, product quality, and when to be cautious."
        if lane == "blood":
            return f"A practical guide to {subject}, including patterns to track, what gets missed, and when to discuss the result with a qualified professional."
        return f"A real-world look at {subject}, including what works, what disappoints people, and what to check before committing."

    def _intent_line(self, keyword: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        if lane == "medication":
            return f"The searcher wants to know whether {subject} is worth considering after real-life side effects, access, cost, and maintenance friction are included."
        if lane == "cbd":
            return f"The searcher wants to know whether {subject} is actually useful, safe, and worth the tradeoff."
        if lane == "blood":
            return f"The searcher wants to understand what {subject} may mean and what pattern deserves attention."
        return f"The searcher wants a practical answer about {subject}, not a generic explainer."

    def _viral_key_points(self, keyword: str) -> list[str]:
        lane = self._lane(keyword)
        if lane == "medication":
            return [
                "Open with pain, not verdict.",
                "The first screen should create curiosity and emotional identification.",
                "Medical details must be translated into felt user pain.",
            ]
        if lane == "cbd":
            return ["Track the next morning, not just the night.", "Product quality changes the result.", "Safety context matters."]
        if lane == "blood":
            return ["Pattern matters more than one moment.", "Context changes the meaning.", "Repeat or worsening signs deserve professional input."]
        return ["Promise must be tested against real-life friction.", "Early progress is not the real test.", "Decision checklist beats motivation."]

    def _viral_headings(self, keyword: str) -> list[str]:
        lane = self._lane(keyword)
        subject = self._title_subject(keyword)
        if lane == "medication":
            return [
                "The Moment The Plan Stops Feeling Simple",
                f"What {subject} Can And Cannot Do For The Right Person",
                "The Side Effects People Understand Too Late",
                "The Access And Cost Problem That Can Break Momentum",
                f"{subject} Compared With The Choice People Usually Have In Mind",
                "What To Do Before You Choose This Path",
            ]
        if lane == "cbd":
            return [
                "The Morning After Is Where The Promise Gets Tested",
                f"What {subject} May Help And Where The Hype Runs Ahead",
                "The Product Quality Problem Most Buyers Miss",
                "The Tradeoff That Makes The Routine Hard To Judge",
                f"{subject} Compared With The Other Options People Usually Try",
                "What To Do Before You Make It A Routine",
            ]
        if lane == "blood":
            return [
                "The Pattern Matters More Than The Panic",
                "The Clues That Matter More Than The Number Alone",
                "Where People Misread The Signal First",
                "A Tracking Scenario That Changes The Conversation",
                f"{subject} Compared With The Checks People Usually Skip",
                "What To Do Before You Guess At The Cause",
            ]
        return [
            "The Moment The Promise Meets Real Life",
            f"What {subject} Can And Cannot Do",
            "The Friction Most People Notice Too Late",
            "A Composite Scenario That Shows The Turning Point",
            f"{subject} Compared With The Easier Looking Alternative",
            "What To Do Before You Commit",
        ]

    def _opening_story(self, keyword: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        if lane == "medication":
            if "metformin" in keyword.lower():
                return (
                    "Marcus thought the hard part was getting the prescription."
                    "\n\nBy week eight, the problem was not motivation anymore. It was the stomach drop before meetings, the afternoon crash that coffee could not touch, and the quiet fear that skipping one dose would turn into quitting completely."
                    "\n\nThat is the part of metformin weight loss most pages rush past. The decision does not get real when the pill is prescribed. It gets real when your body, schedule, bathroom access, refills, and patience all start negotiating at the same time."
                )
            if "mounjaro" in keyword.lower() or "tirzepatide" in keyword.lower():
                return (
                    "Marcus thought the injection would be the hard part."
                    "\n\nBy the second refill, the needle was not what worried him. It was the nausea before dinner, the pharmacy delay, the insurance message he did not understand, and the question he kept avoiding: what happens if this routine breaks?"
                    "\n\nThat is where the Mounjaro weight loss decision gets serious. Not in the success story, but in the ordinary week when side effects, access, cost, and maintenance all show up together."
                )
            return (
                f"Marcus thought {subject} would finally make the decision simple."
                "\n\nThen the routine started asking for more than he expected: side-effect planning, refills, cost checks, follow-up, and the discipline to build habits around the medication instead of treating it like the whole strategy."
                "\n\nThat is where this choice stops being a headline and becomes a real-life tradeoff."
            )
        if lane == "cbd":
            return (
                f"She bought {subject} because the reviews sounded calm."
                "\n\nThe first night felt promising. The next morning felt heavy. By the fourth night, she was not asking whether CBD worked anymore. She was asking whether the tradeoff was worth repeating."
            )
        if lane == "blood":
            return (
                f"The first time he noticed {subject}, he searched before he even wrote down what happened."
                "\n\nThat was the problem. Without timing, meals, sleep, stress, and repeat patterns, the search result had almost nothing to work with."
            )
        return (
            f"The promise behind {subject} usually looks clean from a distance."
            "\n\nThen normal life shows up. That is when the real answer begins."
        )

    def _author_bio(self, keyword: str) -> str:
        lane = self._lane(keyword)
        if lane == "blood":
            return "Evidence-Aware Health Editor"
        return "Evidence-Aware Wellness Editor"

    def _build_locked_viral_body(self, keyword: str) -> str:
        lane = self._lane(keyword)
        sections = self._viral_headings(keyword)
        toc = ["## Table of Contents"] + [f"- [{heading}](#{self._slugify(heading)})" for heading in sections]
        toc += ["- [Frequently Asked Questions](#frequently-asked-questions)", "- [The Next Step Without Guesswork](#the-next-step-without-guesswork)"]
        parts = [
            "> **Disclaimer:** This content is for general educational purposes only and does not replace individualized professional advice.",
            f"Last updated: {datetime.now().strftime('%A, %B %d, %Y')}",
            "\n".join(toc),
            self._direct_opening(keyword),
            self._section_one(keyword, sections[0]),
            self._section_two(keyword, sections[1]),
            self._section_three(keyword, sections[2]),
            self._case_section(keyword, sections[3]),
            self._comparison_section(keyword, sections[4]),
            self._action_guide(keyword, sections[5]),
            self._faq(keyword),
            self._closing(keyword),
            self._tail(keyword),
        ]
        body = "\n\n".join(part.strip() for part in parts if part and part.strip())
        return self._final_cleanup(body, lane)

    def _direct_opening(self, keyword: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        story = self._opening_story(keyword)
        if lane == "medication":
            bridge = (
                "Keep reading and the decision becomes less obvious in the right way."
                "\n\nThe useful question is not whether the medication has a place. It is whether the cost, side effects, access path, medical fit, and maintenance plan survive the messy part after the first wave of hope."
            )
        elif lane == "cbd":
            bridge = (
                "That is why the best test is not the calmest review or the first night."
                "\n\nThe useful question is whether the effect repeats, whether the product is clean enough to trust, and whether the next-day tradeoff still feels acceptable."
            )
        elif lane == "blood":
            bridge = (
                "That is why the first move is not panic and not dismissal."
                "\n\nThe useful move is to turn the moment into a pattern that a qualified professional can actually interpret if it repeats."
            )
        else:
            bridge = (
                "That is why the first result is not the whole story."
                "\n\nThe useful question is whether the promise survives the ordinary friction most people ignore at the beginning."
            )
        return f"{story}\n\n{bridge}"

    def _section_one(self, keyword: str, heading: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        if lane == "medication":
            body = (
                f"{subject} can help the right person, but it is not the whole strategy. That distinction matters because medication content often sells the cleanest part of the story and hides the lived part.\n\n"
                "The lived part is the stomach sensitivity, the refill timing, the follow-up, the cost, and the awkward realization that a pill or injection cannot build the maintenance plan for you.\n\n"
                "That does not make the option useless. It means the choice has to be judged like a real routine, not a dramatic before-and-after promise.\n\n"
                f"[IMAGE: {keyword} real decision]"
            )
        elif lane == "cbd":
            body = (
                f"{subject} can feel appealing because the promise is small and easy. Take it, feel calmer, sleep better, or take the edge off.\n\n"
                "The problem is that the real experience is usually more conditional. Product quality, timing, dose clarity, other ingredients, and medication interactions can change the result fast.\n\n"
                f"[IMAGE: {keyword} real decision]"
            )
        elif lane == "blood":
            body = (
                f"{subject} can feel alarming because blood-related words sound serious. But one reading or one vague symptom rarely tells the full story.\n\n"
                "The useful move is pattern recognition. Timing, meals, sleep, stress, medication changes, and repeat signs often matter more than the isolated moment.\n\n"
                f"[IMAGE: {keyword} tracking pattern]"
            )
        else:
            body = (
                f"{subject} can work in one situation and fail in another. That is why the promise needs to be tested against real life.\n\n"
                "The first signal is easy to overread. What matters more is whether the plan survives cost, stress, boredom, schedule changes, and ordinary inconsistency.\n\n"
                f"[IMAGE: {keyword} real process]"
            )
        return f"## {heading}\n\n{body}"

    def _section_two(self, keyword: str, heading: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        if lane == "medication":
            body = (
                "The first few weeks can trick people because hope is doing part of the work. You pay closer attention, tolerate discomfort more easily, and read every small change as proof that the plan is working.\n\n"
                f"Then {subject} has to live inside a normal week. That means meetings, meals, travel, refill timing, bathroom anxiety, fatigue, and the pressure to keep going even when the scale stops giving quick reassurance.\n\n"
                "That second phase is where the copy on most pages gets too clean. It talks about results, but the reader is living with friction."
            )
        elif lane == "cbd":
            body = (
                "The first night can trick people because expectation changes behavior. You go to bed earlier, watch yourself more closely, and credit the product for the whole setup.\n\n"
                f"The better test for {subject} is several ordinary nights. Track whether the result repeats, whether the morning feels clear, and whether the same product behaves consistently."
            )
        elif lane == "blood":
            body = (
                "The clues that matter most are usually the ones people forget to write down. Timing matters. Meals matter. Stress, sleep, illness, exercise, and medications matter.\n\n"
                f"For {subject}, the goal is not to diagnose yourself. The goal is to turn a vague worry into a cleaner record."
            )
        else:
            body = (
                "The first result is not the real test because motivation is loud at the beginning. Most people can follow a clean plan while it still feels new.\n\n"
                f"With {subject}, the harder question is what happens when the plan becomes boring, inconvenient, expensive, or slower than expected."
            )
        return f"## {heading}\n\n{body}"

    def _section_three(self, keyword: str, heading: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        if lane == "medication":
            if "metformin" in keyword.lower():
                pain = (
                    "The side effects are not just a line on a drug information sheet. They can feel like planning your morning around the nearest bathroom, avoiding breakfast because your stomach feels unpredictable, or getting hit by a 3 p.m. fatigue wave that three coffees still cannot flatten.\n\n"
                    "That last part is where medical language gets too cold. A phrase like B12 monitoring does not feel urgent until it becomes the strange tiredness that makes your normal afternoon feel twice as heavy."
                )
            elif "mounjaro" in keyword.lower() or "tirzepatide" in keyword.lower():
                pain = (
                    "The side effects are not just nausea on a checklist. They can feel like staring at dinner and knowing you should eat, but your stomach has already voted no.\n\n"
                    "The access problem is not just insurance friction. It is the pharmacy delay that makes you wonder whether your routine is about to snap right when it finally started working."
                )
            else:
                pain = (
                    "The side effects are not abstract. They show up as meal anxiety, schedule changes, awkward workdays, and the quiet worry that the plan may be harder to live with than it sounded.\n\n"
                    "The access problem is not abstract either. It is the refill, the coverage check, the cost, and the backup plan if the routine gets interrupted."
                )
            body = (
                f"{pain}\n\n"
                "This is why the decision belongs in a clinician conversation. Not because the reader is helpless, but because the real question involves medical history, other prescriptions, warning signs, follow-up, and what to do when the plan feels rough.\n\n"
                f"[YOUTUBE_VIDEO: {keyword} real-world decision side effects cost]"
            )
        elif lane == "cbd":
            body = (
                f"The friction people underestimate with {subject} is product quality. Two bottles can look similar and feel completely different because the label, testing, added ingredients, and cannabinoid profile are not the same.\n\n"
                "The second friction is the next morning. A product that feels calming at night can still feel like a bad trade if you wake up foggy.\n\n"
                f"[YOUTUBE_VIDEO: {keyword} safety effects product quality]"
            )
        elif lane == "blood":
            body = (
                f"The first place people misread {subject} is treating it as either nothing or an emergency without enough context. The better middle path is repetition and clustering.\n\n"
                "Does it happen after similar meals? At the same time of day? With fatigue, thirst, dizziness, chest discomfort, headache, numbness, or sudden changes? Those details can change the urgency.\n\n"
                f"[YOUTUBE_VIDEO: {keyword} symptoms tracking pattern]"
            )
        else:
            body = (
                f"The friction people notice too late with {subject} is usually not the obvious part. It is the routine pressure: cost, prep time, social inconvenience, symptoms, boredom, or the emotional weight of needing the plan to work.\n\n"
                "When friction stays invisible, people blame themselves. When they name it early, they can decide whether the plan is actually realistic.\n\n"
                f"[YOUTUBE_VIDEO: {keyword} real results tradeoffs]"
            )
        return f"## {heading}\n\n{body}"

    def _case_section(self, keyword: str, heading: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        if lane == "medication":
            body = (
                f"The Marcus story is not here as a fake patient file. It is a composite pattern that shows why {subject} cannot be judged by the first optimistic week.\n\n"
                "At the beginning, the plan feels clean because there is finally a concrete next step. Then the routine starts asking for more: timing meals, watching symptoms, chasing refills, checking coverage, and deciding whether the discomfort is temporary or a sign to call the clinician.\n\n"
                "That is the emotional hinge of the article. The question stops being `will this work?` and becomes `can I live with the full cost of making it work?`"
            )
        elif lane == "cbd":
            body = (
                f"A realistic composite scenario looks like this. Someone buys {subject} because the reviews sound calm. The first night feels better, but the next morning feels heavy.\n\n"
                "By the fourth night, the question changes. It is no longer whether CBD can feel relaxing. It is whether this product, at this timing, creates a tradeoff worth repeating."
            )
        elif lane == "blood":
            body = (
                f"A realistic composite scenario looks like this. Someone notices {subject} and searches immediately because the phrase sounds serious. At first, they only remember the scary moment.\n\n"
                "After tracking for two weeks, the pattern becomes clearer. It appears after similar meals, on short-sleep days, or alongside another symptom they had not connected before."
            )
        else:
            body = (
                f"A realistic composite scenario looks like this. Someone starts {subject} with high motivation and sees an early signal that feels encouraging.\n\n"
                "Then ordinary life returns. Work gets busy, meals become less predictable, and the plan starts requiring more attention than expected."
            )
        return f"## {heading}\n\n{body}"

    def _comparison_section(self, keyword: str, heading: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        intro = f"A useful comparison for {subject} should be written in reader language, not report language. The goal is not to crown a universal winner. It is to show which tradeoff becomes hardest to live with."
        if lane == "medication":
            table = """| What You Feel In Real Life | This Option | The Alternative People Usually Compare It With |
|---|---|---|
| How fast hope shows up | May feel gradual or conditional | May feel stronger early but can bring bigger access or cost friction |
| Daily burden | Symptoms, refills, follow-up, and routine pressure | Different burden such as injections, coverage rules, or stronger appetite changes |
| Biggest disappointment | Expecting the medication to carry the whole strategy | Expecting the more powerful option to be easier to live with |
| Pain point to watch | Bathroom anxiety, fatigue, nausea, constipation, cost, or refill stress | Coverage blocks, side effects, access gaps, and maintenance anxiety |
| Question to ask | What would make this hard to continue? | What happens if cost, side effects, or access interrupt the plan? |"""
        elif lane == "cbd":
            table = """| What You Feel In Real Life | CBD Option | Non-CBD Habit Or Product |
|---|---|---|
| Night-one effect | Can feel subtle or inconsistent | May be more predictable if the issue is routine-based |
| Morning-after test | Possible grogginess or unclear carryover | Usually easier to isolate and adjust |
| Product confidence | Depends on testing, label clarity, and ingredients | Depends on habit consistency or product type |
| Safety context | Interaction and quality questions matter | Different risks depending on the alternative |
| Biggest mistake | Judging by one calm night | Ignoring the root sleep, stress, or pain pattern |"""
        elif lane == "blood":
            table = """| What You Track | Why It Matters | What To Bring Up If It Repeats |
|---|---|---|
| Timing | Patterns after meals, sleep loss, stress, or exercise are useful | When it happens and how often |
| Other symptoms | Clusters can change the level of concern | Fatigue, thirst, dizziness, pain, numbness, headache, or unusual changes |
| Repeat readings | One number can mislead | Whether the pattern is stable, rising, falling, or unpredictable |
| Recent changes | Food, supplements, illness, or prescriptions can matter | What changed before the pattern appeared |
| Urgency signs | Some symptoms should not wait | Severe, sudden, or worsening symptoms |"""
        else:
            table = """| What You Feel In Real Life | The Promising Version | The Real-Life Test |
|---|---|---|
| Early result | Feels motivating | Can fade when novelty wears off |
| Effort | Looks simple from the outside | Requires consistency under stress |
| Cost | Easy to ignore at first | Matters when the plan becomes routine |
| Fit | Sounds good generally | Has to match your actual life |
| Maintenance | Rarely discussed in the headline | Decides whether the result survives |"""
        return f"## {heading}\n\n{intro}\n\n{table}"

    def _action_guide(self, keyword: str, heading: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        if lane == "medication":
            steps = (
                f"A useful next step for {subject} is not to chase the strongest claim. It is to turn the decision into questions you can take to a qualified clinician.\n\n"
                "1. **Check personal fit first.** Write down your medical history, current medications, previous side effects, and the reason you are considering this option.\n"
                "2. **Check the access path.** Confirm prescription requirements, follow-up schedule, refill reliability, insurance coverage, prior authorization, and realistic monthly cost.\n"
                "3. **Plan for tolerability.** Ask what side effects should be expected, what warning signs deserve attention, and what to do if the routine feels hard to tolerate.\n"
                "4. **Build the maintenance layer.** Discuss protein intake, strength training, sleep, long-term eating patterns, and what happens if the medication is paused or stopped."
            )
        elif lane == "cbd":
            steps = (
                f"A useful next step for {subject} is to treat it like a test, not a personality change.\n\n"
                "1. **Check the product first.** Look for clear labeling, third-party testing, cannabinoid content, and added ingredients.\n"
                "2. **Check interaction risk.** If you take medications, have liver concerns, are pregnant, or have a medical condition, discuss CBD with a qualified professional.\n"
                "3. **Track the whole next day.** Track sleep quality, grogginess, mood, and whether the same effect repeats.\n"
                "4. **Compare it against routine fixes.** Timing, caffeine, alcohol, screen use, pain, and stress may explain more than the product does."
            )
        elif lane == "blood":
            steps = (
                f"A useful next step for {subject} is to stop guessing and make the pattern easier to review.\n\n"
                "1. **Write down timing.** Note when it happens, what you ate or did before it, and whether sleep, stress, exercise, or illness changed.\n"
                "2. **Track what repeats.** One isolated moment matters less than a pattern that keeps showing up or getting stronger.\n"
                "3. **Watch for other signs.** Fatigue, thirst, dizziness, pain, numbness, headaches, or sudden changes can alter the level of concern.\n"
                "4. **Escalate appropriately.** Bring repeat patterns to a qualified professional, and seek urgent care for severe, sudden, or worsening symptoms."
            )
        else:
            steps = (
                f"A useful next step for {subject} is to turn the promise into a decision you can actually test.\n\n"
                "1. **Define the real outcome.** Decide what would count as success beyond one good day.\n"
                "2. **Name the friction.** Track cost, time, symptoms, boredom, and routine pressure.\n"
                "3. **Compare the tradeoff.** Ask whether the payoff is worth what the plan asks from your life.\n"
                "4. **Set a review point.** Decide when you will keep, adjust, or stop the plan instead of drifting."
            )
        return f"## {heading}\n\n{steps}"

    def _faq(self, keyword: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        if lane == "medication":
            qas = [
                (f"Does {subject} actually work if you are not the perfect candidate", f"It may help some people, but that phrase matters. A medication-related weight-loss decision depends on medical history, metabolic context, side-effect tolerance, other prescriptions, cost, and follow-up. If a person expects the medication to replace the whole strategy, disappointment becomes more likely. The better question is whether {subject} fits the person's real health situation and whether a qualified clinician agrees the potential benefit is worth the tradeoff. Weight change alone is not enough to judge the decision. The plan also has to be safe, affordable, tolerable, and realistic to maintain."),
                (f"Why do people stop seeing progress with {subject}", "Progress can slow for several reasons, and a search result cannot diagnose which one applies. Sometimes early changes are partly motivation, water shifts, or tighter routine. Sometimes side effects make consistency harder. Sometimes food quality, protein intake, sleep, stress, strength training, or medical context becomes the limiting factor. The practical move is not to panic over a slower trend. It is to bring a clear record to a qualified clinician: what changed, what side effects showed up, what the routine looks like, and whether other health markers need review."),
                (f"Is {subject} worth it if insurance or refills are annoying", "Access friction can change the whole decision. A plan that looks good medically may become stressful if refills are unpredictable, coverage is unclear, or out-of-pocket cost is too high. That does not automatically mean the option is wrong, but it means access belongs in the decision from the start. Ask about realistic monthly cost, prior authorization, refill timing, pharmacy availability, and what to do if a refill is delayed. If the plan depends on perfect access and perfect follow-through, it may not be durable enough for real life."),
                (f"What should I ask a clinician before using {subject}", "Ask practical questions, not only outcome questions. Start with whether your medical history, current medications, and goals make the option appropriate to discuss. Then ask what side effects are common, which symptoms should not be ignored, what follow-up is needed, how refills work, and what the maintenance plan should include. It is also worth asking what would make the plan a bad fit. A careful clinician conversation should leave you with a clearer decision, not just a stronger desire for a quick result."),
            ]
        elif lane == "cbd":
            qas = [
                (f"Does {subject} actually work or is it mostly hype", f"It can feel useful for some people, but the honest answer depends on what you are measuring. A calmer night, less tension, or easier sleep onset is not the same as a guaranteed effect. Product quality, timing, dose consistency, added ingredients, expectations, and other routines can all change the result. The best way to judge {subject} is to track the whole pattern: what happened that night, how you felt the next morning, whether the result repeated, and whether any side effects or interactions made the tradeoff less appealing."),
                (f"Can {subject} make you groggy the next morning", "It can for some people, especially when timing, amount, other ingredients, alcohol, or other sleep aids are involved. That is why judging only the night itself can be misleading. A product may seem helpful if you fall asleep faster, but less helpful if the next morning feels dull or heavy. Track alertness, mood, and focus the next day before deciding whether the product is worth repeating. If you take medications or have a medical condition, check with a qualified professional before making CBD part of a routine."),
                (f"How do you know if a CBD product is low quality", "A low-quality product often gives you very little to verify. Watch for vague labels, no third-party testing, unclear CBD amount, confusing cannabinoid claims, aggressive promises, or ingredient lists that hide the real reason the product feels strong. Better product evaluation starts with transparency. You want to know what is in it, how much is in it, whether it has been tested, and whether the company is making claims that sound too medical or too certain."),
                (f"Should you use {subject} every night", "That depends on why you are using it, how you feel the next day, whether the effect repeats, and whether there are safety concerns such as medication interactions. Using it nightly without tracking can hide the real issue, especially if sleep timing, caffeine, alcohol, anxiety, pain, or screen habits are the bigger drivers. A better approach is to treat it like a structured test and review whether it actually improves the problem you care about."),
            ]
        elif lane == "blood":
            qas = [
                (f"When should {subject} worry me", f"A repeating, worsening, severe, sudden, or hard-to-explain pattern deserves more attention than a one-off moment. The context matters: timing, meals, sleep, stress, medications, other symptoms, and whether the issue keeps coming back. If symptoms are severe, sudden, or feel urgent, do not wait for more tracking. For non-emergency uncertainty, write down the pattern and discuss it with a qualified professional so the conversation is based on more than memory."),
                (f"Can {subject} happen even if I feel fine", "Yes, some blood-related patterns can be quiet or easy to miss, which is why symptoms alone are not always enough. That does not mean every small change is dangerous. It means the pattern matters. Repeated readings, timing, other health conditions, medications, family history, and lifestyle context can all change what the result means. If you are unsure, bring clear notes or readings to a professional instead of trying to interpret the pattern from a single search result."),
                (f"What should I track with {subject}", "Track the details that help someone interpret the pattern: time of day, meals, activity, sleep, stress, medications, symptoms, and whether the issue repeats. If numbers are involved, record the actual reading and when it was taken. If symptoms are involved, write down what else happened around the same time. The goal is not to self-diagnose. The goal is to make the next step clearer and reduce the chance of either overreacting or ignoring something that is repeating."),
                (f"Can food or stress affect {subject}", "Food, stress, sleep, illness, activity, hydration, and medication changes can all affect blood-related patterns, depending on the issue. That is why context is so important. A number or symptom that appears after a specific meal, a poor night of sleep, or a stressful day may mean something different from a pattern that appears randomly or keeps worsening. Track the surrounding details and discuss repeat patterns with a qualified professional."),
            ]
        else:
            qas = [
                (f"Does {subject} actually work in real life", f"It can, but only if the real-life version matches the promise. A plan that works during a perfect week may fail when stress, travel, boredom, meals out, cost, or symptoms show up. The better standard is not whether {subject} sounds good. It is whether the result is repeatable when life gets normal again."),
                (f"Why do people get disappointed with {subject}", "Disappointment usually appears when the expectation is cleaner than the process. People expect a shortcut, then discover the routine has tradeoffs. Sometimes the idea still has value, but it cannot carry the whole outcome by itself. The smarter move is to identify the friction early instead of blaming yourself later."),
                (f"How long should you test {subject}", "Long enough to see a pattern, not just one good or bad day. A useful test includes ordinary days, stressful days, and days when motivation is lower. If it only works when everything is perfect, that tells you something important about the plan."),
                (f"What is the biggest mistake with {subject}", "The biggest mistake is treating the promise as the strategy. A real strategy includes what you will do when the plan becomes boring, inconvenient, expensive, or slower than expected. That is where the honest decision usually begins."),
            ]
        lines = ["## Frequently Asked Questions"]
        for question, answer in qas:
            lines.append(f"### {question}\n\n{answer}")
        return "\n\n".join(lines)

    def _closing(self, keyword: str) -> str:
        lane = self._lane(keyword)
        subject = self._subject(keyword)
        if lane == "medication":
            text = f"The useful move after searching {subject} is not to crown a winner from a headline. It is to collect the practical facts that decide whether the option is realistic for you: medical fit, side-effect tolerance, access, coverage, follow-up, cost, and maintenance. Bring those questions to a qualified clinician before turning a search result into a personal plan."
        elif lane == "cbd":
            text = f"The useful move after searching {subject} is not to buy the calmest promise. It is to check product quality, safety context, timing, next-day effect, and whether the result repeats enough to justify the routine."
        elif lane == "blood":
            text = f"The useful move after searching {subject} is not to guess from one moment. It is to track the pattern clearly, watch for repeat or worsening signs, and bring the right context to a qualified professional."
        else:
            text = f"The useful move after searching {subject} is not to copy the loudest claim. It is to test the promise against your actual life and decide whether the tradeoff still makes sense."
        return f"## The Next Step Without Guesswork\n\n{text}"

    def _tail(self, keyword: str) -> str:
        lane = self._lane(keyword)
        if lane == "cbd":
            refs = (
                "- [FDA Cannabis and Cannabis-Derived Products](https://www.fda.gov/news-events/public-health-focus/fda-regulation-cannabis-and-cannabis-derived-products-including-cannabidiol-cbd)\n"
                "- [NCCIH Cannabis and Cannabinoids](https://www.nccih.nih.gov/health/cannabis-marijuana-and-cannabinoids-what-you-need-to-know)\n"
                "- [MedlinePlus Marijuana](https://medlineplus.gov/marijuana.html)"
            )
        elif lane == "blood":
            refs = (
                "- [CDC Diabetes](https://www.cdc.gov/diabetes/)\n"
                "- [NHLBI High Blood Cholesterol](https://www.nhlbi.nih.gov/health/high-blood-cholesterol)\n"
                "- [MedlinePlus Blood Glucose](https://medlineplus.gov/bloodglucose.html)"
            )
        else:
            refs = (
                "- [NIDDK Health Risks of Overweight and Obesity](https://www.niddk.nih.gov/health-information/weight-management/adult-overweight-obesity/health-risks)\n"
                "- [CDC Healthy Weight](https://www.cdc.gov/healthy-weight-growth/)\n"
                "- [MedlinePlus Weight Control](https://medlineplus.gov/weightcontrol.html)"
            )
        return (
            "## AI Disclosure\n"
            "This article draft was prepared with AI assistance and reviewed through a structured editorial workflow.\n\n"
            "## References\n"
            f"{refs}\n\n"
            "## Author\n"
            f"**{self._author_bio(keyword)}**"
        )

    def _final_cleanup(self, body: str, lane: str) -> str:
        cleaned = body
        for pattern in self.FORBIDDEN_OPENING_PATTERNS:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bThe Short Answer[^\n]*\n", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(drinking|drink|drank)\s+it\b", "using it", cleaned, flags=re.IGNORECASE)
        if lane == "medication":
            cleaned = re.sub(r"\b(Phase\s+(?:I|II|III|1|2|3)|FDA[-\s]?approved|FDA\s+cleared|clinical pipeline|market availability|biological supremacy|guaranteed)\b", "source-dependent claim", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\btea|smoothie|ritual drink|sweet coffee\b", "routine", cleaned, flags=re.IGNORECASE)
        cleaned = self._tighten_mobile_paragraphs(cleaned)
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _tighten_mobile_paragraphs(self, markdown: str) -> str:
        blocks = re.split(r"(\n\n+)", markdown)
        output: list[str] = []
        for block in blocks:
            if block.startswith("\n"):
                output.append(block)
                continue
            stripped = block.strip()
            if not stripped:
                output.append(block)
                continue
            if stripped.startswith(("## ", "### ", "- ", "|", ">", "[IMAGE:", "[YOUTUBE_VIDEO:")) or re.match(r"^\d+\.\s", stripped):
                output.append(stripped)
                continue
            words = stripped.split()
            if len(words) <= 50:
                output.append(stripped)
                continue
            sentences = re.split(r"(?<=[.!?])\s+", stripped)
            paras: list[str] = []
            current: list[str] = []
            current_words = 0
            for sentence in sentences:
                count = len(sentence.split())
                if current and (len(current) >= 2 or current_words + count > 50):
                    paras.append(" ".join(current).strip())
                    current = [sentence]
                    current_words = count
                else:
                    current.append(sentence)
                    current_words += count
            if current:
                paras.append(" ".join(current).strip())
            output.append("\n\n".join(paras))
        return "".join(output)


def run_cli() -> int:
    parser = argparse.ArgumentParser(description="Run PAS locked viral article generation")
    parser.add_argument("keyword", help="Input search keyword")
    parser.add_argument("--workspace", default=".", help="Workspace root containing references/prompts")
    parser.add_argument("--output", default=".", help="Output directory for generated markdown")
    parser.add_argument("--category", type=int, default=1, help="Article category_id")
    parser.add_argument("--keyword-id", type=int, default=None, help="Optional CMS keyword_id")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    controller = EditorialPipelineController(workspace, output_root=output)
    result: PipelineResult = controller.run_generation(args.keyword, category_id=args.category, keyword_id=args.keyword_id)
    preview_path = render_preview_html(result.markdown_path)
    article = load_article(result.markdown_path)
    print(f"Markdown: {result.markdown_path}")
    print(f"Preview: {preview_path}")
    print(f"Title: {article.get('title')}")
    print(f"Category: {article.get('category_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
