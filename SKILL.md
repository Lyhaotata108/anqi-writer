---
name: ymyl-cms-pipeline
description: "Runs a multi-node YMYL content automation pipeline for English content generation, fact-checking, multimedia enrichment, SEO packaging, and compliant CMS publishing. Designed for high-sensitivity health, medical, finance, and other YMYL topics under Google E-E-A-T and GEO requirements."
dependency:
  skill:
    - /human-writing
---

# YMYL Automated Content Generation Engine (CMS Pipeline)

## Execution Guide

This skill is a YMYL-specialized orchestration entrypoint for high-sensitivity English content. Review and follow these references before running the pipeline:

- `references/workflow.md` (Multi-node YMYL pipeline architecture, state machine, and node responsibilities)
- `references/output_template.md` (Standardized output examples and packaging reference)

## Core Mandates

- **Strict YMYL Safety Mode**: Health, medical, legal, financial, and other high-risk topics must run under enhanced fact-checking and compliance rules.
- **E-E-A-T First**: Content must demonstrate experience, expertise, authoritativeness, and trustworthiness. Do not output vague, generic, or fluff-heavy copy.
- **Structured Outputs Only**: Every machine-readable stage must return strict JSON so downstream parsing remains stable.
- **Fact-Checking Circuit Breaker**: If critical claims cannot be verified through approved authoritative sources, the pipeline must stop and hand off to manual review.
- **Graceful Degradation**: Non-critical enrichment failures such as missing video transcripts must not block publishing preparation.

## Core Pipeline States

- `Pending`
- `Drafting`
- `Fact_Checking`
- `Enriching`
- `SEO_Optimizing`
- `Ready_to_Publish`
- `Manual_Review`

## Core Asset Paths

- Workflow definition: `references/workflow.md`
- Output reference: `references/output_template.md`
- Prompt blueprints: `references/prompts/stage1_1_anqicms.md`, `references/prompts/stage1_2_anqicms.md`, `references/prompts/stage2_anqicms.md`
- Target article workspace: `doc/geo/articles/`
- Automated publisher: `scripts/publish_articles.py`

## Execution Scope

This skill is intended to orchestrate:

1. Keyword intake and YMYL classification
2. Persona loading and first-person draft generation
3. Claim extraction and authoritative fact-checking
4. Multimedia enrichment with image/video commentary
5. SEO packaging, TOC generation, and internal linking
6. Compliance assembly and CMS publishing handoff
