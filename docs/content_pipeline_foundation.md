# Content pipeline foundation

The main browser generation flow now uses a sample-style AI writer rather than the deterministic paragraph assembler.

## Current production test flow

```text
keywords
↓
keyword cleanup
↓
intent classification
↓
article type routing
↓
sample-style AI writer
↓
local repair pass if the draft misses required structure
↓
quality guard
↓
preview
↓
AnQiCMS import
```

## 1. Keyword clustering

File:

```text
scripts/cluster_keywords_large.py
```

Purpose:

- Merge raw keywords into entity + intent + modifier clusters.
- Select one `primary_keyword` per cluster.
- Export `.clusters.csv`, `.members.csv`, and `.to_generate.txt`.

Run:

```bash
python3 scripts/cluster_keywords_large.py data/keywords_weight_loss.csv --category 1
python3 scripts/cluster_keywords_large.py data/keywords_cbd.csv --category 5
python3 scripts/cluster_keywords_large.py data/keywords_blood.csv --category 9
```

## 2. Keyword cleanup

File:

```text
scripts/keyword_cleaner.py
```

Purpose:

- Normalize keywords before generation.
- Mark malformed, too-short, or numeric product-like keywords as `needs_review`, `brand_unknown`, `low_quality`, or `skip`.

Run:

```bash
python3 scripts/keyword_cleaner.py "100 lemon juice for weight loss"
python3 scripts/keyword_cleaner.py "top 10 green tea for weight loss"
```

## 3. Intent classifier

File:

```text
scripts/intent_classifier.py
```

Purpose:

- Classify a keyword into `entity`, `intent`, `modifier`, `page_type`, `lane`, and `cluster_key`.

Run:

```bash
python3 scripts/intent_classifier.py "berberine vs metformin"
```

## 4. Article type router

File:

```text
scripts/article_type_router.py
```

Routes keywords into:

```text
top_10_listicle
evidence_review
process_explainer
comparison_decision
side_effect_safety
generic_editorial
```

Run:

```bash
python3 scripts/article_type_router.py "top 10 green tea for weight loss"
python3 scripts/article_type_router.py "what does a dietitian do for weight loss"
```

## 5. Sample-style AI writer

File:

```text
scripts/sample_style_writer.py
```

Purpose:

- Generate a complete import-ready AnQiCMS Markdown article with frontmatter.
- Follow the target sample style: strong search-confusion opening, evidence-aware framing, tables, FAQ, action protocol, references, and author block.
- Avoid fake internal trials, fake clients, and fake clinical measurements.
- Use real public-evidence language without inventing private data.
- Include one `[IMAGE: ...]` and one `[YOUTUBE_VIDEO: ...]` placeholder.

Run:

```bash
python3 scripts/sample_style_writer.py "metabolism boosters for women over 40" --category 1
python3 scripts/sample_style_writer.py "top 10 green tea for weight loss" --category 1
```

## 6. Article repair

File:

```text
scripts/article_repair.py
```

Purpose:

- Repair one markdown file if the quality guard flags it.
- Uses the configured Gemini-compatible endpoint.

Run:

```bash
python3 scripts/article_repair.py ui_metabolism-boosters-for-women-over-40.md
```

## 7. YouTube helper

File:

```text
scripts/youtube_finder.py
```

Purpose:

- Test whether a keyword resolves to an embeddable YouTube video through the existing `media_enrichment.py` pipeline.
- The article writer only inserts `[YOUTUBE_VIDEO: query]`; media enrichment resolves it during preview/import.

Run:

```bash
python3 scripts/youtube_finder.py "resistance training women over 40 metabolism"
```

## 8. Quality guard

File:

```text
scripts/quality_guard.py
```

Purpose:

- Score generated Markdown articles.
- Check mobile paragraph length, generic phrases, missing FAQ, missing action guide, missing table, weak named-story signal, YMYL risk wording, and similarity to an optional corpus.
- Similarity checks ignore draft files, brief files, and same-slug files to reduce false positives.

Run:

```bash
python3 scripts/quality_guard.py ui_metabolism-boosters-for-women-over-40.md
```

## Browser UI integration

File:

```text
scripts/browser_ui.py
```

Current behavior:

1. Cleans each keyword.
2. Classifies the keyword.
3. Routes it to an article type.
4. Calls `scripts/sample_style_writer.py` for complete Markdown generation.
5. Runs quality guard automatically.
6. Shows article type, quality score, preview link, and import button.

## Recommended test workflow

1. Pull latest code.
2. Start the browser UI.
3. Test 5-10 keywords only.
4. Review whether the output matches the two gold samples.
5. Then test 20-50 keywords.
6. Only after quality is stable, reconnect `.to_generate.txt` from clustering.

## Still pending

- Secondary keyword injection from `.clusters.csv` into the sample writer prompt.
- Stronger source/evidence retrieval before writing.
- Optional YouTube channel whitelist.
