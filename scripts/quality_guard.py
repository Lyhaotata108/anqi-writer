#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quality guard for generated Markdown articles.

Checks:
- import-safe frontmatter/body contract
- mobile paragraph length
- generic/template phrases
- missing table / FAQ / action guide
- malformed YouTube placeholders
- repeated n-grams against an optional corpus directory
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import argparse
import json
import re
from pathlib import Path


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
    "sounds easy until real life starts testing it",
    "promise meets real life",
    "the moment the promise meets real life",
    "the first result is not the whole story",
]

REQUIRED_SECTIONS = [
    "## Frequently Asked Questions",
    "## The Next Step Without Guesswork",
    "## AI Disclosure",
    "## References",
    "## Author",
]

ACTION_GUIDE_PATTERNS = [
    r"##\s+What To Do",
    r"##\s+What To Do Before",
    r"##\s+The Next Step Without Guesswork",
    r"##\s+Daily Protocol",
]

# These are hard-risk wording patterns. They intentionally avoid benign FAQ
# questions such as "Can I stop taking Ozempic...?" and instead target advice
# that appears to tell the reader to make medication changes without care.
YMYL_RISK_PATTERNS = [
    r"\bguaranteed\b",
    r"\bcure\b",
    r"\bwill cure\b",
    r"\bmust take\b",
    r"\b(you should|you can|patients should|people should|it is safe to)\s+stop taking\b",
    r"\bstop taking\s+(?:your\s+)?(?:prescribed|prescription|medication|medicine|drug)\b",
    r"\breplaces medication\b",
    r"\bno risk\b",
    r"\bclinically proven to melt\b",
]

BAD_MEDIA_TOKENS = ["sample123", "dqw4w9wgxcq", "youtube.com", "youtu.be", "http://", "https://"]
METADATA_LEAK_PATTERN = re.compile(r"(?im)^(title|description|keywords|category_id|tag|country|region|locality)\s*:")


@dataclass
class QualityReport:
    path: str
    score: int
    passed: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)


def frontmatter_delimiter_count(markdown: str) -> int:
    return sum(1 for line in markdown.splitlines() if line.strip() == "---")


def strip_frontmatter(markdown: str) -> str:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return markdown
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:]).strip()
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
        if stripped.startswith(("##", "###", "- ", "* ", "|", ">", "[IMAGE:", "[YOUTUBE_VIDEO:")):
            continue
        if re.match(r"^\d+\.\s", stripped):
            continue
        lengths.append(len(words(stripped)))
    return lengths


def ngrams(text: str, n: int = 5) -> set[tuple[str, ...]]:
    toks = words(strip_frontmatter(text))
    return {tuple(toks[i:i+n]) for i in range(max(0, len(toks) - n + 1))}


def canonical_article_key(path: Path) -> str:
    name = path.name
    if name.endswith(".draft.md"):
        name = name[:-9] + ".md"
    return name


def should_skip_similarity_candidate(path: Path, current_path: Path | None) -> bool:
    if path.name.endswith(".draft.md") or ".brief." in path.name:
        return True
    if any(part in {"briefs", ".git", "node_modules", "__pycache__"} for part in path.parts):
        return True
    if current_path:
        try:
            if path.resolve() == current_path.resolve():
                return True
        except FileNotFoundError:
            return True
        if canonical_article_key(path) == canonical_article_key(current_path):
            return True
    return False


def similarity_to_corpus(markdown: str, corpus_dir: Path | None, current_path: Path | None = None) -> tuple[float, str | None]:
    if not corpus_dir or not corpus_dir.exists():
        return 0.0, None
    current = ngrams(markdown, 5)
    if not current:
        return 0.0, None
    best_score = 0.0
    best_file: str | None = None
    for path in corpus_dir.rglob("*.md"):
        if should_skip_similarity_candidate(path, current_path):
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


def duplicate_h2_headings(markdown: str) -> list[str]:
    headings = [h.strip().lower() for h in re.findall(r"^##\s+(.+)$", markdown, flags=re.M)]
    seen: set[str] = set()
    dupes: list[str] = []
    for heading in headings:
        if heading in seen and heading not in dupes:
            dupes.append(heading)
        seen.add(heading)
    return dupes


def body_contains_separator(markdown: str) -> bool:
    body = strip_frontmatter(markdown)
    return any(line.strip() == "---" for line in body.splitlines())


def format_contract_issues(markdown: str) -> list[str]:
    issues: list[str] = []
    body = strip_frontmatter(markdown)
    if frontmatter_delimiter_count(markdown) != 2:
        issues.append("frontmatter line delimiter count must be exactly 2")
    if METADATA_LEAK_PATTERN.search(body):
        issues.append("body contains leaked metadata fields")
    if body_contains_separator(markdown):
        issues.append("body contains markdown separator ---")
    yt_matches = re.findall(r"\[YOUTUBE_VIDEO:\s*([^\]]+)\]", markdown, flags=re.I)
    if len(yt_matches) != 1:
        issues.append("must contain exactly one YouTube query placeholder")
    elif any(token in yt_matches[0].lower() for token in BAD_MEDIA_TOKENS):
        issues.append("YouTube placeholder must be a query, not a URL or fake ID")
    if markdown.count("[IMAGE:") != 1:
        issues.append("must contain exactly one image placeholder")
    for section in ("## Frequently Asked Questions", "## AI Disclosure", "## References", "## Author"):
        if markdown.count(section) != 1:
            issues.append(f"{section} must appear exactly once")
    dupes = duplicate_h2_headings(markdown)
    if dupes:
        issues.append("duplicate H2 headings: " + ", ".join(dupes[:5]))
    return issues


def evaluate_markdown(path: Path, corpus_dir: Path | None = None, min_score: int = 85) -> QualityReport:
    markdown = path.read_text(encoding="utf-8")
    lower = markdown.lower()
    issues: list[str] = []
    warnings: list[str] = []
    score = 100

    for issue in format_contract_issues(markdown):
        issues.append(issue)
        score -= 12

    lengths = paragraph_lengths(markdown)
    long_paragraphs = [length for length in lengths if length > 70]
    if long_paragraphs:
        warnings.append(f"mobile paragraphs long: {len(long_paragraphs)} paragraphs over 70 words")
        score -= min(12, 3 * len(long_paragraphs))

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
    if faq_count < 4:
        issues.append(f"FAQ too thin: {faq_count} questions")
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
    if any(not report.passed for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
