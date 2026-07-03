#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AnQiCMS Automated Document Publisher - MDX Engine Connector

Description:
    Iterates over standardized MDX markdown assets from the local
    production directory and uploads them directly to the AnQiCMS REST endpoint.

Usage:
    # Upload a single document asset (extension optional)
    python3 publish_articles.py single_post_name

    # Upload an explicit file path
    python3 publish_articles.py single_post_name.md

    # Run a complete batch processing deployment across the directory
    python3 publish_articles.py

    # Force override specific taxonomy category bindings and time intervals
    python3 publish_articles.py single_post_name --category 16 --interval 2
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

import requests

from media_enrichment import MultimediaEnricher

# ==================== Core Gateway Configuration ====================
API_URL = "https://manage.teiastyle.com/import/article"
API_TOKEN = os.environ.get("ANQICMS_IMPORT_TOKEN", "anqicms-import")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = PROJECT_ROOT
DEFAULT_INTERVAL = 1
DESCRIPTION_MAX_LENGTH = 160
# ====================================================================


def truncate_description(description: str, limit: int = DESCRIPTION_MAX_LENGTH) -> str:
    """Clamp description text to a database-safe length.

    Args:
        description: Raw description text.
        limit: Maximum number of characters to keep.

    Returns:
        Trimmed single-line description.
    """
    normalized = re.sub(r"\s+", " ", str(description)).strip()
    if len(normalized) <= limit:
        return normalized
    shortened = normalized[:limit].rstrip(" ,;:-")
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return shortened.rstrip(" ,;:-") + "..."


def parse_mdx_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse MDX-style frontmatter and split the document body.

    Args:
        content: Raw markdown file contents.

    Returns:
        A tuple of frontmatter metadata and the markdown body.
    """
    pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
    match = re.match(pattern, content, re.DOTALL)

    if not match:
        return {}, content

    frontmatter_str = match.group(1)
    body_content = match.group(2).strip()

    metadata: dict[str, Any] = {}
    for line in frontmatter_str.split('\n'):
        line = line.strip()
        if not line or ':' not in line:
            continue

        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()

        if not key:
            continue

        if value.lower() == 'true':
            metadata[key] = True
        elif value.lower() == 'false':
            metadata[key] = False
        else:
            try:
                metadata[key] = int(value)
            except ValueError:
                try:
                    metadata[key] = float(value)
                except ValueError:
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    metadata[key] = value

    return metadata, body_content


def find_article_file(filename: str) -> Path:
    """Resolve a target markdown file path while preserving .md compatibility.

    Args:
        filename: Input filename with or without the .md suffix.

    Returns:
        Absolute article path.

    Raises:
        FileNotFoundError: If the file does not exist in the articles directory.
    """
    direct_candidate = Path(filename)
    if direct_candidate.is_file():
        return direct_candidate.resolve()

    resolved_name = filename if filename.endswith('.md') else f"{filename}.md"
    filepath = ARTICLES_DIR / resolved_name
    if filepath.is_file():
        return filepath

    matches = list(ARTICLES_DIR.rglob(resolved_name))
    if matches:
        return matches[0]

    raise FileNotFoundError(
        f"Target file asset missing from path context: {resolved_name}\n"
        f"Please verify the file exists inside: {ARTICLES_DIR}"
    )


def build_media_root(article_path: Path) -> Path:
    """Build the output directory for generated media assets.

    Args:
        article_path: Path to the source markdown article.

    Returns:
        Media output directory.
    """
    return article_path.parent / "generated_media" / article_path.stem


def enrich_article_content(article_path: Path, content: str, article_title: str | None = None) -> str:
    """Resolve placeholders into real-media preview content.

    Args:
        article_path: Path to the source article file.
        content: Original markdown body.
        article_title: Article title used to improve media-search relevance.

    Returns:
        Preview-oriented enriched content.
    """
    enricher = MultimediaEnricher(build_media_root(article_path), article_title=article_title)
    return enricher.enrich_markdown(content)


def enrich_article_content_for_cms(article_path: Path, content: str, article_title: str | None = None) -> str:
    """Resolve placeholders into CMS-compatible markdown placeholders.

    Args:
        article_path: Path to the source article file.
        content: Original markdown body.
        article_title: Article title used for placeholder metadata.

    Returns:
        CMS-compatible markdown content.
    """
    enricher = MultimediaEnricher(build_media_root(article_path), article_title=article_title)
    return enricher.enrich_markdown_for_cms(content)


def normalize_article_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Fill optional CMS metadata fields with stable defaults.

    Args:
        metadata: Parsed frontmatter metadata.

    Returns:
        Normalized metadata dictionary.
    """
    normalized = dict(metadata)
    normalized.setdefault("tag", "")
    normalized.setdefault("country", "")
    normalized.setdefault("region", "")
    normalized.setdefault("locality", "")
    return normalized


def load_article(filepath: Path) -> dict[str, Any]:
    """Validate required frontmatter fields and return a sanitized post payload.

    Args:
        filepath: Source markdown article path.

    Returns:
        Article dictionary ready for publishing.

    Raises:
        ValueError: If required frontmatter is missing.
    """
    content = filepath.read_text(encoding='utf-8')
    metadata, body_content = parse_mdx_frontmatter(content)
    metadata = normalize_article_metadata(metadata)
    article_title = str(metadata.get("title", ""))
    enriched_content = enrich_article_content_for_cms(filepath, body_content, article_title=article_title)
    article: dict[str, Any] = {"content": enriched_content, **metadata}

    if "title" not in article:
        raise ValueError(
            f"Validation failure: missing 'title' frontmatter in {filepath.name}"
        )
    if "category_id" not in article:
        raise ValueError(
            f"Validation failure: missing 'category_id' frontmatter in {filepath.name}"
        )

    article["category_id"] = int(article["category_id"])
    if article["category_id"] not in {1, 5, 9}:
        raise ValueError(
            f"Validation failure: category_id must be 1, 5, or 9 in {filepath.name}"
        )
    if "description" in article and article["description"] not in (None, ""):
        article["description"] = truncate_description(str(article["description"]))
    return article


def publish_article(article: dict[str, Any]) -> dict[str, Any]:
    """Upload a single article payload to the AnQiCMS import endpoint.

    Args:
        article: Parsed article payload.

    Returns:
        Normalized publish result.
    """
    payload: dict[str, Any] = {}
    for field in ("title", "content", "keyword_id", "category_id", "keywords", "description"):
        if field in article and article[field] not in (None, ""):
            payload[field] = article[field]

    try:
        response = requests.post(
            API_URL,
            params={"token": API_TOKEN},
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        api_code = int(result.get("code", 0) or 0)
        remote_id = result.get("data", {}).get("id") if isinstance(result.get("data"), dict) else None
        return {
            "ok": response.status_code == 200 and api_code == 200,
            "http_status": response.status_code,
            "api_code": api_code,
            "message": str(result.get("msg", "")),
            "remote_id": remote_id,
            "data": result.get("data"),
            "raw": result,
        }
    except requests.exceptions.RequestException as error:
        print(f"Request failed: {error}")
        return {
            "ok": False,
            "http_status": None,
            "api_code": None,
            "message": str(error),
            "remote_id": None,
            "data": None,
            "raw": None,
        }


def publish_single(filepath: Path, force_category: int | None = None) -> dict[str, Any]:
    """Execute a single publish operation.

    Args:
        filepath: Source article path.
        force_category: Optional category override.

    Returns:
        Publish result payload.
    """
    try:
        article = load_article(filepath)
        if force_category is not None:
            article["category_id"] = int(force_category)

        print(f"Deploying: {article.get('title', 'Untitled')}")
        print(f"Category: {article.get('category_id')}")
        print(f"File: {filepath.name}")

        result = publish_article(article)
        if result.get("ok"):
            print(f"Upload verified successfully. Remote ID: {result.get('remote_id', 'N/A')}")
        else:
            print(f"Backend error: {result.get('message')}")
        return result
    except Exception as error:
        print(f"Deployment exception: {error}")
        return {"code": -1, "msg": str(error), "data": None}


def publish_batch(all_articles: list[dict[str, Any]], interval: int | None = None) -> tuple[int, int]:
    """Publish a list of loaded article payloads sequentially.

    Args:
        all_articles: Article payloads.
        interval: Sleep duration between publish operations.

    Returns:
        Success and failure counts.
    """
    if interval is None:
        interval = DEFAULT_INTERVAL

    success = 0
    failed = 0

    for index, article in enumerate(all_articles, 1):
        print(f"\n[{index}/{len(all_articles)}] {article.get('title', 'Untitled')}")
        result = publish_article(article)

        if result.get("ok"):
            print(f"Upload verified successfully. Remote ID: {result.get('remote_id', 'N/A')}")
            success += 1
        else:
            print(f"Backend error: {result.get('message')}")
            failed += 1

        if index < len(all_articles) and interval > 0:
            time.sleep(interval)

    print("\n" + "=" * 40)
    print(f"Batch complete: success {success}, failed {failed}")
    return success, failed


def publish_all_articles(category_id: int | None = None, interval: int | None = None) -> tuple[int, int]:
    """Load and publish all markdown articles from the workspace directory.

    Args:
        category_id: Optional category override.
        interval: Sleep duration between publish operations.

    Returns:
        Success and failure counts.
    """
    if not ARTICLES_DIR.is_dir():
        print(f"Workspace target structure missing or unreachable: {ARTICLES_DIR}")
        return 0, 0

    md_files = sorted(
        path for path in ARTICLES_DIR.rglob('*.md')
        if path.is_file() and path.name != 'MEMORY.md' and '.claude' not in path.parts
    )
    if not md_files:
        print("No actionable markdown source assets discoverable in current environment context.")
        return 0, 0

    print(f"Discovered {len(md_files)} production files for validation. Running batch operations...\n")

    articles: list[dict[str, Any]] = []
    for filepath in md_files:
        try:
            article = load_article(filepath)
            if category_id is not None:
                article["category_id"] = category_id
            articles.append(article)
        except ValueError as error:
            print(f"Skipping {filepath.name}: {error}")

    return publish_batch(articles, interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AnQiCMS Google SEO Document Deployment Utility")
    parser.add_argument(
        "filename",
        nargs="?",
        default=None,
        help="Explicit filename target inside the workspace directory",
    )
    parser.add_argument(
        "--category",
        "-c",
        type=int,
        default=None,
        help="Override default category mappings manually",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=DEFAULT_INTERVAL,
        help="Throttle delay in seconds between batch entries",
    )
    parser.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        help="Simulate frontmatter analysis without dispatching requests",
    )
    parser.add_argument(
        "--dir",
        "-D",
        default=str(ARTICLES_DIR),
        help=f"Articles directory (default: {ARTICLES_DIR})",
    )
    args = parser.parse_args()

    ARTICLES_DIR = Path(args.dir)

    print(f"API endpoint: {API_URL}")
    print(f"Articles directory: {ARTICLES_DIR}")
    print("-" * 50)

    if args.dry_run:
        print("\n[Dry-run mode enabled. No requests will be sent.]\n")

    if args.filename:
        try:
            target_path = find_article_file(args.filename)
        except FileNotFoundError as error:
            print(f"Execution error: {error}", file=sys.stderr)
            sys.exit(1)

        if args.dry_run:
            article = load_article(target_path)
            print(f"Title: {article.get('title')}")
            print(f"Category ID: {article.get('category_id')}")
            print(f"Description: {article.get('description', 'N/A')}")
            print(f"Keywords: {article.get('keywords', 'N/A')}")
            print(f"Tags: {article.get('tag', 'N/A')}")
            print(f"Content length: {len(article.get('content', ''))} characters")
            print("\n[Preview complete]")
        else:
            result = publish_single(target_path, args.category)
            sys.exit(0 if result.get("ok") else 1)
    else:
        if args.dry_run:
            if not ARTICLES_DIR.is_dir():
                print(f"Workspace target structure missing or unreachable: {ARTICLES_DIR}")
                sys.exit(1)

            md_files = sorted(
                path for path in ARTICLES_DIR.rglob('*.md')
                if path.is_file() and path.name != 'MEMORY.md' and '.claude' not in path.parts
            )
            if not md_files:
                print("No actionable markdown source assets discoverable in current environment context.")
                sys.exit(1)

            print(f"Discovered {len(md_files)} production files:\n")
            for filepath in md_files:
                try:
                    article = load_article(filepath)
                    print(f"  - {article.get('title', 'Untitled')} ({filepath.name})")
                except Exception as error:
                    print(f"  - {filepath.name} (Parse error: {error})")
        else:
            success, failed = publish_all_articles(args.category, args.interval)
            sys.exit(0 if failed == 0 else 1)
