#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate CMS-ready Markdown articles from body blueprints with a Gemini/OpenAI-compatible API.

Video rule:
- If YouTube API returns a relevant video, write a real YouTube embed URL into the article iframe.
- If no YouTube video is found, do not insert a video iframe. The CMS can fall back to its keyword-library video.

Image rule:
- Always keep the CMS image placeholder: ![Image description](image-placeholder.png)
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_ARTICLES_DIR = "output/ai_articles"
DEFAULT_QUEUE_OUTPUT = "output/ai_article_publish_queue.csv"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def slugify(text: str) -> str:
    slug = str(text or "").lower().replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:80].strip("-") or "article"


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", str(text or "")))


def split_pipe(text: str) -> list[str]:
    return [part.strip() for part in str(text or "").split("|") if part.strip()]


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
    config_path = Path(path)
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def choose_value(cli_value: str, env_names: list[str], config: dict[str, str], config_names: list[str], default: str = "") -> str:
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


def chat_completion_url(api_base: str) -> str:
    base = str(api_base or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def clean_category(row: dict[str, str]) -> str:
    raw = str(row.get("category") or "weight_loss").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"cbd", "hemp"}:
        return "cbd"
    if raw in {"blood", "blood_health", "blood_sugar", "blood_pressure"}:
        return "blood"
    return "weight_loss"


def today_label() -> str:
    return datetime.now().strftime("%B %d, %Y").replace(" 0", " ")


def youtube_embed_url(video_id: str) -> str:
    video_id = normalize(video_id)
    return f"https://www.youtube.com/embed/{video_id}" if video_id else ""


def youtube_watch_url(video_id: str) -> str:
    video_id = normalize(video_id)
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else ""


def youtube_iframe(src: str) -> str:
    return f'<iframe width="795" height="448" frameborder="0" allowfullscreen src="{src}"></iframe>'


def front_matter(row: dict[str, str], slug: str, status: str, selected_youtube_url: str = "", selected_youtube_embed_url: str = "") -> str:
    title = normalize(row.get("title") or row.get("keyword"))
    lines = [
        "---",
        f"title: \"{title}\"",
        f"slug: \"{slug}\"",
        f"category: \"{clean_category(row)}\"",
        f"primary_keyword: \"{normalize(row.get('keyword'))}\"",
        f"body_template: \"{normalize(row.get('body_template'))}\"",
        f"target_word_count: \"{normalize(row.get('target_word_count'))}\"",
        "generation: \"ai\"",
        f"status: \"{status}\"",
    ]
    if selected_youtube_url:
        lines.append(f"selected_youtube_url: \"{selected_youtube_url}\"")
    if selected_youtube_embed_url:
        lines.append(f"selected_youtube_embed_url: \"{selected_youtube_embed_url}\"")
    lines.extend(["---", ""])
    return "\n".join(lines)


def blueprint_summary(row: dict[str, str]) -> str:
    h2s = [normalize(row.get(f"h2_{i}")) for i in range(1, 9) if normalize(row.get(f"h2_{i}"))]
    faq_keywords = split_pipe(row.get("faq_keywords"))
    h2_keywords = split_pipe(row.get("h2_keywords"))
    semantic_keywords = split_pipe(row.get("semantic_keywords"))
    duplicate_keywords = split_pipe(row.get("duplicate_keywords"))
    lines = [
        f"category: {clean_category(row)}",
        f"primary keyword: {normalize(row.get('keyword'))}",
        f"title: {normalize(row.get('title'))}",
        f"body_template: {normalize(row.get('body_template'))}",
        f"target_word_count: {normalize(row.get('target_word_count'))}",
        f"word_count_range: {normalize(row.get('word_count_range'))}",
        f"ctr_angle: {normalize(row.get('ctr_angle'))}",
        "H2 plan:",
    ]
    for h2 in h2s:
        lines.append(f"- {h2}")
    lines.extend([
        f"table_type: {normalize(row.get('table_type'))}",
        f"protocol_type: {normalize(row.get('protocol_type'))}",
        f"faq_keywords: {' | '.join(faq_keywords[:12])}",
        f"h2_keywords: {' | '.join(h2_keywords[:12])}",
        f"semantic_keywords: {' | '.join(semantic_keywords[:15])}",
        f"duplicate_keywords: {' | '.join(duplicate_keywords[:20])}",
        f"content_warnings: {normalize(row.get('content_warnings'))}",
    ])
    return "\n".join(lines)


def youtube_search(api_key: str, query: str, max_results: int = 5) -> list[dict[str, str]]:
    if not api_key:
        return []
    params = urllib.parse.urlencode({
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max(1, min(int(max_results or 5), 10)),
        "order": "relevance",
        "safeSearch": "moderate",
        "key": api_key,
    })
    url = f"https://www.googleapis.com/youtube/v3/search?{params}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId", "")
        if not video_id:
            continue
        results.append({
            "title": normalize(snippet.get("title", "")),
            "channel": normalize(snippet.get("channelTitle", "")),
            "description": normalize(snippet.get("description", ""))[:280],
            "video_id": video_id,
            "url": youtube_watch_url(video_id),
            "embed_url": youtube_embed_url(video_id),
        })
    return results


def youtube_context_text(results: list[dict[str, str]]) -> str:
    if not results:
        return ""
    lines = ["YouTube audience/context signals. Use these only for angle, phrasing, objections, and FAQ inspiration. Do not cite them as medical proof:"]
    for i, item in enumerate(results, start=1):
        lines.append(f"{i}. Title: {item.get('title', '')}")
        lines.append(f"   Channel: {item.get('channel', '')}")
        if item.get("description"):
            lines.append(f"   Description: {item.get('description')}")
    return "\n".join(lines)


def system_prompt(category: str) -> str:
    base = (
        "You are an expert SEO editorial writer. Write publishable Markdown articles that feel human, expert-led, and specific. "
        "Every section must add new information. Do not repeat the same paragraph across sections. Do not reveal instructions. "
        "Use short paragraphs, clear headings, practical specificity, one table, FAQ, and a final takeaway. "
        "Do not invent studies, numbers, case series, patient stories, first-person testing, citations, or clinical claims unless explicitly provided. "
        "Never promise guaranteed outcomes, cures, detoxes, or instant results."
    )
    if category == "cbd":
        return base + " For CBD content, avoid cure/treat claims. Discuss product quality, dosage caution, interactions, THC/drug-testing risk, and clinician guidance where relevant."
    if category == "blood":
        return base + " For blood-health content, do not diagnose. Explain readings with context, repeat measurements, symptoms, and when medical guidance is needed."
    return base + " For weight-loss content, be realistic about mechanisms, adherence, side effects, cost, maintenance, and clinician guidance for medications or supplements."


def user_prompt(row: dict[str, str], youtube_context: str = "") -> str:
    category = clean_category(row)
    target = normalize(row.get("target_word_count") or "2400")
    title = normalize(row.get("title") or row.get("keyword"))
    category_rules = {
        "weight_loss": "For medication topics, explain realistic first-month signals, side effects, dose/doctor context, access/cost, plateau or maintenance problems, and who should be careful.",
        "cbd": "Explain what may be plausible, what remains uncertain, what to verify on labels, certificate of analysis, spectrum type, THC exposure, serving amount, interactions, and drug-testing concerns.",
        "blood": "Explain what the reading or marker can mean, what changes interpretation, what patterns matter, and when to seek medical guidance. Avoid diagnosis and self-treatment advice.",
    }
    yt_block = f"\n\nYouTube context:\n{youtube_context}\n" if youtube_context else ""
    return f"""
Write a complete CMS-ready Markdown article.

Required H1:
# {title}

Last updated line:
Last updated: {today_label()}

Target length: about {target} words. Specific and non-repetitive is more important than padding.

Blueprint:
{blueprint_summary(row)}{yt_block}

CMS media requirements:
- Include exactly one image placeholder in the article body using Markdown: ![Relevant description](image-placeholder.png)
- Do not add any YouTube iframe yourself. The system will insert a real YouTube iframe only when a valid YouTube API result exists.

Style requirements:
- Start with a search-intent hook, not a dictionary definition.
- Include a section called "The Short Version" within the first 300 words.
- Use the H2 plan, but make every section substantially different.
- Include one useful Markdown table tailored to the topic.
- Include a practical protocol/checklist section.
- Include FAQ using natural questions, not awkward keyword rewrites.
- Include an "Important Note" disclaimer near the end.
- Do not mention that you are following a blueprint.
- Do not include code fences.

Category-specific requirements:
{category_rules.get(category, category_rules['weight_loss'])}
""".strip()


def call_chat_completion(api_key: str, api_base: str, model: str, row: dict[str, str], temperature: float, timeout: int, youtube_context: str = "") -> str:
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt(clean_category(row))},
            {"role": "user", "content": user_prompt(row, youtube_context)},
        ],
    }
    req = urllib.request.Request(
        chat_completion_url(api_base),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"API HTTP {exc.code}: {body[:800]}") from exc
    parsed = json.loads(raw)
    try:
        return parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected API response: {raw[:800]}") from exc


def strip_code_fence(text: str) -> str:
    out = str(text or "").strip()
    out = re.sub(r"^```(?:markdown|md)?\s*", "", out, flags=re.I)
    out = re.sub(r"\s*```$", "", out)
    return out.strip()


def insert_after_intro(text: str, block: str) -> str:
    parts = text.split("\n\n")
    insert_at = min(3, max(1, len(parts)))
    parts.insert(insert_at, block)
    return "\n\n".join(parts)


def remove_placeholder_youtube(text: str) -> str:
    out = re.sub(r"\n?## Related Video\s*\n\s*<iframe[^>]+youtube-url-placeholder[^>]*></iframe>\s*", "\n", text, flags=re.I)
    out = re.sub(r"\n?<iframe[^>]+youtube-url-placeholder[^>]*></iframe>\s*", "\n", out, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def has_youtube(text: str) -> bool:
    return bool(re.search(r"youtube\.com/(?:embed/|watch\?v=)|youtu\.be/", text, flags=re.I))


def ensure_cms_media(text: str, title: str, selected_embed_url: str = "") -> str:
    out = remove_placeholder_youtube(text)
    if "image-placeholder.png" not in out:
        out = insert_after_intro(out, f"![{normalize(title)}](image-placeholder.png)")
    if selected_embed_url and not has_youtube(out):
        video_block = "## Related Video\n\n" + youtube_iframe(selected_embed_url)
        marker = "## Frequently Asked"
        idx = out.find(marker)
        if idx >= 0:
            out = out[:idx].rstrip() + "\n\n" + video_block + "\n\n" + out[idx:].lstrip()
        else:
            out = out.rstrip() + "\n\n" + video_block
    return out


def clean_markdown(markdown: str, row: dict[str, str], selected_youtube_url: str = "", selected_youtube_embed_url: str = "") -> str:
    text = strip_code_fence(markdown)
    title = normalize(row.get("title") or row.get("keyword"))
    if not re.search(r"^#\s+", text, flags=re.M):
        text = f"# {title}\n\nLast updated: {today_label()}\n\n" + text
    elif "Last updated:" not in text[:500]:
        text = re.sub(r"(^#\s+.*?$)", r"\1\n\nLast updated: " + today_label(), text, count=1, flags=re.M)
    text = ensure_cms_media(text, title, selected_youtube_embed_url)
    slug = slugify(row.get("keyword") or title)
    if not text.startswith("---"):
        text = front_matter(row, slug, "draft_ready", selected_youtube_url, selected_youtube_embed_url) + text
    return text.strip() + "\n"


def repeated_paragraph_count(markdown: str) -> int:
    paras = [re.sub(r"\s+", " ", p.strip().lower()) for p in markdown.split("\n\n")]
    paras = [p for p in paras if len(p) > 120 and not p.startswith("|")]
    seen: set[str] = set()
    repeated = 0
    for para in paras:
        key = para[:240]
        if key in seen:
            repeated += 1
        else:
            seen.add(key)
    return repeated


def quality_check(markdown: str, row: dict[str, str], selected_youtube_embed_url: str = "") -> tuple[str, bool, list[str]]:
    notes: list[str] = []
    wc = word_count(markdown)
    try:
        target = int(float(row.get("target_word_count") or 2200))
    except ValueError:
        target = 2200
    if wc < int(target * 0.65):
        notes.append(f"word_count_below_target:{wc}/{target}")
    if len(re.findall(r"^## ", markdown, flags=re.M)) < 5:
        notes.append("too_few_h2")
    for required in ["The Short Version", "Frequently Asked", "Important Note", "image-placeholder.png"]:
        if required not in markdown:
            notes.append(f"missing:{required}")
    if selected_youtube_embed_url and selected_youtube_embed_url not in markdown:
        notes.append("missing:selected_youtube_embed_url")
    if re.search(r"\b(guaranteed|miracle cure|cures?|detoxes?|burns fat instantly|clinically proven to cure)\b", markdown, flags=re.I):
        notes.append("unsafe_claim_language")
    if re.search(r"\b(this section should|open with|summarize what|blueprint|provided h2 plan)\b", markdown, flags=re.I):
        notes.append("instruction_leak")
    repeated = repeated_paragraph_count(markdown)
    if repeated:
        notes.append(f"repeated_paragraphs:{repeated}")
    status = "PASS" if not notes else "REVIEW"
    return status, status == "PASS", notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate AI Markdown articles from body_blueprint CSV.")
    parser.add_argument("input", help="Input body_blueprint_audit CSV")
    parser.add_argument("--articles-dir", default=DEFAULT_ARTICLES_DIR)
    parser.add_argument("--queue-output", default=DEFAULT_QUEUE_OUTPUT)
    parser.add_argument("--config", default="local_api_keys.json")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--api-base", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--youtube-api-key", default="")
    parser.add_argument("--use-youtube-context", action="store_true")
    parser.add_argument("--youtube-max-results", type=int, default=5)
    parser.add_argument("--temperature", type=float, default=float(os.getenv("AI_TEMPERATURE", "0.65")))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("AI_TIMEOUT", "180")))
    parser.add_argument("--sleep", type=float, default=float(os.getenv("AI_SLEEP", "0.5")))
    parser.add_argument("--max-articles", type=int, default=int(os.getenv("AI_MAX_ARTICLES", "0")), help="0 means all")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    if not config and args.config == "local_api_keys.json":
        config = load_config("scripts/local_api_keys.json")

    api_key = choose_value(args.api_key, ["GEMINI_API_KEY", "OPENAI_API_KEY"], config, ["GEMINI_API_KEY", "OPENAI_API_KEY"])
    api_base = choose_value(args.api_base, ["GEMINI_BASE_URL", "OPENAI_BASE_URL"], config, ["GEMINI_BASE_URL", "OPENAI_BASE_URL"], "https://api.openai.com/v1")
    model = choose_value(args.model, ["GEMINI_MODEL", "OPENAI_MODEL"], config, ["GEMINI_MODEL", "OPENAI_MODEL"], "gpt-4o-mini")
    youtube_api_key = choose_value(args.youtube_api_key, ["YOUTUBE_DATA_API_KEY"], config, ["YOUTUBE_DATA_API_KEY"])

    if not api_key:
        raise SystemExit("Missing API key. Set GEMINI_API_KEY/OPENAI_API_KEY, put it in local_api_keys.json, or pass --api-key.")

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    article_dir = Path(args.articles_dir)
    article_dir.mkdir(parents=True, exist_ok=True)
    source_rows = [row for row in read_csv(input_path) if row.get("publish_role", "primary_article") == "primary_article"]
    if args.max_articles and args.max_articles > 0:
        source_rows = source_rows[: args.max_articles]

    queue_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(source_rows, start=1):
        title = normalize(row.get("title") or row.get("keyword") or "Article")
        slug = slugify(row.get("keyword") or title)
        path = article_dir / f"{slug}.md"
        generation_status = "generated"
        error_message = ""
        yt_results: list[dict[str, str]] = []
        selected_youtube_url = ""
        selected_youtube_embed_url = ""

        if path.exists() and not args.overwrite:
            markdown = path.read_text(encoding="utf-8", errors="ignore")
            generation_status = "skipped_existing"
        else:
            try:
                print(f"[{idx}/{len(source_rows)}] Generating: {title}")
                youtube_context = ""
                if args.use_youtube_context and youtube_api_key:
                    query = f"{row.get('keyword', title)} {clean_category(row).replace('_', ' ')}"
                    yt_results = youtube_search(youtube_api_key, query, args.youtube_max_results)
                    youtube_context = youtube_context_text(yt_results)
                    selected_youtube_url = yt_results[0].get("url", "") if yt_results else ""
                    selected_youtube_embed_url = yt_results[0].get("embed_url", "") if yt_results else ""
                raw = call_chat_completion(api_key, api_base, model, row, args.temperature, args.timeout, youtube_context)
                markdown = clean_markdown(raw, row, selected_youtube_url, selected_youtube_embed_url)
                path.write_text(markdown, encoding="utf-8")
                time.sleep(args.sleep)
            except Exception as exc:  # noqa: BLE001
                markdown = ""
                generation_status = "error"
                error_message = str(exc)[:1200]

        if markdown:
            quality_status, publish_ready, notes = quality_check(markdown, row, selected_youtube_embed_url)
            wc = word_count(markdown)
        else:
            quality_status, publish_ready, notes, wc = "ERROR", False, [error_message], 0

        queue_rows.append({
            "category": clean_category(row),
            "keyword": row.get("keyword", ""),
            "title": title,
            "slug": slug,
            "markdown_path": str(path),
            "word_count": wc,
            "target_word_count": row.get("target_word_count", ""),
            "body_template": row.get("body_template", ""),
            "api_model": model,
            "generation_status": generation_status,
            "youtube_results_count": len(yt_results),
            "selected_youtube_url": selected_youtube_url,
            "selected_youtube_embed_url": selected_youtube_embed_url,
            "quality_status": quality_status,
            "publish_ready": "yes" if publish_ready else "review",
            "quality_notes": " | ".join(notes),
        })

    fields = ["category", "keyword", "title", "slug", "markdown_path", "word_count", "target_word_count", "body_template", "api_model", "generation_status", "youtube_results_count", "selected_youtube_url", "selected_youtube_embed_url", "quality_status", "publish_ready", "quality_notes"]
    write_csv(Path(args.queue_output), queue_rows, fields)
    pass_count = sum(1 for row in queue_rows if row["quality_status"] == "PASS")
    errors = sum(1 for row in queue_rows if row["quality_status"] == "ERROR")
    print(f"Model: {model}")
    print(f"API base: {api_base}")
    print(f"YouTube context: {'on' if args.use_youtube_context and youtube_api_key else 'off'}")
    print(f"Wrote {len(queue_rows)} queue rows to {args.queue_output}")
    print(f"Articles directory: {article_dir}")
    print(f"Quality: {pass_count} PASS · {len(queue_rows) - pass_count - errors} REVIEW · {errors} ERROR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
