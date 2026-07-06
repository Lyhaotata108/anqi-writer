#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Streamlit UI for the multi-category SEO pipeline."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import csv
import json
import os
import shutil
import subprocess
import sys
import time

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
WEB_RUN_DIR = OUTPUT_DIR / "web_runs"

CATEGORY_OPTIONS = {"Weight Loss": "weight_loss", "CBD": "cbd", "Blood": "blood"}
CATEGORY_LABELS = {value: label for label, value in CATEGORY_OPTIONS.items()}

SAMPLES = {
    "weight_loss": "ozempic for weight loss\nweight loss pills\npink salt recipe for weight loss\nmetabolism booster for women\n",
    "cbd": "best cbd gummies for pain\ncbd oil for anxiety\ncbd dosage for sleep\nfull spectrum vs broad spectrum cbd\n",
    "blood": "how to lower blood pressure naturally\nnormal blood sugar levels chart\na1c levels chart\nfoods to lower cholesterol\n",
}

st.set_page_config(page_title="Anqi Writer SEO Pipeline", page_icon="✍️", layout="wide")


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    WEB_RUN_DIR.mkdir(parents=True, exist_ok=True)


def safe_run_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(name or "")).strip("_") or "seo_run"


def widget_key(prefix: str, *parts: object) -> str:
    return prefix + "_" + safe_run_name("__".join(str(part) for part in parts))


def local_config() -> dict[str, str]:
    for path in [ROOT / "local_api_keys.json", ROOT / "scripts" / "local_api_keys.json"]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items() if v is not None}
    return {}


def cfg_value(config: dict[str, str], names: list[str], default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "") or config.get(name, "")
        if value and not value.startswith("paste-your-"):
            return value
    return default


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_csv_df(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def write_csv_rows(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_csv_file(target: Path, source: Path, batch_id: str = "") -> int:
    rows = read_csv_rows(source)
    if not rows:
        return 0
    source_fields = list(rows[0].keys())
    if batch_id:
        for row in rows:
            row["batch_id"] = batch_id
        fields = ["batch_id"] + [field for field in source_fields if field != "batch_id"]
    else:
        fields = source_fields

    if target.exists():
        existing_rows = read_csv_rows(target)
        if existing_rows:
            fields = list(existing_rows[0].keys())
            for field in rows[0].keys():
                if field not in fields:
                    fields.append(field)
            rows = existing_rows + rows

    write_csv_rows(target, rows, fields)
    return len(rows)


def append_generated_subjects(registry_path: Path, publish_queue: Path, batch_id: str) -> int:
    rows = read_csv_rows(publish_queue)
    if not rows:
        return 0
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_csv_rows(registry_path)
    seen = {(row.get("category", "").lower(), row.get("slug", "").lower()) for row in existing}
    new_rows: list[dict[str, object]] = []
    for row in rows:
        key = (row.get("category", "").lower(), row.get("slug", "").lower())
        if key in seen:
            continue
        seen.add(key)
        new_rows.append({
            "batch_id": batch_id,
            "category": row.get("category", ""),
            "keyword": row.get("keyword", ""),
            "title": row.get("title", ""),
            "slug": row.get("slug", ""),
            "quality_status": row.get("quality_status", ""),
            "publish_ready": row.get("publish_ready", ""),
        })
    if not new_rows:
        return 0
    fields = ["batch_id", "category", "keyword", "title", "slug", "quality_status", "publish_ready"]
    write_csv_rows(registry_path, existing + new_rows, fields)
    return len(new_rows)


def read_text_keywords(text: str) -> list[str]:
    out, seen = [], set()
    for line in str(text or "").splitlines():
        item = line.strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def read_uploaded_keywords(uploaded_file) -> list[str]:
    if uploaded_file is None:
        return []
    raw = uploaded_file.getvalue().decode("utf-8-sig", errors="ignore")
    if uploaded_file.name.lower().endswith(".csv"):
        reader = csv.DictReader(raw.splitlines())
        if reader.fieldnames:
            fields = {f.lower(): f for f in reader.fieldnames}
            key_field = fields.get("keyword") or fields.get("primary_keyword") or reader.fieldnames[0]
            return [str(row.get(key_field, "")).strip() for row in reader if str(row.get(key_field, "")).strip()]
    return read_text_keywords(raw)


def merge_keywords(*groups: list[str]) -> list[str]:
    out, seen = [], set()
    for group in groups:
        for kw in group:
            key = kw.lower().strip()
            if key and key not in seen:
                seen.add(key)
                out.append(kw)
    return out


def chunk_keywords(keywords: list[str], batch_size: int) -> list[list[str]]:
    if batch_size <= 0:
        return [keywords]
    return [keywords[i:i + batch_size] for i in range(0, len(keywords), batch_size)]


def run_command(args: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(args, cwd=str(ROOT), text=True, capture_output=True)
    output = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
    return proc.returncode == 0, output.strip()


def cleanup_history(current_run_name: str, keep_runs: int = 8, older_than_days: int = 0) -> list[str]:
    if not WEB_RUN_DIR.exists():
        return []
    current_safe = safe_run_name(current_run_name)
    candidates = [path for path in WEB_RUN_DIR.iterdir() if path.is_dir() and path.name != current_safe]
    candidates.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    protected = {path.resolve() for path in candidates[: max(0, int(keep_runs or 0))]}
    now = time.time()
    deleted: list[str] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in protected:
            continue
        age_days = (now - path.stat().st_mtime) / 86400 if path.exists() else 999999
        delete_by_count = resolved not in protected
        delete_by_age = older_than_days > 0 and age_days >= older_than_days
        if delete_by_count or delete_by_age:
            try:
                shutil.rmtree(path)
                deleted.append(path.name)
            except Exception as exc:
                deleted.append(f"FAILED:{path.name}:{exc}")
    return deleted


def run_paths(run_name: str, category: str, batch_id: str = "") -> dict[str, Path]:
    category_dir = WEB_RUN_DIR / safe_run_name(run_name) / category
    run_dir = category_dir / "batches" / safe_run_name(batch_id) if batch_id else category_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        "run_dir": run_dir,
        "keyword_input": run_dir / "keywords.txt",
        "cluster_audit": run_dir / "keyword_cluster_audit.csv",
        "primary_queue": run_dir / "primary_article_queue.csv",
        "title_audit": run_dir / "title_intent_audit.csv",
        "body_blueprint": run_dir / "body_blueprint_audit.csv",
        "articles_dir": run_dir / "articles",
        "publish_queue": run_dir / "article_publish_queue.csv",
        "cms_results": run_dir / "cms_import_results.csv",
        "generated_subjects": category_dir / "generated_subjects.csv",
    }


def run_pipeline(
    keywords: list[str],
    run_name: str,
    category: str,
    use_ai: bool,
    use_youtube: bool,
    max_articles: int,
    overwrite: bool,
    cms_auto_import: bool = False,
    cms_settings: dict[str, int | bool] | None = None,
    batch_id: str = "",
) -> tuple[dict[str, Path], list[tuple[str, bool, str]]]:
    paths = run_paths(run_name, category, batch_id)
    paths["keyword_input"].write_text("\n".join(keywords) + "\n", encoding="utf-8")
    logs = []

    steps = [
        ("关键词聚类", [sys.executable, "scripts/keyword_cluster_engine.py", str(paths["keyword_input"]), "--category", category, "--audit-output", str(paths["cluster_audit"]), "--queue-output", str(paths["primary_queue"])]),
        ("标题生成", [sys.executable, "scripts/title_intent_audit.py", str(paths["primary_queue"]), "--category", category, "--output", str(paths["title_audit"])]),
        ("正文蓝图", [sys.executable, "scripts/body_blueprint_engine.py", str(paths["title_audit"]), "--output", str(paths["body_blueprint"])]),
    ]
    for name, cmd in steps:
        ok, output = run_command(cmd)
        logs.append((name, ok, output))
        if not ok:
            return paths, logs

    if use_ai:
        settings = cms_settings or {}
        cmd = [
            sys.executable, "scripts/ai_body_writer_engine.py", str(paths["body_blueprint"]),
            "--config", "local_api_keys.json",
            "--articles-dir", str(paths["articles_dir"]),
            "--queue-output", str(paths["publish_queue"]),
        ]
        if use_youtube:
            cmd.append("--use-youtube-context")
        if max_articles > 0:
            cmd.extend(["--max-articles", str(max_articles)])
        if overwrite:
            cmd.append("--overwrite")
        if cms_auto_import:
            cmd.extend(["--cms-import-after-each", "--cms-output", str(paths["cms_results"])])
            if settings.get("publish"):
                cmd.append("--cms-publish")
            if settings.get("only_publish_ready"):
                cmd.append("--cms-only-publish-ready")
            if int(settings.get("category_id", 0) or 0) > 0:
                cmd.extend(["--cms-category-id", str(int(settings.get("category_id", 0) or 0))])
        ok, output = run_command(cmd)
        label = "Gemini完整正文 + HTML预览"
        if cms_auto_import:
            label += " + 单篇即时CMS导入"
        logs.append((label, ok, output))
    else:
        ok, output = run_command([sys.executable, "scripts/body_writer_engine.py", str(paths["body_blueprint"]), "--articles-dir", str(paths["articles_dir"]), "--queue-output", str(paths["publish_queue"])])
        logs.append(("模板完整正文", ok, output))
    return paths, logs


def run_cms_import(paths: dict[str, Path], settings: dict[str, int | bool]) -> tuple[bool, str]:
    if not paths["publish_queue"].exists():
        return False, "发布队列 article_publish_queue.csv 不存在，无法导入 CMS。"
    cmd = [sys.executable, "scripts/cms_importer.py", str(paths["publish_queue"]), "--config", "local_api_keys.json", "--output", str(paths["cms_results"])]
    if int(settings.get("max_articles", 0) or 0) > 0:
        cmd.extend(["--max-articles", str(int(settings.get("max_articles", 0) or 0))])
    if int(settings.get("category_id", 0) or 0) > 0:
        cmd.extend(["--category-id", str(int(settings.get("category_id", 0) or 0))])
    if settings.get("only_publish_ready"):
        cmd.append("--only-publish-ready")
    if settings.get("publish"):
        cmd.append("--publish")
    return run_command(cmd)


def aggregate_batch_outputs(root_paths: dict[str, Path], batch_paths: dict[str, Path], batch_id: str) -> None:
    append_csv_file(root_paths["cluster_audit"], batch_paths["cluster_audit"], batch_id)
    append_csv_file(root_paths["primary_queue"], batch_paths["primary_queue"], batch_id)
    append_csv_file(root_paths["title_audit"], batch_paths["title_audit"], batch_id)
    append_csv_file(root_paths["body_blueprint"], batch_paths["body_blueprint"], batch_id)
    append_csv_file(root_paths["publish_queue"], batch_paths["publish_queue"], batch_id)
    append_csv_file(root_paths["cms_results"], batch_paths["cms_results"], batch_id)
    append_generated_subjects(root_paths["generated_subjects"], batch_paths["publish_queue"], batch_id)


def run_category_task(
    category: str,
    keywords: list[str],
    run_name: str,
    use_ai: bool,
    use_youtube: bool,
    max_articles: int,
    overwrite: bool,
    cms_auto_import: bool,
    cms_settings: dict[str, int | bool],
    keyword_batch_size: int,
    max_batches: int,
) -> tuple[str, dict[str, Path], list[tuple[str, bool, str]]]:
    root_paths = run_paths(run_name, category)
    root_paths["keyword_input"].write_text("\n".join(keywords) + "\n", encoding="utf-8")
    for key in ["cluster_audit", "primary_queue", "title_audit", "body_blueprint", "publish_queue", "cms_results", "generated_subjects"]:
        if root_paths[key].exists():
            root_paths[key].unlink()

    batches = chunk_keywords(keywords, int(keyword_batch_size or 0))
    if max_batches and max_batches > 0:
        batches = batches[:max_batches]

    all_logs: list[tuple[str, bool, str]] = []
    category_max_articles = int(max_articles)
    if cms_auto_import and int(cms_settings.get("max_articles", 0) or 0) > 0:
        cap = int(cms_settings.get("max_articles", 0) or 0)
        category_max_articles = min(category_max_articles, cap) if category_max_articles > 0 else cap

    for index, batch_keywords in enumerate(batches, start=1):
        batch_id = f"batch_{index:04d}"
        start_no = (index - 1) * int(keyword_batch_size or len(keywords)) + 1
        end_no = start_no + len(batch_keywords) - 1
        all_logs.append((f"{batch_id} · 准备关键词", True, f"{CATEGORY_LABELS.get(category, category)} {batch_id}: keywords {start_no}-{end_no} / total {len(keywords)}"))

        batch_paths, logs = run_pipeline(
            keywords=batch_keywords,
            run_name=run_name,
            category=category,
            use_ai=use_ai,
            use_youtube=use_youtube,
            max_articles=category_max_articles,
            overwrite=overwrite,
            cms_auto_import=cms_auto_import,
            cms_settings=cms_settings,
            batch_id=batch_id,
        )

        if cms_auto_import and not use_ai:
            ok, output = run_cms_import(batch_paths, cms_settings)
            label = "CMS真实发布" if cms_settings.get("publish") else "CMS导入 dry-run"
            logs.append((label, ok, output))

        aggregate_batch_outputs(root_paths, batch_paths, batch_id)
        batch_ok = all(ok for _, ok, _ in logs)
        all_logs.extend([(f"{batch_id} · {step}", ok, output) for step, ok, output in logs])
        if not batch_ok:
            all_logs.append((f"{batch_id} · 停止后续批次", False, "当前批次失败，为避免连续错误，已停止该分类后续批次。"))
            break

    return category, root_paths, all_logs


def csv_download(path: Path, label: str) -> None:
    if path.exists():
        st.download_button(
            label,
            path.read_bytes(),
            file_name=path.name,
            mime="text/csv",
            use_container_width=True,
            key=widget_key("download_csv", path),
        )


def show_table(title: str, path: Path, cols: list[str] | None = None) -> None:
    df = read_csv_df(path)
    if df.empty:
        st.info(f"暂时没有生成 {title}。")
        return
    st.subheader(title)
    st.caption(f"{path} · {len(df)} rows")
    if cols:
        visible = [c for c in cols if c in df.columns]
        if visible:
            st.dataframe(df[visible].head(200), use_container_width=True, height=420)
            with st.expander("查看全部字段"):
                st.dataframe(df.head(200), use_container_width=True, height=420)
            return
    st.dataframe(df.head(200), use_container_width=True, height=420)


def show_metrics(paths: dict[str, Path]) -> None:
    cluster = read_csv_df(paths["cluster_audit"])
    queue = read_csv_df(paths["primary_queue"])
    publish = read_csv_df(paths["publish_queue"])
    cms = read_csv_df(paths["cms_results"])
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("聚类关键词行", len(cluster) if not cluster.empty else "-")
    c2.metric("主文章数", len(queue) if not queue.empty else "-")
    c3.metric("Markdown正文", len(publish) if not publish.empty else "-")
    if not publish.empty and "word_count" in publish.columns:
        c4.metric("平均正文字数", int(pd.to_numeric(publish["word_count"], errors="coerce").fillna(0).mean()))
    else:
        c4.metric("平均正文字数", "-")
    c5.metric("CMS导入记录", len(cms) if not cms.empty else "-")
    if not publish.empty and "quality_status" in publish.columns:
        st.markdown("**正文质量状态**")
        st.bar_chart(publish["quality_status"].value_counts())
    if not cms.empty and "status" in cms.columns:
        st.markdown("**CMS导入状态**")
        st.bar_chart(cms["status"].value_counts())


def show_article_preview(paths: dict[str, Path]) -> None:
    publish = read_csv_df(paths["publish_queue"])
    if publish.empty or "markdown_path" not in publish.columns:
        st.info("暂时没有生成 Markdown 正文。")
        return
    cols = [c for c in ["batch_id", "keyword", "title", "word_count", "api_model", "generation_status", "youtube_results_count", "quality_status", "publish_ready", "markdown_path", "preview_html_path"] if c in publish.columns]
    st.dataframe(publish[cols], use_container_width=True, height=300)
    article_options = publish["markdown_path"].astype(str).tolist()
    selected = st.selectbox("选择文章", article_options, key=widget_key("article_select", paths["run_dir"]))
    md_path = Path(selected)
    row = publish[publish["markdown_path"].astype(str) == selected].iloc[0].to_dict()
    html_path = Path(str(row.get("preview_html_path", "")))

    preview_tab, markdown_tab = st.tabs(["HTML 预览", "Markdown 源码"])
    with preview_tab:
        if html_path.exists():
            html_text = html_path.read_text(encoding="utf-8", errors="ignore")
            st.download_button(
                "下载当前 HTML 预览",
                html_text.encode("utf-8"),
                file_name=html_path.name,
                mime="text/html",
                use_container_width=True,
                key=widget_key("download_html", html_path),
            )
            components.html(html_text, height=900, scrolling=True)
        else:
            st.warning("没有找到 HTML 预览文件。请用最新版本重新生成文章。")
    with markdown_tab:
        if md_path.exists():
            text = md_path.read_text(encoding="utf-8", errors="ignore")
            st.download_button(
                "下载当前 Markdown",
                text.encode("utf-8"),
                file_name=md_path.name,
                mime="text/markdown",
                use_container_width=True,
                key=widget_key("download_markdown", md_path),
            )
            st.markdown(text[:30000])
        else:
            st.warning("没有找到 Markdown 文件。")


ensure_dirs()
config = local_config()
has_gemini = bool(cfg_value(config, ["GEMINI_API_KEY", "OPENAI_API_KEY"]))
has_youtube = bool(cfg_value(config, ["YOUTUBE_DATA_API_KEY"]))
has_cms = True
model_name = cfg_value(config, ["GEMINI_MODEL", "OPENAI_MODEL"], "gemini-3-flash-preview")
base_url = cfg_value(config, ["GEMINI_BASE_URL", "OPENAI_BASE_URL"], "")

st.title("Anqi Writer SEO Pipeline")
st.caption("支持 Weight Loss / CBD / Blood 三分类并发运行，并支持大词库按批次流水线处理：每批聚类 → 生成正文 → 每篇立即导入 CMS → 下一批。")

with st.sidebar:
    st.header("运行设置")
    selected_labels = st.multiselect("要运行的分类", list(CATEGORY_OPTIONS.keys()), default=list(CATEGORY_OPTIONS.keys()))
    selected_categories = [CATEGORY_OPTIONS[label] for label in selected_labels]
    run_name = st.text_input("运行名称", "multi_" + time.strftime("%Y%m%d_%H%M%S"))
    st.caption(f"本地配置：Gemini {'已检测' if has_gemini else '未检测'} · YouTube {'已检测' if has_youtube else '未检测'} · CMS 导入默认可用")
    if base_url or model_name:
        st.caption(f"模型：{model_name} · Base：{base_url or 'default'}")
    use_ai = st.checkbox("使用 Gemini 中转 API 生成爆款正文", value=True)
    if use_ai and not has_gemini:
        st.warning("没有检测到 Gemini Key：请确认 local_api_keys.json 在项目根目录，且字段名是 GEMINI_API_KEY。")
    use_youtube = st.checkbox("使用 YouTube API 补充爆款角度", value=has_youtube)
    max_articles = st.number_input("每批每个分类最多生成几篇，0 = 全部", min_value=0, value=3, step=1)
    overwrite = st.checkbox("覆盖已存在 Markdown（AI 模式建议保持开启）", value=True)

    st.divider()
    st.subheader("大词库分批")
    keyword_batch_size = st.number_input("每批最多处理关键词数", min_value=100, value=1000, step=100)
    max_batches = st.number_input("每个分类最多跑几个批次，0 = 跑完整个词库", min_value=0, value=0, step=1)
    st.caption("例如 8 万词、每批 1000，就是约 80 批；每批会先完成聚类/标题/蓝图，然后马上生成并导入，不会等 8 万词全部处理完。")

    st.divider()
    st.subheader("CMS 导入")
    cms_auto_import = st.checkbox("生成一篇就导入一篇 CMS", value=False)
    cms_publish = st.checkbox("真正发布到 CMS（关闭则只 dry-run）", value=False, disabled=not cms_auto_import)
    cms_only_ready = st.checkbox("只导入 publish_ready = yes 的文章", value=True, disabled=not cms_auto_import)
    cms_max_articles = st.number_input("CMS 每批每个分类最多导入几篇，0 = 跟随生成数量", min_value=0, value=0, step=1, disabled=not cms_auto_import)
    cms_category_id = st.number_input("覆盖 category_id，0 = 使用固定映射", min_value=0, value=0, step=1, disabled=not cms_auto_import)
    st.caption("三分类会并发运行；每个分类内部按批次流水线执行，并保持生成第 1 篇 → 立即 dry-run/发布第 1 篇 → 再生成第 2 篇。")
    if cms_auto_import and cms_publish:
        st.warning("已开启真实发布。并发发布会同时向 CMS 发起请求，建议先每类 1–3 篇测试。")

    st.divider()
    st.subheader("历史文件清理")
    auto_cleanup = st.checkbox("运行前自动清理历史文件", value=True)
    cleanup_keep_runs = st.number_input("保留最近几个运行目录", min_value=0, value=8, step=1, disabled=not auto_cleanup)
    cleanup_older_days = st.number_input("额外删除多少天前的历史目录，0 = 不按天", min_value=0, value=0, step=1, disabled=not auto_cleanup)
    st.caption("只清理 output/web_runs 里的旧运行目录，不会删除当前运行。")

    start = st.button("开始运行", type="primary", use_container_width=True)

if not selected_categories:
    st.warning("请至少选择一个分类。")
    st.stop()

st.markdown("### 关键词输入")
category_keywords: dict[str, list[str]] = {}
input_tabs = st.tabs([CATEGORY_LABELS[c] for c in selected_categories])
for tab, category in zip(input_tabs, selected_categories):
    with tab:
        uploaded = st.file_uploader(f"上传 {CATEGORY_LABELS[category]} 关键词 TXT / CSV", type=["txt", "csv"], key=f"upload_{category}")
        text = st.text_area(f"粘贴 {CATEGORY_LABELS[category]} 关键词", value=SAMPLES[category], height=180, key=f"textarea_{category}")
        merged = merge_keywords(read_uploaded_keywords(uploaded), read_text_keywords(text))
        category_keywords[category] = merged
        planned_batches = len(chunk_keywords(merged, int(keyword_batch_size or 0))) if merged else 0
        if max_batches and max_batches > 0:
            planned_batches = min(planned_batches, int(max_batches))
        st.markdown(f"当前分类：**{CATEGORY_LABELS[category]}** · 待处理关键词：**{len(merged)}** 个 · 计划批次：**{planned_batches}**")

if start:
    runnable = {category: kws for category, kws in category_keywords.items() if kws}
    if not runnable:
        st.error("请至少给一个分类上传或粘贴关键词。")
    else:
        paths_by_category: dict[str, dict[str, str]] = {}
        cms_settings = {
            "publish": bool(cms_publish),
            "only_publish_ready": bool(cms_only_ready),
            "max_articles": int(cms_max_articles),
            "category_id": int(cms_category_id),
        }
        if auto_cleanup:
            deleted = cleanup_history(run_name, int(cleanup_keep_runs), int(cleanup_older_days))
            if deleted:
                st.info("已清理历史运行目录：" + ", ".join(deleted[:12]) + (" ..." if len(deleted) > 12 else ""))

        with st.status("正在并发分批运行多分类 SEO Pipeline...", expanded=True) as status:
            all_ok = True
            finished_count = 0
            total_count = len(runnable)
            max_workers = min(3, total_count)
            future_map = {}

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for category, keywords in runnable.items():
                    future = executor.submit(
                        run_category_task,
                        category,
                        keywords,
                        run_name,
                        use_ai,
                        use_youtube,
                        int(max_articles),
                        bool(overwrite),
                        bool(cms_auto_import),
                        cms_settings,
                        int(keyword_batch_size),
                        int(max_batches),
                    )
                    future_map[future] = category

                for future in as_completed(future_map):
                    category = future_map[future]
                    st.markdown(f"#### {CATEGORY_LABELS[category]}")
                    try:
                        category_name, paths, logs = future.result()
                        paths_by_category[category_name] = {k: str(v) for k, v in paths.items()}
                        for step, ok, output in logs:
                            all_ok = all_ok and ok
                            (st.success if ok else st.error)(f"{CATEGORY_LABELS[category_name]} · {step}")
                            if output:
                                st.code(output)
                    except Exception as exc:
                        all_ok = False
                        st.error(f"{CATEGORY_LABELS[category]} · 运行失败")
                        st.code(str(exc))

                    finished_count += 1
                    status.update(label=f"并发分批运行中... 已完成分类 {finished_count}/{total_count}", state="running")

            ordered_paths: dict[str, dict[str, str]] = {}
            for category in selected_categories:
                if category in paths_by_category:
                    ordered_paths[category] = paths_by_category[category]
            paths_by_category = ordered_paths
            status.update(label="运行完成" if all_ok else "部分分类运行失败", state="complete" if all_ok else "error")
        st.session_state["last_runs"] = paths_by_category

if "last_runs" not in st.session_state:
    st.info("填写一个或多个分类的关键词，然后点击左侧“开始运行”。")
else:
    paths_by_category = st.session_state["last_runs"]
    st.divider()
    st.subheader("多分类运行汇总")
    rows = []
    for category, raw_paths in paths_by_category.items():
        paths = {k: Path(v) for k, v in raw_paths.items()}
        publish = read_csv_df(paths["publish_queue"])
        cms = read_csv_df(paths["cms_results"])
        subjects = read_csv_df(paths["generated_subjects"])
        rows.append({
            "category": CATEGORY_LABELS.get(category, category),
            "markdown_articles": len(publish) if not publish.empty else 0,
            "cms_rows": len(cms) if not cms.empty else 0,
            "generated_subjects": len(subjects) if not subjects.empty else 0,
            "run_dir": str(paths["run_dir"]),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    result_tabs = st.tabs([CATEGORY_LABELS.get(c, c) for c in paths_by_category.keys()])
    for tab, (category, raw_paths) in zip(result_tabs, paths_by_category.items()):
        with tab:
            paths = {k: Path(v) for k, v in raw_paths.items()}
            st.markdown(f"## {CATEGORY_LABELS.get(category, category)}")
            show_metrics(paths)
            d1, d2, d3, d4, d5, d6, d7 = st.columns(7)
            with d1: csv_download(paths["cluster_audit"], "下载聚类审计 CSV")
            with d2: csv_download(paths["primary_queue"], "下载主文章队列 CSV")
            with d3: csv_download(paths["title_audit"], "下载标题审计 CSV")
            with d4: csv_download(paths["body_blueprint"], "下载正文蓝图 CSV")
            with d5: csv_download(paths["publish_queue"], "下载发布队列 CSV")
            with d6: csv_download(paths["cms_results"], "下载 CMS 结果 CSV")
            with d7: csv_download(paths["generated_subjects"], "下载已生成主题 CSV")
            tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["关键词聚类", "主文章队列", "标题审计", "正文蓝图", "完整正文 / HTML预览", "CMS导入结果", "已生成主题"])
            with tab1: show_table("关键词聚类审计", paths["cluster_audit"], ["batch_id", "category", "keyword", "publish_role", "merge_usage", "primary_keyword", "cluster_size", "keyword_score", "score_reason"])
            with tab2: show_table("主文章队列", paths["primary_queue"], ["batch_id", "category", "primary_keyword", "cluster_size", "canonical_subject", "intent_family", "secondary_keywords", "faq_keywords", "h2_keywords"])
            with tab3: show_table("标题审计", paths["title_audit"], ["batch_id", "category", "keyword", "title", "title_shape", "ctr_angle", "title_score", "secondary_keywords", "faq_keywords", "h2_keywords"])
            with tab4: show_table("正文蓝图", paths["body_blueprint"], ["batch_id", "category", "keyword", "title", "body_template", "target_word_count", "word_count_range", "h2_1", "h2_2", "h2_3", "faq_keywords", "content_warnings"])
            with tab5: show_article_preview(paths)
            with tab6: show_table("CMS 导入结果", paths["cms_results"], ["batch_id", "title", "status", "cms_id", "message"])
            with tab7: show_table("已生成主题", paths["generated_subjects"], ["batch_id", "category", "keyword", "title", "slug", "quality_status", "publish_ready"])
