#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export primary keywords from a clusters CSV.

Usage:
    python3 scripts/export_primary_keywords.py data/keywords_weight_loss.clusters.csv
    python3 scripts/export_primary_keywords.py data/keywords_weight_loss.clusters.csv --yes-only
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export primary keywords from a clustering output CSV.")
    parser.add_argument("clusters_csv", help="Path to <name>.clusters.csv")
    parser.add_argument("--yes-only", action="store_true", help="Only export rows where should_generate is yes.")
    parser.add_argument("--output", default=None, help="Optional output txt path.")
    args = parser.parse_args()

    input_path = Path(args.clusters_csv).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"File not found: {input_path}")

    allowed = {"yes"} if args.yes_only else {"yes", "maybe"}
    keywords: list[str] = []

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("should_generate") in allowed:
                keyword = str(row.get("primary_keyword") or "").strip()
                if keyword:
                    keywords.append(keyword)

    output_path = Path(args.output).expanduser().resolve() if args.output else input_path.with_suffix(".to_generate.txt")
    output_path.write_text("\n".join(keywords), encoding="utf-8")
    print(f"Exported {len(keywords)} keywords to {output_path}")


if __name__ == "__main__":
    main()
