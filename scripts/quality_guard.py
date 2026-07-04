#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quality guard for generated Markdown articles.

Checks:
- mobile paragraph length
- generic/template phrases
- missing named story signals
- missing table / FAQ / action guide
- weak entity-specific detail density
- repeated n-grams against an optional corpus directory
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import argparse
import json
import re
from pathlib import Path
from collections import Counter


FORBIDDEN_PHRASES = [
    "the short answer is",
    "the direct verdict is",
    "searching this keyword usually means",
    "searching {keyword} usually means",
    "a realistic composite scenario looks like this",
    "someone starts",
    "early signal",
    "ordinary life returns",
    "in today's world",
    "many people are wondering",
]

REQUIRED_SECTIONS = [
    "## Frequently Asked Questions",
    "## The Next Step Without Guesswork",
]

ACTION_GUIDE_PATTERNS = [
    r"##\s+What To Do",
    r"##\s+What To Do Before",
    r"##\s+The Next Step Without Guesswork",
]

YMYL_RISK_PATTERNS = [
    r"\bguaranteed\b",
    r"\bcure\b",
    r"\bwill cure\b",
    r"\bmust take\b",
    r"\bstop taking\b",
    r"\breplaces medication\b",
    r"\bno risk\b",
]


@dataclass
class QualityReport:
    path: str
    score: int
    passed: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)


def strip_frontmatter(markdown: str) -> str:
    if markdown.startswith("---"):
        parts = markdown.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return markdown


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def paragraph_lengths(markdown: str) -> list[int]:
    body = strip_frontmatter(markdown)
    lengths: list[int] = []
    for block in re.split(r"\n\s*\n", body):
        stripped = block.strip()
        if not stripped:
            continue
        if stripped.startswith(("##", "###", "- ", "|", ">", "[IMAGE:", "[YOUTUBE_VIDEO:")):
            continue
        if re.match(r"^\d+\.\s", stripped):
            continue
        lengths.append(len(words(stripped)))
    return lengths


def ngrams(text: str, n: int = 5) -> set[tuple[str, ...]]:
    toks = words(strip_frontmatter(text))
    return {tuple(toks[i:i+n]) for i in range(max(0, len(toks) - n + 1))}


def similarity_to_corpus(markdown: str, corpus_dir: Path | None, current_path: Path | None = None) -> tuple[float, str | None]:
    if not corpus_dir or not corpus_dir.exists():
        return 0.0, None
    current = ngrams(markdown, 5)
    if not current:
        return 0.0, None

    best_score = 0.0
    best_file: str | None = None
    for path in corpus_dir.rglob("*.md"):
        if current_path and path.resolve() == current_path.resolve():
            continue
        try:
            other_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        other = ngrams(other_text, 5)
        if not other:
            continue
        score = len(current & other) / max(1, min(len(current), len(other)))
        if score > best_score:
            best_score = score
            best_file = str(path)
    return best_score, best_file


def count_markdown_tables(markdown: str) -> int:
    return len(re.findall(r"\n\|.+\|\n\|[-:|\s]+\|", markdown))


def count_faq_questions(markdown: str) -> int:
    faq_match = re.search(r"##\s+Frequently Asked Questions(?P<body>.*?)(?:\n##\s+|\Z)", markdown, flags=re.S | re.I)
    if not faq_match:
        return 0
    return len(re.findall(r"\n###\s+", faq_match.group("body")))


def has_named_story(markdown: str) -> bool:
    # Simple signal: at least one capitalized first-name-like token appears in opening body.
    body = strip_frontmatter(markdown)
    opening = body[:1500]
    names = re.findall(r"\b[A-Z][a-z]{2,}\b", opening)
    generic = {"Disclaimer", "Last", "Table", "Contents", "Frequently", "Questions", "The", "What", "Before"}
    return any(name not in generic for name in names)


def evaluate_markdown(path: Path, corpus_dir: Path | None = None, min_score: int = 85) -> QualityReport:
    markdown = path.read_text(encoding="utf-8")
    lower = markdown.lower()
    issues: list[str] = []
    warnings: list[str] = []
    score = 100

    lengths = paragraph_lengths(markdown)
    long_paragraphs = [length for length in lengths if length > 55]
    if long_paragraphs:
        issues.append(f"mobile paragraphs too long: {len(long_paragraphs)} paragraphs over 55 words")
        score -= min(20, 5 * len(long_paragraphs))

    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in lower:
            issues.append(f"forbidden generic phrase found: {phrase}")
            score -= 8

    for pattern in YMYL_RISK_PATTERNS:
        if re.search(pattern, lower):
            issues.append(f"ymyl risk wording found: {pattern}")
            score -= 10

    for required in REQUIRED_SECTIONS:
        if required.lower() not in lower:
            issues.append(f"missing required section: {required}")
            score -= 10

    if not any(re.search(pattern, markdown, flags=re.I) for pattern in ACTION_GUIDE_PATTERNS):
        issues.append("missing action guide section")
        score -= 10

    table_count = count_markdown_tables(markdown)
    if table_count < 1:
        issues.append("missing markdown comparison table")
        score -= 8

    faq_count = count_faq_questions(markdown)
    if faq_count < 3:
        issues.append(f"FAQ too thin: {faq_count} questions")
        score -= 8

    if not has_named_story(markdown):
        issues.append("opening does not show a named story/person signal")
        score -= 8

    sim_score, sim_file = similarity_to_corpus(markdown, corpus_dir, current_path=path)
    if sim_score >= 0.70:
        issues.append(f"high similarity to corpus: {sim_score:.2%} vs {sim_file}")
        score -= 25
    elif sim_score >= 0.55:
        warnings.append(f"moderate similarity to corpus: {sim_score:.2%} vs {sim_file}")
        score -= 8

    score = max(0, min(100, score))
    passed = score >= min_score and not issues

    return QualityReport(
        path=str(path),
        score=score,
        passed=passed,
        issues=issues,
        warnings=warnings,
        stats={
            "paragraph_count": len(lengths),
            "max_paragraph_words": max(lengths) if lengths else 0,
            "table_count": table_count,
            "faq_count": faq_count,
            "similarity_to_corpus": round(sim_score, 4),
            "similarity_file": sim_file,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check generated Markdown article quality.")
    parser.add_argument("path", help="Markdown file or directory of Markdown files.")
    parser.add_argument("--corpus", default=None, help="Optional corpus directory for similarity checks.")
    parser.add_argument("--min-score", type=int, default=85, help="Minimum passing score.")
    parser.add_argument("--json", action="store_true", help="Print JSON reports.")
    args = parser.parse_args()

    target = Path(args.path).expanduser().resolve()
    corpus_dir = Path(args.corpus).expanduser().resolve() if args.corpus else None

    paths = sorted(target.rglob("*.md")) if target.is_dir() else [target]
    reports = [evaluate_markdown(path, corpus_dir=corpus_dir, min_score=args.min_score) for path in paths]

    if args.json:
        print(json.dumps([asdict(report) for report in reports], ensure_ascii=False, indent=2))
    else:
        for report in reports:
            status = "PASS" if report.passed else "FAIL"
            print(f"[{status}] {report.score}/100 {report.path}")
            for issue in report.issues:
                print(f"  issue: {issue}")
            for warning in report.warnings:
                print(f"  warning: {warning}")
            print(f"  stats: {report.stats}")

    failed = [report for report in reports if not report.passed]
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
