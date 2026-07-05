#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publish generated Markdown articles to the AnQiCMS import API.

This importer follows the same contract as the legacy publish_articles.py:
- Endpoint: https://manage.teiastyle.com/import/article
- Token: query parameter ?token=...
- Default token fallback: anqicms-import
- JSON payload fields: title, content, keyword_id, category_id, keywords, description
- Fixed category IDs: weight_loss=1, cbd=5, blood=9

Safety:
- Without --publish, this script only performs dry-run.
- With --publish, it uses --token, CMS_IMPORT_TOKEN, ANQICMS_IMPORT_TOKEN, or the default fallback token.
- Use --only-publish-ready to import only rows marked publish_ready=yes and quality_status=PASS.

Network compatibility:
- POST requests include browser-like headers to avoid simple WAF/Cloudflare blocks that reject Python's default urllib user agent.
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
DEFAULT_IMPORT_TOKEN = "anqicms-import"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

CATEGORY_ID_MAP = {
    "weight_loss": 1,
    "cbd": 5,
    "blood": 9,
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_category(category: str) -> str:
    raw = normalize(category).lower().replace("-", "_").replace(" ", "_")
    if raw in {"weight", "weightloss", "weight_loss", "weight_loss_articles", "减肥", "减肥药"}:
        return "weight_loss"
    if raw in {"cbd", "hemp", "cbd_articles"}:
        return "cbd"
    if raw in {"blood", "blood_health", "blood_sugar", "blood_pressure", "blood_articles", "血", "血糖", "血压"}:
        return "blood"
    return raw


def category_id_for_row(row: dict[str, str], override: int = 0) -> int | None:
    if override and override > 0:
        return int(override)
    category = normalize_category(row.get("category", ""))
    if category in CATEGORY_ID_MAP:
        return CATEGORY_ID_MAP[category]
    blob = normalize(" ".join([row.get("keyword", ""), row.get("title", ""), row.get("body_template", "")])).lower()
    if "cbd" in blob or "hemp" in blob:
        return CATEGORY_ID_MAP["cbd"]
    if any(term in blob for term in ["blood", "a1c", "cholesterol", "glucose", "pressure", "血糖", "血压"]):
        return CATEGORY_ID_MAP["blood"]
    if any(term in blob for term in ["weight", "ozempic", "wegovy", "zepbound", "metformin", "berberine", "减肥"]):
        return CATEGORY_ID_MAP["weight_loss"]
    return None


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


def first_value(cli_value: str, env_names: list[str], config: dict[str, str], config_names: list[str], default: str = "") -> str:
    if cli_value:
        return cli_value
    for name in env_names:
        value = os.getenv(name, "")
        if value:
            return value
    for name in config_names:
        value = config.get(name, "")
        if value and not value.startswith("paste-your-"):
            return value
    return default


def import_url(base_url: str, token: str) -> str:
    base = base_url.rstrip("/")
    query = urllib.parse.urlencode({"token": token})
    return f"{base}/import/article?{query}"


def browser_headers(url: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    user_agent = os.getenv("ANQICMS_USER_AGENT", "") or os.getenv("CMS_IMPORT_USER_AGENT", "") or DEFAULT_USER_AGENT
    referer = os.getenv("ANQICMS_REFERER", "") or os.getenv("CMS_IMPORT_REFERER", "") or f"{origin}/"
    return {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Origin": origin,
        "Referer": referer,
        "User-Agent": user_agent,
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def post_json(url: str, payload: dict[str, Any], timeout: int = 90) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=browser_headers(url))
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


def is_publish_ready(row: dict[str, str]) -> bool:
    publish_ready = normalize(row.get("publish_ready", "")).lower()
    quality_status = normalize(row.get("quality_status", "")).upper()
    return publish_ready in {"yes", "true", "1", "pass"} and quality_status in {"PASS", ""}


def filter_rows(rows: list[dict[str, str]], only_publish_ready: bool, max_articles: int) -> list[dict[str, str]]:
    filtered = [row for row in rows if is_publish_ready(row)] if only_publish_ready else rows
    if max_articles and max_articles > 0:
        filtered = filtered[:max_articles]
    return filtered


def build_payload(row: dict[str, str], category_override: int = 0) -> tuple[dict[str, Any], str]:
    title = normalize(row.get("title") or row.get("keyword"))
    md_path = Path(row.get("markdown_path", ""))
    if not md_path.exists():
        raise FileNotFoundError(f"markdown not found: {md_path}")
    raw_md = md_path.read_text(encoding="utf-8", errors="ignore")
    content = ensure_cms_media(raw_md, title, row)
    category_id = category_id_for_row(row, category_override)
    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "keywords": build_keywords(row),
        "description": description_from_markdown(content),
    }
    if normalize(row.get("keyword_id", "")).isdigit():
        payload["keyword_id"] = int(normalize(row.get("keyword_id", "")))
    elif category_id:
        payload["category_id"] = category_id
    return payload, content


def cms_error_message(exc: urllib.error.HTTPError) -> str:
    body = exc.read().decode("utf-8", errors="ignore")
    message = f"HTTP {exc.code}: {body[:500]}"
    if exc.code == 403 and "1010" in body:
        message += " | blocked_by_waf_or_cloudflare_1010: request reached the domain but was blocked before AnQiCMS handled it. Whitelist /import/article POST or disable the related WAF rule if this still appears after browser headers."
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish article Markdown files to AnQiCMS import API.")
    parser.add_argument("queue", help="article_publish_queue.csv")
    parser.add_argument("--config", default="local_api_keys.json")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--category-id", type=int, default=0, help="Override category_id. 0 means use fixed mapping: weight_loss=1, cbd=5, blood=9")
    parser.add_argument("--max-articles", type=int, default=0, help="0 means all")
    parser.add_argument("--only-publish-ready", action="store_true", help="Import only rows with publish_ready=yes and quality_status=PASS")
    parser.add_argument("--publish", action="store_true", help="Actually POST articles. Without this flag, dry-run only.")
    args = parser.parse_args()

    config = load_config(args.config)
    if not config and args.config == "local_api_keys.json":
        config = load_config("scripts/local_api_keys.json")
    base_url = first_value(args.base_url, ["CMS_IMPORT_BASE_URL", "ANQICMS_IMPORT_BASE_URL"], config, ["CMS_IMPORT_BASE_URL", "ANQICMS_IMPORT_BASE_URL"], DEFAULT_BASE_URL)
    token = first_value(args.token, ["CMS_IMPORT_TOKEN", "ANQICMS_IMPORT_TOKEN"], config, ["CMS_IMPORT_TOKEN", "ANQICMS_IMPORT_TOKEN"], DEFAULT_IMPORT_TOKEN)

    queue_rows = filter_rows(read_csv(Path(args.queue)), bool(args.only_publish_ready), int(args.max_articles or 0))
    article_url = import_url(base_url, token) if args.publish else ""

    results: list[dict[str, Any]] = []
    for idx, row in enumerate(queue_rows, start=1):
        title = normalize(row.get("title") or row.get("keyword"))
        try:
            payload, content = build_payload(row, int(args.category_id or 0))
        except Exception as exc:  # noqa: BLE001
            results.append({"title": title, "status": "error", "cms_id": "", "message": str(exc)[:500]})
            continue

        if not payload.get("keyword_id") and not payload.get("category_id"):
            results.append({"title": title, "status": "error", "cms_id": "", "message": "missing keyword_id/category_id"})
            continue

        if not args.publish:
            video_mode = "real_youtube" if has_real_youtube(content) else "cms_fallback_video"
            id_mode = f"keyword_id={payload.get('keyword_id')}" if payload.get("keyword_id") else f"category_id={payload.get('category_id')}"
            message = json.dumps({"payload_preview": payload, "video_mode": video_mode, "id_mode": id_mode}, ensure_ascii=False)[:1000]
            results.append({"title": title, "status": "dry_run", "cms_id": "", "message": message})
            continue

        try:
            response = post_json(article_url, payload)
            ok = int(response.get("code", 0)) == 200
            cms_id = response.get("data", {}).get("id", "") if isinstance(response.get("data"), dict) else ""
            results.append({"title": title, "status": "success" if ok else "error", "cms_id": cms_id, "message": response.get("msg", json.dumps(response, ensure_ascii=False))})
            print(f"[{idx}/{len(queue_rows)}] {'OK' if ok else 'ERROR'} {title}")
        except urllib.error.HTTPError as exc:
            results.append({"title": title, "status": "error", "cms_id": "", "message": cms_error_message(exc)})
        except Exception as exc:  # noqa: BLE001
            results.append({"title": title, "status": "error", "cms_id": "", "message": str(exc)[:500]})

    write_csv(Path(args.output), results, ["title", "status", "cms_id", "message"])
    print(f"Selected rows: {len(queue_rows)}")
    print("Endpoint: /import/article")
    print("Token source: --token / env / local config / default fallback")
    print("Headers: browser-like User-Agent, Origin, Referer, Accept, X-Requested-With")
    print("Payload fields: title, content, keyword_id/category_id, keywords, description")
    print("Category mapping: weight_loss=1, cbd=5, blood=9")
    print(f"Wrote CMS import results to {args.output}")
    if not args.publish:
        print("Dry run only. Add --publish to actually post articles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
