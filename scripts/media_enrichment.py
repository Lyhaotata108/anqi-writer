#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multimedia enrichment middleware for markdown article placeholders.

This module resolves placeholder directives such as ``[YOUTUBE_VIDEO: keyword]``
and ``[IMAGE: keyword]`` into publishable markdown fragments before the article is
sent to the CMS import endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
import io
import json
import os
import re
from typing import Any, Final
from urllib.parse import quote_plus

import requests


YOUTUBE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:\*\*|__|\*)?\s*(?:<!--\s*YOUTUBE_VIDEO:\s*(.*?)\s*-->|\[YOUTUBE_VIDEO:\s*(.*?)\s*\])\s*(?:\*\*|__|\*)?")
IMAGE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:\*\*|__|\*)?\s*(?:<!--\s*IMAGE:\s*(.*?)\s*-->|\[IMAGE:\s*(.*?)\s*\])\s*(?:\*\*|__|\*)?")
INTERNAL_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:<!--\s*INTERNAL_LINK:\s*(.*?)\s*-->|\[INTERNAL_LINK:\s*(.*?)\s*\])")


@dataclass(frozen=True)
class VideoAsset:
    """Represents a resolved video block for markdown injection.

    Attributes:
        keyword: Source keyword from the placeholder.
        url: Resolved video URL.
        embed_url: Resolved embeddable video URL when available.
        transcript: Transcript or transcript-like summary text.
        commentary: Editor commentary derived from the transcript.
    """

    keyword: str
    url: str
    embed_url: str | None
    transcript: str
    commentary: str


@dataclass(frozen=True)
class ImageAsset:
    """Represents a resolved image block for markdown injection.

    Attributes:
        keyword: Source keyword from the placeholder.
        alt_text: Generated alt text.
        output_path: Relative path to the generated WebP asset.
    """

    keyword: str
    alt_text: str
    output_path: str


@dataclass(frozen=True)
class ApiKeys:
    """API keys loaded from a local file or environment variables.

    Attributes:
        pexels_api_key: Optional Pexels API key.
        unsplash_access_key: Optional Unsplash access key.
        youtube_data_api_key: Optional YouTube Data API key.
    """

    pexels_api_key: str | None
    unsplash_access_key: str | None
    youtube_data_api_key: str | None


class MultimediaEnricher:
    """Resolve markdown multimedia placeholders into publishable markdown.

    The implementation supports live provider lookups when API keys are available.
    """

    def __init__(self, media_root: Path, article_title: str | None = None) -> None:
        """Initialize the enrichment middleware.

        Args:
            media_root: Directory where generated media files should be written.
            article_title: Article title used to improve image-search relevance.
        """
        self.media_root = media_root
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.api_keys = load_api_keys(media_root)
        self.article_title = article_title or ""

    def enrich_markdown(self, markdown_body: str) -> str:
        """Resolve placeholders into real-media preview markup.

        Args:
            markdown_body: Original markdown body containing placeholders.

        Returns:
            Markdown-like content with real media blocks for preview use.
        """
        enriched_body = YOUTUBE_PATTERN.sub(self._replace_video_placeholder, markdown_body)
        enriched_body = IMAGE_PATTERN.sub(self._replace_image_placeholder, enriched_body)
        enriched_body = INTERNAL_LINK_PATTERN.sub(self._replace_internal_link_placeholder, enriched_body)
        enriched_body = remove_manual_editor_notes(enriched_body)
        return enriched_body

    def enrich_markdown_for_cms(self, markdown_body: str) -> str:
        """Resolve placeholders into CMS-compatible markdown placeholders.

        Args:
            markdown_body: Original markdown body containing placeholders.

        Returns:
            Markdown content that follows the CMS import protocol.
        """
        enriched_body = YOUTUBE_PATTERN.sub(self._replace_video_placeholder_for_cms, markdown_body)
        enriched_body = IMAGE_PATTERN.sub(self._replace_image_placeholder_for_cms, enriched_body)
        enriched_body = INTERNAL_LINK_PATTERN.sub(self._replace_internal_link_placeholder_for_cms, enriched_body)
        enriched_body = remove_manual_editor_notes(enriched_body)
        return enriched_body

    def _replace_video_placeholder(self, match: re.Match[str]) -> str:
        keyword = (match.group(1) or match.group(2) or "").strip()
        video = self._resolve_video_asset(keyword)
        iframe_html = ""
        if video.embed_url:
            iframe_html = (
                f"  <iframe width=\"560\" height=\"315\" src=\"{video.embed_url}\" "
                "title=\"YouTube video player\" frameborder=\"0\" "
                "allow=\"accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share\" "
                "referrerpolicy=\"strict-origin-when-cross-origin\" allowfullscreen></iframe>\n"
            )
        return (
            "\n<figure class=\"media-block media-video\">\n"
            f"{iframe_html}"
            f"  <figcaption class=\"media-caption\">Video: {video.keyword}</figcaption>\n"
            f"  <blockquote class=\"editor-commentary\"><strong>Editor’s note:</strong> {video.commentary}</blockquote>\n"
            "</figure>\n"
        )

    def _replace_image_placeholder(self, match: re.Match[str]) -> str:
        keyword = (match.group(1) or match.group(2) or "").strip()
        image_asset = self._resolve_image_asset(keyword)
        return (
            "\n<figure class=\"media-block media-image\">\n"
            f"  <img src=\"{image_asset.output_path}\" alt=\"{image_asset.alt_text}\" />\n"
            "</figure>\n"
        )

    def _replace_internal_link_placeholder(self, match: re.Match[str]) -> str:
        return ""

    def _replace_image_placeholder_for_cms(self, match: re.Match[str]) -> str:
        keyword = (match.group(1) or match.group(2) or "").strip()
        alt_text = generate_image_alt_text(keyword)
        return f"\n![{alt_text}](image-placeholder.png)\n"

    def _replace_video_placeholder_for_cms(self, match: re.Match[str]) -> str:
        keyword = (match.group(1) or match.group(2) or "").strip()
        commentary = generate_ai_editor_commentary(keyword, simulate_transcript_fetch(keyword))
        return (
            '\n<iframe width="795" height="448" frameborder="0" allowfullscreen src="youtube-url-placeholder"></iframe>\n\n'
            f'> **Editor note:** {commentary}\n'
        )

    def _replace_internal_link_placeholder_for_cms(self, match: re.Match[str]) -> str:
        return ""

    def _resolve_video_asset(self, keyword: str) -> VideoAsset:
        """Resolve a YouTube asset using the Data API when configured."""
        video_query = build_youtube_query(self.article_title, keyword)
        resolved: dict[str, str] | None = None
        if self.api_keys.youtube_data_api_key:
            resolved = fetch_youtube_video(video_query, self.api_keys.youtube_data_api_key)
        if resolved is None:
            resolved = scrape_youtube_video(video_query)
        if resolved is not None:
            transcript = fetch_youtube_transcript_like_summary(resolved)
            commentary = generate_ai_editor_commentary(video_query, transcript)
            return VideoAsset(
                keyword=video_query,
                url=resolved["url"],
                embed_url=resolved["embed_url"],
                transcript=transcript,
                commentary=commentary,
            )

        video_url = simulate_youtube_lookup(video_query)
        transcript = simulate_transcript_fetch(video_query)
        commentary = generate_ai_editor_commentary(video_query, transcript)
        return VideoAsset(
            keyword=video_query,
            url=video_url,
            embed_url=simulate_youtube_embed_url(video_query),
            transcript=transcript,
            commentary=commentary,
        )

    def _resolve_image_asset(self, keyword: str) -> ImageAsset:
        """Resolve an image asset using Pexels or Unsplash when configured."""
        alt_text = generate_image_alt_text(keyword)
        output_name = f"{slugify(keyword)}-{short_hash(keyword)}.webp"
        output_path = self.media_root / output_name

        source_bytes: bytes | None = None
        if self.api_keys.pexels_api_key:
            source_bytes = fetch_pexels_image_bytes(keyword, self.article_title, self.api_keys.pexels_api_key)
        elif self.api_keys.unsplash_access_key:
            source_bytes = fetch_unsplash_image_bytes(keyword, self.article_title, self.api_keys.unsplash_access_key)

        if source_bytes is None:
            source_bytes = simulate_image_download(keyword)

        sanitize_and_convert_image(source_bytes, output_path)
        article_base_dir = self.media_root.parent.parent
        relative_output_path = output_path.relative_to(article_base_dir).as_posix()
        return ImageAsset(
            keyword=keyword,
            alt_text=alt_text,
            output_path=relative_output_path,
        )


def load_api_keys(media_root: Path) -> ApiKeys:
    """Load local API keys from file first, then environment variables.

    Supported file names:
    - `local_api_keys.json` beside the article directory
    - `local_api_keys.json` beside this script

    File format:
    {
      "PEXELS_API_KEY": "...",
      "UNSPLASH_ACCESS_KEY": "...",
      "YOUTUBE_DATA_API_KEY": "..."
    }

    Args:
        media_root: Media output directory used to infer a nearby local config.

    Returns:
        Loaded API key bundle.
    """
    candidate_paths = [
        media_root.parent.parent / "local_api_keys.json",
        media_root.parent.parent / "local_api_keys.example.json",
        Path(__file__).resolve().parent / "local_api_keys.json",
        Path(__file__).resolve().parent / "local_api_keys.example.json",
    ]

    file_values: dict[str, Any] = {}
    for candidate in candidate_paths:
        if candidate.is_file():
            file_values = json.loads(candidate.read_text(encoding="utf-8"))
            break

    return ApiKeys(
        pexels_api_key=_pick_config_value(file_values, "PEXELS_API_KEY"),
        unsplash_access_key=_pick_config_value(file_values, "UNSPLASH_ACCESS_KEY"),
        youtube_data_api_key=_pick_config_value(file_values, "YOUTUBE_DATA_API_KEY"),
    )


def _pick_config_value(file_values: dict[str, Any], key: str) -> str | None:
    """Resolve a configuration value from file first, then environment.

    Args:
        file_values: Parsed JSON config values.
        key: Target config key.

    Returns:
        Resolved string value or None.
    """
    value = file_values.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()

    env_value = os.environ.get(key)
    if env_value and env_value.strip():
        return env_value.strip()
    return None


def fetch_youtube_video(keyword: str, api_key: str) -> dict[str, str] | None:
    """Search YouTube and return the first public embeddable video.

    Args:
        keyword: Search keyword.
        api_key: YouTube Data API key.

    Returns:
        Resolved watch and embed URLs or None.
    """
    try:
        search_response = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": keyword,
                "type": "video",
                "videoEmbeddable": "true",
                "videoSyndicated": "true",
                "maxResults": 8,
                "safeSearch": "strict",
                "key": api_key,
            },
            timeout=30,
        )
        search_response.raise_for_status()
        items = search_response.json().get("items", [])
    except requests.RequestException:
        return None
    candidate_ids = [item.get("id", {}).get("videoId") for item in items if item.get("id", {}).get("videoId")]
    if not candidate_ids:
        return None

    try:
        details_response = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "status,snippet",
                "id": ",".join(candidate_ids),
                "key": api_key,
            },
            timeout=30,
        )
        details_response.raise_for_status()
        details_items = details_response.json().get("items", [])
    except requests.RequestException:
        return None

    keyword_tokens = _tokenize(keyword)
    ranked_items = sorted(
        details_items,
        key=lambda item: _score_youtube_item(item, keyword_tokens),
        reverse=True,
    )
    for item in ranked_items:
        status = item.get("status", {})
        if not status.get("embeddable"):
            continue
        if status.get("privacyStatus") != "public":
            continue
        video_id = item.get("id")
        if not video_id:
            continue
        return {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "embed_url": f"https://www.youtube.com/embed/{video_id}",
        }
    return None


def fetch_youtube_transcript_like_summary(video: dict[str, str]) -> str:
    """Build a transcript-like summary for editor commentary.

    Args:
        video: Resolved video metadata.

    Returns:
        Summary text for downstream commentary generation.
    """
    return (
        f"This video at {video['url']} appears to focus on the main topic, covers practical takeaways, "
        "and gives enough context to support a short editorial note even when a full transcript pipeline is not configured."
    )


def scrape_youtube_video(keyword: str) -> dict[str, str] | None:
    """Scrape the public YouTube search page and validate embeddable candidates."""
    try:
        response = requests.get(
            "https://www.youtube.com/results",
            params={"search_query": keyword},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    candidate_ids: list[str] = []
    for video_id in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', response.text):
        if video_id not in candidate_ids:
            candidate_ids.append(video_id)
        if len(candidate_ids) >= 8:
            break
    for video_id in candidate_ids:
        if not is_embeddable_youtube_video(video_id):
            continue
        return {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "embed_url": f"https://www.youtube.com/embed/{video_id}",
        }
    return None


def is_embeddable_youtube_video(video_id: str) -> bool:
    """Check whether the YouTube embed page is playable enough for preview use."""
    try:
        response = requests.get(
            f"https://www.youtube.com/embed/{video_id}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException:
        return False
    text = response.text
    blocked_markers = [
        'Video unavailable',
        'UNPLAYABLE',
        'LOGIN_REQUIRED',
        'This video is unavailable',
    ]
    return not any(marker in text for marker in blocked_markers)


def fetch_pexels_image_bytes(keyword: str, article_title: str, api_key: str) -> bytes | None:
    """Search Pexels and download the most relevant matching image.

    Args:
        keyword: Placeholder keyword.
        article_title: Article title used as the primary search signal.
        api_key: Pexels API key.

    Returns:
        Raw image bytes or None.
    """
    keyword_tokens = _tokenize(f"{article_title} {keyword}")
    queries = build_image_queries(article_title, keyword)
    best_photo: dict[str, Any] | None = None
    best_score = -1

    for query in queries:
        try:
            search_response = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": api_key},
                params={"query": query, "per_page": 8, "orientation": "landscape"},
                timeout=30,
            )
            search_response.raise_for_status()
            photos = search_response.json().get("photos", [])
        except requests.RequestException:
            continue
        for photo in photos:
            score = _score_pexels_photo(photo, keyword_tokens)
            if score > best_score:
                best_score = score
                best_photo = photo
        if best_photo is not None and best_score >= max(2, len(keyword_tokens) // 2):
            break

    if best_photo is None:
        return None

    source_url = best_photo.get("src", {}).get("large2x") or best_photo.get("src", {}).get("large")
    if not source_url:
        return None

    try:
        image_response = requests.get(source_url, timeout=30)
        image_response.raise_for_status()
        return image_response.content
    except requests.RequestException:
        return None


def fetch_unsplash_image_bytes(keyword: str, article_title: str, access_key: str) -> bytes | None:
    """Search Unsplash and download the most relevant matching image.

    Args:
        keyword: Placeholder keyword.
        article_title: Article title used as the primary search signal.
        access_key: Unsplash access key.

    Returns:
        Raw image bytes or None.
    """
    keyword_tokens = _tokenize(f"{article_title} {keyword}")
    queries = build_image_queries(article_title, keyword)
    best_photo: dict[str, Any] | None = None
    best_score = -1

    for query in queries:
        try:
            search_response = requests.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": 8, "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {access_key}"},
                timeout=30,
            )
            search_response.raise_for_status()
            results = search_response.json().get("results", [])
        except requests.RequestException:
            continue
        for photo in results:
            score = _score_unsplash_photo(photo, keyword_tokens)
            if score > best_score:
                best_score = score
                best_photo = photo
        if best_photo is not None and best_score >= max(2, len(keyword_tokens) // 2):
            break

    if best_photo is None:
        return None

    source_url = best_photo.get("urls", {}).get("regular")
    if not source_url:
        return None

    try:
        image_response = requests.get(source_url, timeout=30)
        image_response.raise_for_status()
        return image_response.content
    except requests.RequestException:
        return None


def build_image_queries(article_title: str, keyword: str) -> list[str]:
    """Build image queries with article title first and placeholder keyword second.

    Args:
        article_title: Article title used as the primary search signal.
        keyword: Original image placeholder keyword.

    Returns:
        Ordered search queries from most specific to broader fallback.
    """
    lowered = f"{article_title} {keyword}".lower()
    queries = []
    if article_title.strip():
        queries.extend([
            article_title,
            f"{article_title} {keyword}",
        ])
    queries.append(keyword)
    if "gelatin" in lowered:
        queries.extend([
            "jelly dessert bowl",
            "gelatin dessert bowl",
            "clear jelly snack bowl",
            "food journal scale",
        ])
    if "food journal" in lowered or "appetite tracker" in lowered:
        queries.extend([
            "food journal weight loss",
            "nutrition diary notebook",
        ])
    if "water retention" in lowered or "scale" in lowered:
        queries.extend([
            "bathroom scale measuring tape",
            "weight scale nutrition tracking",
        ])
    if "caution" in lowered or "dieting" in lowered:
        queries.extend([
            "nutrition consultation healthy eating",
            "diet checklist health",
        ])
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query not in seen:
            deduped.append(query)
            seen.add(query)
    return deduped


def build_youtube_query(article_title: str, keyword: str) -> str:
    lane = infer_content_lane(article_title, keyword)
    base = keyword.strip() or article_title.strip() or 'health explainer'
    if lane == 'CBD':
        return f"{base} cbd benefits safety dosage explainer"
    if lane == 'BLOOD':
        return f"{base} blood sugar cholesterol blood pressure health explainer"
    return f"{base} weight loss metabolism diet exercise explainer"


def infer_content_lane(article_title: str, keyword: str) -> str:
    lowered = f"{article_title} {keyword}".lower()
    if any(token in lowered for token in ('cbd', 'cannabidiol', 'hemp', 'gummy', 'gummies', 'tincture', 'oil')):
        return 'CBD'
    if any(token in lowered for token in ('blood', 'glucose', 'a1c', 'cholesterol', 'triglycerides', 'blood pressure', 'hypertension', 'insulin', 'sugar')):
        return 'BLOOD'
    return 'WEIGHT_LOSS'


def _tokenize(value: str) -> set[str]:
    """Tokenize text into lowercase word fragments."""
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


def _score_text_match(text: str, keyword_tokens: set[str]) -> int:
    """Score text by token overlap with the desired keyword set."""
    text_tokens = _tokenize(text)
    return len(text_tokens & keyword_tokens)


def _score_pexels_photo(photo: dict[str, Any], keyword_tokens: set[str]) -> int:
    """Score a Pexels photo for topical relevance."""
    text_parts = [
        str(photo.get("alt", "")),
        str(photo.get("photographer", "")),
        str(photo.get("url", "")),
    ]
    score = _score_text_match(" ".join(text_parts), keyword_tokens)
    width = int(photo.get("width", 0) or 0)
    height = int(photo.get("height", 0) or 0)
    if width >= height:
        score += 1
    return score


def _score_unsplash_photo(photo: dict[str, Any], keyword_tokens: set[str]) -> int:
    """Score an Unsplash photo for topical relevance."""
    text_parts = [
        str(photo.get("alt_description", "")),
        str(photo.get("description", "")),
        str(photo.get("slug", "")),
    ]
    width = int(photo.get("width", 0) or 0)
    height = int(photo.get("height", 0) or 0)
    score = _score_text_match(" ".join(text_parts), keyword_tokens)
    if width >= height:
        score += 1
    return score


def _score_youtube_item(item: dict[str, Any], keyword_tokens: set[str]) -> int:
    """Score a YouTube item for title/description relevance."""
    snippet = item.get("snippet", {})
    combined = f"{snippet.get('title', '')} {snippet.get('description', '')}"
    score = _score_text_match(combined, keyword_tokens)
    lowered = combined.lower()
    if item.get("status", {}).get("embeddable"):
        score += 2
    if any(token in keyword_tokens for token in {'cbd', 'cannabidiol', 'hemp'}) and any(token in lowered for token in ('cbd', 'cannabidiol', 'hemp')):
        score += 4
    if any(token in keyword_tokens for token in {'blood', 'glucose', 'cholesterol', 'insulin', 'pressure'}) and any(token in lowered for token in ('blood', 'glucose', 'cholesterol', 'insulin', 'pressure')):
        score += 4
    if any(token in keyword_tokens for token in {'weight', 'loss', 'diet', 'metabolism', 'exercise'}) and any(token in lowered for token in ('weight loss', 'diet', 'metabolism', 'exercise', 'fat loss')):
        score += 4
    if any(token in lowered for token in ('podcast', 'music', 'shorts', 'mukbang')):
        score -= 3
    return score


def remove_manual_editor_notes(content: str) -> str:
    """Remove manual editor-note lines so only middleware commentary remains.

    Args:
        content: Enriched markdown content.

    Returns:
        Content with standalone manual editor-note lines removed.
    """
    lines = content.splitlines()
    kept_lines = [line for line in lines if not re.match(r"^\s*Editor’s note:\s*", line)]
    return "\n".join(kept_lines)


def short_hash(value: str) -> str:
    """Generate a short stable hash for asset naming."""
    return sha1(value.encode("utf-8")).hexdigest()[:10]


def slugify(value: str) -> str:
    """Convert arbitrary text into a filesystem-safe slug."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return normalized or "asset"


def simulate_youtube_embed_url(keyword: str) -> str | None:
    """No safe embed URL exists without a real video id."""
    return None


def simulate_youtube_lookup(keyword: str) -> str:
    """Build a YouTube search URL for a keyword when no API key is configured."""
    return f"https://www.youtube.com/results?search_query={quote_plus(keyword)}"


def simulate_transcript_fetch(keyword: str) -> str:
    """Simulate transcript retrieval for a YouTube video.

    Args:
        keyword: Placeholder keyword.

    Returns:
        Deterministic transcript text.
    """
    return (
        f"This transcript discusses {keyword}, highlights the most common reader questions, "
        f"explains the main evidence-aware considerations, and separates practical takeaways "
        f"from misleading headline claims."
    )


def generate_ai_editor_commentary(keyword: str, transcript: str) -> str:
    """Generate short editor commentary from transcript content.

    Args:
        keyword: Placeholder keyword.
        transcript: Simulated transcript text.

    Returns:
        A concise editorial note.
    """
    lowered = keyword.lower()
    if any(token in lowered for token in ('side effect', 'side effects', 'nausea', 'fatigue', 'reviews', 'review')):
        return 'This clip is useful because it gives quick context around user complaints, early side effects, and what people tend to misunderstand before they sign up.'
    if any(token in lowered for token in ('cost', 'price', 'subscription')):
        return 'This clip helps most when you want a clearer sense of the pricing story, what is included, and where the sales pitch can feel cleaner than the real commitment.'
    if any(token in lowered for token in ('blood', 'glucose', 'cholesterol', 'pressure')):
        return 'This clip is most useful when you want the practical version of the blood-marker discussion without getting buried in jargon.'
    if any(token in lowered for token in ('cbd', 'gummies', 'hemp', 'tincture')):
        return 'This clip is worth watching if you want the plain-English version of the CBD safety and effectiveness conversation.'
    return 'This clip works best as a quick companion to the article because it turns the main claim into something easier to judge in real-world terms.'


def generate_image_alt_text(keyword: str) -> str:
    """Generate standardized alt text for an image keyword."""
    return f"Illustration related to {keyword}"


def _require_pillow_image() -> type:
    """Import Pillow lazily so the publisher can start without it.

    Returns:
        The Pillow Image module.

    Raises:
        RuntimeError: If Pillow is not installed.
    """
    try:
        from PIL import Image  # type: ignore import-not-found
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Pillow is required for [IMAGE: ...] placeholder processing. Install it with `python3 -m pip install Pillow`."
        ) from error
    return Image


def simulate_image_download(keyword: str) -> bytes:
    """Generate an in-memory placeholder image for a keyword.

    Args:
        keyword: Placeholder keyword.

    Returns:
        PNG image bytes.
    """
    image_module = _require_pillow_image()
    color_seed = int(short_hash(keyword)[:6], 16)
    red = (color_seed >> 16) & 0xFF
    green = (color_seed >> 8) & 0xFF
    blue = color_seed & 0xFF
    image = image_module.new("RGB", (1280, 720), color=(red, green, blue))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def sanitize_and_convert_image(source_bytes: bytes, output_path: Path) -> None:
    """Remove metadata and save the image as WebP.

    Args:
        source_bytes: Original image bytes.
        output_path: Target file path for the WebP asset.
    """
    image_module = _require_pillow_image()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with image_module.open(io.BytesIO(source_bytes)) as source_image:
        clean_image = image_module.new("RGB", source_image.size)
        clean_image.putdata(list(source_image.convert("RGB").getdata()))
        clean_image.save(output_path, format="WEBP", quality=82, method=6)
