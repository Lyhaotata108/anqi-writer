#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publish generated Markdown articles to the CMS import API.

Video rule:
- Preserve a real YouTube iframe/link if the article already has one.
- If queue row has selected_youtube_embed_url, insert that real iframe.
- If no real YouTube URL exists, do not insert a placeholder. The CMS can fall back to its keyword-library video.

Image rule:
- Ensure image-placeholder.png exists so the CMS can replace it later.
"""

from __future__ import annotations
from pathlib import Path
import argparse
import csv
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://manage.teiastyle.com"
DEFAULT_OUTPUT = "output/cms_import_results.csv"

CATEGORY_HINTS = {
    "weight_loss": ["keto", "减肥", "减肥药", "weight", "weight loss"],
    "cbd": ["cbd"],
    "blood": ["blood", "血", "血压", "血糖", "cholesterol", "pressure", "glucose"],
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_config(path: str | Path) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def cfg(cli_value: str, env_name: str, config: dict[str, str], config_name: str, default: str = "") -> str:
    return cli_value or os.getenv(env_name, "") or config.get(config_name, "") or default


def url_join(base_url: str, path: str, token: str) -> str:
    base = base_url.rstrip("/")
    query = urllib.parse.urlencode({"token": token})
    return f"{base}{path}?{query}"


def get_json(url: str, timeout: int = 60) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], timeout: int = 90) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def strip_front_matter(markdown: str) -> str:
    text = str(markdown or "").strip()
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.S).strip()


def youtube_embed_from_url(url: str) -> str:
    raw = normalize(url)
    if not raw or "youtube-url-placeholder" in raw:
        return ""
    if "/embed/" in raw:
        return raw
    patterns = [r"youtube\.com/watch\?v=([^&\s]+)", r"youtu\.be/([^?&\s]+)", r"youtube\.com/shorts/([^?&\s]+)"]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.I)
        if match:
            return f"https://www.youtube.com/embed/{match.group(1)}"
    return raw if "youtube.com" in raw else ""


def has_real_youtube(text: str) -> bool:
    return bool(re.search(r"youtube\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/", text, flags=re.I))


def youtube_iframe(src: str) -> str:
    return f'<iframe width="795" height="448" frameborder="0" allowfullscreen src="{src}"></iframe>'


def remove_placeholder_youtube(text: str) -> str:
    out = re.sub(r"\n?## Related Video\s*\n\s*<iframe[^>]+youtube-url-placeholder[^>]*></iframe>\s*", "\n", text, flags=re.I)
    out = re.sub(r"\n?<iframe[^>]+youtube-url-placeholder[^>]*></iframe>\s*", "\n", out, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def ensure_cms_media(markdown: str, title: str, row: dict[str, str]) -> str:
    text = strip_front_matter(markdown)
    text = remove_placeholder_youtube(text)
    if "image-placeholder.png" not in text:
        image_md = f"![{normalize(title)}](image-placeholder.png)"
        parts = text.split("\n\n")
        insert_at = 3 if len(parts) > 4 else min(1, len(parts))
        parts.insert(insert_at, image_md)
        text = "\n\n".join(parts)

    selected_embed = normalize(row.get("selected_youtube_embed_url")) or youtube_embed_from_url(row.get("selected_youtube_url", ""))
    if selected_embed and not has_real_youtube(text):
        video_block = "## Related Video\n\n" + youtube_iframe(selected_embed)
        marker = "## Frequently Asked"
        idx = text.find(marker)
        if idx >= 0:
            text = text[:idx].rstrip() + "\n\n" + video_block + "\n\n" + text[idx:].lstrip()
        else:
            text = text.rstrip() + "\n\n" + video_block
    return text.strip() + "\n"


def description_from_markdown(markdown: str, limit: int = 160) -> str:
    text = strip_front_matter(markdown)
    text = re.sub(r"<iframe.*?</iframe>", " ", text, flags=re.I | re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"[#*_>`|\[\]()]+", " ", text)
    text = normalize(text)
    return text[:limit].rsplit(" ", 1)[0] if len(text) > limit else text


def fetch_keywords(base_url: str, token: str) -> list[dict[str, Any]]:
    data = get_json(url_join(base_url, "/import/keywords", token))
    return data.get("data", []) if isinstance(data, dict) else []


def fetch_categories(base_url: str, token: str) -> list[dict[str, Any]]:
    data = get_json(url_join(base_url, "/import/categories", token))
    return data.get("data", []) if isinstance(data, dict) else []


def match_keyword_id(keyword: str, keywords: list[dict[str, Any]]) -> int | None:
    target = normalize(keyword).lower()
    if not target:
        return None
    for item in keywords:
        if normalize(item.get("title", "")).lower() == target:
            try:
                return int(item["id"])
            except Exception:
                return None
    return None


def match_category_id(category: str, categories: list[dict[str, Any]]) -> int | None:
    hints = CATEGORY_HINTS.get(category, [category])
    for item in categories:
        title = normalize(item.get("title", "")).lower()
        template = normalize(item.get("template_dir", "")).lower()
        blob = f"{title} {template}"
        if any(h.lower() in blob for h in hints):
            try:
                return int(item["id"])
            except Exception:
                return None
    return None


def build_keywords(row: dict[str, str]) -> str:
    parts = [row.get("keyword", ""), row.get("category", ""), row.get("body_template", "")]
    clean = []
    seen = set()
    for part in parts:
        item = normalize(part).replace("_", " ")
        if item and item.lower() not in seen:
            seen.add(item.lower())
            clean.append(item)
    return ",".join(clean)


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish article Markdown files to CMS import API.")
    parser.add_argument("queue", help="article_publish_queue.csv")
    parser.add_argument("--config", default="local_api_keys.json")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--category-id", type=int, default=0, help="Fallback category_id if keyword/category matching fails")
    parser.add_argument("--max-articles", type=int, default=0, help="0 means all")
    parser.add_argument("--publish", action="store_true", help="Actually POST articles. Without this flag, dry-run only.")
    args = parser.parse_args()

    config = load_config(args.config)
    if not config and args.config == "local_api_keys.json":
        config = load_config("scripts/local_api_keys.json")
    base_url = cfg(args.base_url, "CMS_IMPORT_BASE_URL", config, "CMS_IMPORT_BASE_URL", DEFAULT_BASE_URL)
    token = cfg(args.token, "CMS_IMPORT_TOKEN", config, "CMS_IMPORT_TOKEN")
    if not token:
        raise SystemExit("Missing CMS token. Set CMS_IMPORT_TOKEN, put it in local_api_keys.json, or pass --token.")

    queue_rows = read_csv(Path(args.queue))
    if args.max_articles and args.max_articles > 0:
        queue_rows = queue_rows[: args.max_articles]

    keywords = fetch_keywords(base_url, token) if args.publish else []
    categories = fetch_categories(base_url, token) if args.publish else []
    article_url = url_join(base_url, "/import/article", token)

    results: list[dict[str, Any]] = []
    for idx, row in enumerate(queue_rows, start=1):
        title = normalize(row.get("title") or row.get("keyword"))
        md_path = Path(row.get("markdown_path", ""))
        if not md_path.exists():
            results.append({"title": title, "status": "error", "cms_id": "", "message": f"markdown not found: {md_path}"})
            continue
        raw_md = md_path.read_text(encoding="utf-8", errors="ignore")
        content = ensure_cms_media(raw_md, title, row)
        keyword_id = match_keyword_id(row.get("keyword", ""), keywords) if args.publish else None
        category_id = None if keyword_id else (args.category_id or match_category_id(row.get("category", ""), categories) if args.publish else args.category_id or None)

        payload: dict[str, Any] = {
            "title": title,
            "content": content,
            "keywords": build_keywords(row),
            "description": description_from_markdown(content),
        }
        if keyword_id:
            payload["keyword_id"] = keyword_id
        elif category_id:
            payload["category_id"] = category_id

        if not payload.get("keyword_id") and not payload.get("category_id"):
            results.append({"title": title, "status": "error", "cms_id": "", "message": "missing keyword_id/category_id"})
            continue

        if not args.publish:
            video_mode = "real_youtube" if has_real_youtube(content) else "cms_fallback_video"
            message = json.dumps({"payload_preview": payload, "video_mode": video_mode}, ensure_ascii=False)[:700]
            results.append({"title": title, "status": "dry_run", "cms_id": "", "message": message})
            continue

        try:
            response = post_json(article_url, payload)
            ok = int(response.get("code", 0)) == 200
            cms_id = response.get("data", {}).get("id", "") if isinstance(response.get("data"), dict) else ""
            results.append({"title": title, "status": "success" if ok else "error", "cms_id": cms_id, "message": response.get("msg", json.dumps(response, ensure_ascii=False))})
            print(f"[{idx}/{len(queue_rows)}] {'OK' if ok else 'ERROR'} {title}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            results.append({"title": title, "status": "error", "cms_id": "", "message": f"HTTP {exc.code}: {body[:500]}"})
        except Exception as exc:
            results.append({"title": title, "status": "error", "cms_id": "", "message": str(exc)[:500]})

    write_csv(Path(args.output), results, ["title", "status", "cms_id", "message"])
    print(f"Wrote CMS import results to {args.output}")
    if not args.publish:
        print("Dry run only. Add --publish to actually post articles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
