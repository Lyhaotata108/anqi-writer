#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check whether the local browser UI is wired to the batch-safe writer."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BROWSER_UI = ROOT / "scripts" / "browser_ui.py"
SAMPLE_WRITER = ROOT / "scripts" / "sample_style_writer.py"


def main() -> int:
    issues: list[str] = []
    browser = BROWSER_UI.read_text(encoding="utf-8") if BROWSER_UI.exists() else ""
    sample = SAMPLE_WRITER.read_text(encoding="utf-8") if SAMPLE_WRITER.exists() else ""

    if "generate_sample_style_article" not in browser:
        issues.append("browser_ui.py is not calling generate_sample_style_article")
    if "brief_article_writer" in browser:
        issues.append("browser_ui.py still imports brief_article_writer")
    if "Batch-Safe Generator" not in browser:
        issues.append("browser_ui.py does not show the Batch-Safe Generator UI label")
    if "PASS-only" not in browser and "PASS articles only" not in browser:
        issues.append("browser_ui.py does not appear to enforce PASS-only import")
    if "batch_reports" not in browser:
        issues.append("browser_ui.py does not appear to write batch reports")
    if "strict JSON" not in sample.lower() and "STRICT JSON" not in sample:
        issues.append("sample_style_writer.py is not using JSON-schema generation")
    if "assemble_markdown" not in sample:
        issues.append("sample_style_writer.py is missing code-side markdown assembly")

    if issues:
        print("WRITER MODE CHECK: FAIL")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("WRITER MODE CHECK: PASS")
    print("browser_ui.py is wired to schema-driven sample_style_writer.py")
    print("Expected page title: AnQiCMS Batch-Safe Generator")
    print("Expected logs: [Keyword], [Route], [Writing], [Quality], [Batch Risk]")
    print("Expected reports: output/batch_reports/batch_<job_id>.json and .csv")
    print("Expected import behavior: PASS-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
