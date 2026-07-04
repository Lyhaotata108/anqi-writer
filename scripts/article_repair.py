#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repair generated AnQiCMS markdown using the configured Gemini endpoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from pipeline_controller import PipelineController
from sample_style_writer import build_repair_prompt, normalize_markdown
from quality_guard import evaluate_markdown


def repair_article_if_needed(markdown_path: Path, workspace_root: Path, min_score: int = 85) -> bool:
    report = evaluate_markdown(markdown_path, corpus_dir=workspace_root, min_score=min_score)
    if report.passed:
        return False
    markdown = markdown_path.read_text(encoding="utf-8")
    keyword = markdown_path.stem.replace("ui_", "").replace("-", " ")
    category_id = 1
    for line in markdown.splitlines():
        if line.startswith("category_id:"):
            try:
                category_id = int(line.partition(":")[2].strip())
            except ValueError:
                category_id = 1
            break
    prompt = build_repair_prompt(markdown, report.issues + report.warnings, keyword, category_id, "sample_style")
    controller = PipelineController(workspace_root, output_root=workspace_root)
    repaired = controller._call_gemini_with_retry(prompt, attempts=1)
    if not repaired:
        return False
    fixed = normalize_markdown(repaired, keyword, category_id, "sample_style")
    markdown_path.write_text(fixed, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair one markdown file if it fails quality guard.")
    parser.add_argument("path")
    parser.add_argument("--workspace", default="/Users/hjg/Documents/anqicms-writer")
    parser.add_argument("--min-score", type=int, default=85)
    args = parser.parse_args()
    changed = repair_article_if_needed(Path(args.path).expanduser().resolve(), Path(args.workspace).expanduser().resolve(), args.min_score)
    print("repaired" if changed else "no change")


if __name__ == "__main__":
    main()
