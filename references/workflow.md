# YMYL Automated Content Generation Engine (CMS Pipeline)

## 1. System Overview

This system is an automated content production workflow that integrates large language models, external search engines for retrieval-augmented generation, and multimedia APIs. Unlike one-shot article generation, it uses a multi-node pipeline architecture to improve factual accuracy, compliance handling, multimedia assembly, and Google E-E-A-T alignment for YMYL topics.

## 2. Pipeline State Machine

Article records move through the following lifecycle:

```text
Pending -> Drafting -> Fact_Checking -> Enriching -> SEO_Optimizing -> Ready_to_Publish
                                                     \-> Manual_Review
```

- `Pending`: Task accepted and waiting for execution.
- `Drafting`: First-pass article generation is in progress.
- `Fact_Checking`: High-risk claims, numbers, and regulations are being verified.
- `Enriching`: Images, video embeds, transcript commentary, and related assets are being added.
- `SEO_Optimizing`: TOC, internal links, metadata, and URL packaging are being assembled.
- `Ready_to_Publish`: The article is complete and safe for publishing handoff.
- `Manual_Review`: The workflow encountered an unverified or conflicting critical claim and stopped for human review.

## 3. Core Pipeline Nodes

### Node 1: Trigger, Sensitivity Classification, and Persona Loading

**Input**
- Business-system keyword input such as `CBD dosage`.

**Action 1: YMYL Intent Classification**
- Call a lightweight LLM to determine whether the keyword belongs to a YMYL-sensitive domain such as health, medicine, law, or finance.
- If yes, set `is_ymyl = true` and `ymyl_level = true` to enable maximum compliance mode.

**Action 2: Author Persona Matching**
- Query `cms_author_personas` using topic labels.
- Select a matching persona and load background story, experience profile, and writing tone.

**Output**
- Seed context for downstream nodes including keyword, YMYL mode, compliance flag, and author persona.

---

### Node 2: Drafting Engine

**Objective**
- Generate the first markdown draft with a strong first-person narrative voice and clear article structure.

**Execution Rules**
- Inject the persona background from Node 1.
- If `ymyl_level == true`, require a first-person opening that starts from a pain point, personal trial, client question, or lived-experience scenario.
- Require H2/H3 structure.
- For any dosage, regulation, efficacy, or numerical claim, preserve language that is explicit enough for downstream fact-checking.
- Avoid clickbait headlines and generic AI filler.

**Output**
- Markdown draft body.

---

### Node 3: RAG Fact-Checking Engine

This is the primary safety gate for YMYL automation.

**Action 1: Claim Extraction**
- Use an LLM to extract all medical claims, numerical statements, legal or regulatory assertions, and other high-risk statements from the draft.

**Action 2: Authoritative Search**
- Call a search API and constrain results to authoritative domains such as `nih.gov`, `fda.gov`, `who.int`, or topic-equivalent top-tier agencies.

**Action 3: Verification and Rewrite**
- Compare the draft against retrieved sources.
- If the claim is verified, store the supporting source in `references_array`.
- If the claim conflicts with authoritative evidence, rewrite the relevant paragraph to align with verified information.
- If the claim cannot be verified, stop the pipeline, append an error entry, and move the article to `Manual_Review`.

**Output**
- Verified or corrected markdown draft plus references.

---

### Node 4: Multimedia Enrichment

**Action 1: Image Enrichment**
- Query a royalty-free image API such as Unsplash or Pexels.
- Generate keyword-relevant alt text for each selected image.

**Action 2: Video and Commentary Enrichment**
- Search YouTube for a relevant video.
- Fetch the transcript when available.
- Generate a short human-sounding commentary block based on the transcript.

**Assembly Rule**
- Insert image URLs, video iframe blocks, and commentary beneath the most relevant H2 sections.
- During draft generation, reserve deterministic placeholders so the Python layer can replace them later.

**Failure Rule**
- If a transcript or video lookup fails, skip the video step and continue. This must not block the rest of the pipeline.

---

### Node 5: SEO and Packaging

**Action 1: TOC Generation**
- Extract H2/H3 headings from the markdown body and generate an HTML anchor table of contents.

**Action 2: Internal Linking**
- Query the CMS content index or database for 1 to 2 highly relevant published articles.
- Insert contextual internal links naturally into the body.

**Action 3: Metadata Generation**
- Generate `meta_description` within the target length budget.
- Generate an SEO-friendly `url_slug`.

**Output**
- SEO-packaged content bundle.

---

### Node 6: Compliance Assembly and Publish Handoff

**Assembly Order**
1. Top disclaimer block when `is_ymyl == true`
2. Table of contents
3. Main article body with multimedia inserts and internal links
4. AI assistance disclosure
5. References list
6. Author bio card

**Persistence Rule**
- Write the final payload into the CMS post structure.
- Transition to `Published`, or save as a pre-publish draft if the business workflow requires a final human glance.

## 4. Shared State JSON

Use a shared state object in Redis, memory, or a queue payload to pass context between nodes.

```json
{
  "task_id": "REQ-10029",
  "target_keyword": "CBD dosage for sleep",
  "is_ymyl": true,
  "ymyl_level": true,
  "author_id": 12,
  "author_bio": "I write evidence-aware explainers grounded in lived user questions and practical editorial review.",
  "personal_story": "I started investigating this topic after seeing how quickly confident supplement claims outran what readers actually needed to know.",
  "content": {
    "title": "...",
    "meta_description": "...",
    "url_slug": "cbd-dosage-for-sleep",
    "markdown_body": "...",
    "toc_html": "..."
  },
  "enrichment": {
    "images": [{"url": "...", "alt": "..."}],
    "videos": [{"iframe": "...", "ai_commentary": "..."}],
    "internal_links": [{"url": "/old-post", "anchor_text": "..."}]
  },
  "compliance": {
    "references": ["https://www.ncbi.nlm.nih.gov/..."],
    "disclaimer_required": true,
    "ai_disclosure_required": true
  },
  "pipeline_status": "Fact_Checking",
  "error_log": []
}
```

## 5. Development Guardrails

### Model Selection
- Prefer models with strong structured output or function-calling support.
- Every machine-readable node should return strict JSON.

### Search API
- Prefer search providers with stable JSON output such as SerpApi or DataForSEO.
- Domain-restricted retrieval should be enforced at the query layer for regulated topics.

### Timeouts and Async Execution
- End-to-end execution may take several minutes.
- Do not run this workflow as a synchronous front-end request.
- Use an async job system such as Celery, RabbitMQ, or Redis Queue.

### Failure Policy
- Non-critical enrichment failures should be logged and skipped.
- Fact-checking conflicts on critical YMYL claims must raise a blocking error and force `Manual_Review`.
