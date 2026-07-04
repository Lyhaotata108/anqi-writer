# Keyword clustering workflow

Use this before batch article generation. The goal is to avoid creating one article for every raw keyword when many keywords share the same search intent.

## Recommended file layout

```text
data/keywords_weight_loss.csv
data/keywords_cbd.csv
data/keywords_blood.csv
```

Each CSV should have a `Keyword` column. If there is no header, the script reads the first column.

## Run clustering

```bash
python3 scripts/cluster_keywords_large.py data/keywords_weight_loss.csv --category 1
python3 scripts/cluster_keywords_large.py data/keywords_cbd.csv --category 5
python3 scripts/cluster_keywords_large.py data/keywords_blood.csv --category 9
```

Each run writes three outputs next to the input file:

```text
<name>.clusters.csv
<name>.members.csv
<name>.to_generate.txt
```

## Files

`clusters.csv` is the main review file. Each row is one suggested article.

`members.csv` maps every original keyword to a cluster and primary keyword.

`to_generate.txt` contains primary keywords to paste into the browser UI.

## should_generate

`yes` means the cluster has at least two keywords.

`maybe` means the cluster has only one keyword. Review these before large batch generation.

To export only `yes` clusters:

```bash
python3 scripts/cluster_keywords_large.py data/keywords_weight_loss.csv --category 1 --yes-only
```

## Practical rule

Generate articles from primary keywords only. Put secondary keywords into the article brief, FAQ, or metadata later.
