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
python3 scripts/quality_guard.py ui_berberine-weight-loss.md
```

Run a directory:

```bash
python3 scripts/quality_guard.py . --corpus .
```

## Browser UI integration

File:

```text
scripts/browser_ui.py
```

Current behavior:

1. Before generating each keyword, the browser UI builds a deterministic variation brief.
2. It saves the brief files under:

```text
output/briefs/ui_<keyword>.brief.json
output/briefs/ui_<keyword>.brief.txt
```

3. It logs the lane, entity, intent, scene, and brief filename.
4. After generation, it runs `quality_guard.py` logic automatically.
5. Each result includes `quality_score`, `quality_passed`, `quality_issues`, `quality_warnings`, and the brief paths.
6. The UI summary shows quality score and PASS/REVIEW status per article.

## Recommended safe workflow

1. Put one category CSV per file under `data/`.
2. Run clustering.
3. Review `.clusters.csv`.
4. Paste `.to_generate.txt` keywords into the browser UI.
5. Generate a 100-keyword test batch.
6. Review quality scores and failed issues.
7. Expand to 500, then 2000+ only after the failure pattern is understood.

## Still pending

The browser UI now creates and stores variation briefs and runs quality guard, but the article writer still needs deeper integration so the generated article body fully follows each variation brief.

Next steps:

- Inject the variation brief directly into the article body builder.
- Use quality guard failures to trigger automatic rewrite/repair.
- Feed secondary keywords from clustering into each article brief.
