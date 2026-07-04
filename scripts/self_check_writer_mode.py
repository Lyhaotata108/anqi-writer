#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check whether the local browser UI is wired to the sample-style writer."""

from __future__ import annotations

from pathlib import Path
import sys


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
    if "Sample Style Generator" not in browser:
        issues.append("browser_ui.py does not show the Sample Style Generator UI label")
    if "FORBIDDEN_STYLE_PHRASES" not in sample:
        issues.append("sample_style_writer.py is missing forbidden phrase guard")
    if "raise RuntimeError" not in sample:
        issues.append("sample_style_writer.py may not hard-fail bad drafts")

    if issues:
        print("WRITER MODE CHECK: FAIL")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("WRITER MODE CHECK: PASS")
    print("browser_ui.py is wired to sample_style_writer.py")
    print("Expected page title: AnQiCMS Sample Style Generator")
    print("Expected logs: [Keyword], [Route], [Writing], [Quality]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
