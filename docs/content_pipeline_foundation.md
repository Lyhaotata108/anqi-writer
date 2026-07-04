# Content pipeline foundation

This repository now has the baseline modules needed before large batch generation.

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

## 2. Intent classifier

File:

```text
scripts/intent_classifier.py
```

Purpose:

- Classify a keyword into `entity`, `intent`, `modifier`, `page_type`, `lane`, and `cluster_key`.
- Designed for local processing before any AI call.

Run one keyword:

```bash
python3 scripts/intent_classifier.py "berberine vs metformin"
```

Run a CSV:

```bash
python3 scripts/intent_classifier.py data/keywords_weight_loss.csv
```

## 3. Entity pain bank

File:

```text
scripts/entity_pain_bank.py
```

Purpose:

- Provide reusable story names, scenes, social hooks, pain details, FAQ angles, comparison angles, safety boundaries, and source profiles.
- Entities currently include berberine, metformin, CBD, blood sugar, and cholesterol, with a default fallback pack.

Run:

```bash
python3 scripts/entity_pain_bank.py berberine
```

## 4. Variation engine

File:

```text
scripts/variation_engine.py
```

Purpose:

- Deterministically rotate story names, scenes, hooks, pain details, FAQ angles, and comparison angles.
- The same keyword always gets the same brief.
- Different keywords get different combinations to reduce visible template repetition.

Run:

```bash
python3 scripts/variation_engine.py "berberine weight loss"
python3 scripts/variation_engine.py "berberine weight loss" --json
```

## 5. Quality guard

File:

```text
scripts/quality_guard.py
```

Purpose:

- Score generated Markdown articles.
- Check mobile paragraph length, generic phrases, missing FAQ, missing action guide, missing table, weak named-story signal, YMYL risk wording, and similarity to an optional corpus.

Run one file:

```bash
python3 scripts/quality_guard.py output/ui_berberine-weight-loss.md
```

Run a directory:

```bash
python3 scripts/quality_guard.py output --corpus output
```

## Current integration status

The modules are foundation-ready but not fully wired into the browser UI generation flow yet.

Current safe workflow:

1. Run clustering.
2. Review `.clusters.csv`.
3. Generate from `.to_generate.txt`.
4. Run quality guard on generated Markdown.
5. Review failures before scaling.

Next integration step:

- Feed `variation_engine.py` prompt briefs into the article-generation controller.
- Use `quality_guard.py` after each generated article.
- Auto-rewrite or block articles that fail the guard.
