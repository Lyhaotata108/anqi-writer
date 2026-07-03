#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch-generate articles by turning raw keywords into titles first."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import time

from cleanup_generated import cleanup_generated_outputs
from pipeline_controller import PipelineController, TitlePlan


WORKSPACE_ROOT = Path("/Users/hjg/Documents/anqicms-writer")
DEFAULT_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class BatchRow:
    keyword: str
    category_id: int
    keyword_id: int | None = None


def load_batch_rows(input_path: Path, default_category_id: int) -> list[BatchRow]:
    """Load keywords from txt or csv input."""
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        return _load_csv_rows(input_path, default_category_id)
    return _load_text_rows(input_path, default_category_id)


def _load_text_rows(input_path: Path, default_category_id: int) -> list[BatchRow]:
    rows: list[BatchRow] = []
    for raw_line in input_path.read_text(encoding="utf-8").splitlines():
        keyword = raw_line.strip()
        if not keyword or keyword.startswith("#"):
            continue
        rows.append(BatchRow(keyword=keyword, category_id=_normalize_category_id(default_category_id)))
    return rows


def _load_csv_rows(input_path: Path, default_category_id: int) -> list[BatchRow]:
    rows: list[BatchRow] = []
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for item in reader:
            keyword = str(item.get("keyword", "")).strip()
            if not keyword:
                continue
            category_value = str(item.get("category_id", "")).strip()
            keyword_id_value = str(item.get("keyword_id", "")).strip()
            rows.append(
                BatchRow(
                    keyword=keyword,
                    category_id=_normalize_category_id(int(category_value)) if category_value else _normalize_category_id(default_category_id),
                    keyword_id=int(keyword_id_value) if keyword_id_value else None,
                )
            )
    return rows


def _normalize_category_id(category_id: int) -> int:
    if category_id in {1, 5, 9}:
        return category_id
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch article generation for AnQiCMS")
    parser.add_argument("--input", "-i", required=True, help="Path to keywords .txt or .csv file")
    parser.add_argument("--category", "-c", type=int, default=1, help="Default category_id, only 1 or 5")
    parser.add_argument("--limit", type=int, default=0, help="Limit the number of rows processed")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS, help="Delay in seconds between rows")
    parser.add_argument("--publish", action="store_true", help="Publish each generated article after generation")
    parser.add_argument("--resume", action="store_true", help="Skip rows whose markdown file already exists")
    parser.add_argument("--titles-only", action="store_true", help="Only generate title plans and save them to JSON")
    parser.add_argument("--output-json", default="", help="Optional JSON output path for title plans or batch results")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    cleanup_summary = cleanup_generated_outputs(WORKSPACE_ROOT)
    print(
        "Cleanup complete: "
        f"removed_files={cleanup_summary.removed_files} "
        f"removed_directories={cleanup_summary.removed_directories}"
    )

    input_path = Path(args.input).expanduser().resolve()
    rows = load_batch_rows(input_path, args.category)
    if args.limit > 0:
        rows = rows[: args.limit]
    if not rows:
        print("No input keywords found.")
        return 1

    controller = PipelineController(WORKSPACE_ROOT)
    title_plans: list[TitlePlan] = []

    skipped_title_failures = 0
    for index, row in enumerate(rows, 1):
        style = controller.suggest_title_styles(row.keyword)[0]
        title_plan = controller.generate_title_plan(row.keyword, style=style)
        if title_plan is None:
            skipped_title_failures += 1
            print(f"[{index}/{len(rows)}] skipped title generation after two Gemini failures: {row.keyword}")
            if args.delay > 0 and index < len(rows):
                time.sleep(args.delay)
            continue
        title_plans.append(title_plan)
        print(
            f"[{index}/{len(rows)}] style={title_plan.style} candidates={','.join(title_plan.candidate_styles)} "
            f"title={title_plan.title} topic_category={title_plan.topic_category}"
        )
        if args.delay > 0 and index < len(rows):
            time.sleep(args.delay)

    if args.titles_only:
        output_path = _resolve_output_json(args.output_json, input_path, suffix="titles")
        output_path.write_text(
            json.dumps([asdict(plan) for plan in title_plans], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Saved title plans to {output_path}")
        if skipped_title_failures:
            print(f"Skipped {skipped_title_failures} keywords because Gemini title generation failed twice")
        return 0

    results: list[dict[str, object]] = []
    title_plan_map = {plan.source_keyword: plan for plan in title_plans}
    generated_total = len(title_plans)
    processed_index = 0
    for row in rows:
        title_plan = title_plan_map.get(row.keyword)
        if title_plan is None:
            results.append(
                {
                    "keyword": row.keyword,
                    "title": "",
                    "topic_category": "",
                    "style": "",
                    "candidate_styles": list(controller.suggest_title_styles(row.keyword)),
                    "status": "failed",
                    "error": "Gemini title generation did not produce any acceptable title after retry; skipped without fallback template",
                }
            )
            continue

        processed_index += 1
        slug = _slugify(title_plan.title)
        markdown_path = WORKSPACE_ROOT / f"ui_{slug}.md"
        if args.resume and markdown_path.is_file():
            print(f"[{processed_index}/{generated_total}] skipped existing {markdown_path.name}")
            results.append(
                {
                    "keyword": row.keyword,
                    "title": title_plan.title,
                    "topic_category": title_plan.topic_category,
                    "style": title_plan.style,
                    "candidate_styles": list(title_plan.candidate_styles),
                    "markdown_path": str(markdown_path),
                    "status": "skipped",
                }
            )
            continue

        try:
            result = controller.run_generation(
                title_plan.title,
                category_id=row.category_id,
                keyword_id=row.keyword_id,
                style=title_plan.style,
            )
            record: dict[str, object] = {
                "keyword": row.keyword,
                "title": title_plan.title,
                "topic_category": title_plan.topic_category,
                "style": title_plan.style,
                "candidate_styles": list(title_plan.candidate_styles),
                "markdown_path": str(result.markdown_path),
                "preview_path": str(result.preview_path),
                "status": "generated",
            }
            print(f"[{processed_index}/{generated_total}] generated {result.markdown_path.name}")

            if args.publish:
                publish_result = controller.publish_existing(result.markdown_path)
                record["publish"] = publish_result
                print(
                    f"[{processed_index}/{generated_total}] publish ok={publish_result.get('ok')} "
                    f"remote_id={publish_result.get('remote_id')}"
                )

            results.append(record)
        except Exception as error:  # noqa: BLE001
            results.append(
                {
                    "keyword": row.keyword,
                    "title": title_plan.title,
                    "topic_category": title_plan.topic_category,
                    "style": title_plan.style,
                    "status": "failed",
                    "error": str(error),
                }
            )
            print(f"[{processed_index}/{generated_total}] failed {title_plan.title}: {error}")
        if args.delay > 0 and processed_index < generated_total:
            time.sleep(args.delay)

    output_path = _resolve_output_json(args.output_json, input_path, suffix="results")
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved batch results to {output_path}")
    return 0


def _resolve_output_json(configured: str, input_path: Path, suffix: str) -> Path:
    if configured:
        return Path(configured).expanduser().resolve()
    return WORKSPACE_ROOT / f"{input_path.stem}.{suffix}.json"


def _slugify(value: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-") or "article"


if __name__ == "__main__":
    raise SystemExit(main())
