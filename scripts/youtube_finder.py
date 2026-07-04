#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve YouTube placeholders for article media planning.

The production preview/import path already uses `media_enrichment.py`. This helper
is a direct CLI for testing whether a keyword can resolve to an embeddable video.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from media_enrichment import MultimediaEnricher


def find_youtube_video(keyword: str, workspace_root: Path | None = None) -> dict[str, str | None]:
    root = workspace_root or Path.cwd()
    enricher = MultimediaEnricher(root / "generated_media" / "youtube_test", article_title=keyword)
    video = enricher._resolve_video_asset(keyword)
    return {
        "query": video.keyword,
        "url": video.url,
        "embed_url": video.embed_url,
        "commentary": video.commentary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Find an embeddable YouTube video for a keyword.")
    parser.add_argument("keyword", nargs="+")
    parser.add_argument("--workspace", default="/Users/hjg/Documents/anqicms-writer")
    args = parser.parse_args()
    result = find_youtube_video(" ".join(args.keyword), Path(args.workspace))
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
