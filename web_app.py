#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Streamlit UI for the multi-category SEO pipeline."""

from __future__ import annotations
from pathlib import Path
import csv
import json
import os
import subprocess
import sys
import time

import pandas as pd
import streamlit as st

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


def read_csv_df(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


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


def run_command(args: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(args, cwd=str(ROOT), text=True, capture_output=True)
    output = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
    return proc.returncode == 0, output.strip()


def run_paths(run_name: str, category: str) -> dict[str, Path]:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in run_name).strip("_") or "seo_run"
    run_dir = WEB_RUN_DIR / safe / category
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
    }


def run_pipeline(keywords: list[str], run_name: str, category: str, use_ai: bool, use_youtube: bool, max_articles: int, overwrite: bool) -> tuple[dict[str, Path], list[tuple[str, bool, str]]]:
    paths = run_paths(run_name, category)
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
        cmd = [sys.executable, "scripts/ai_body_writer_engine.py", str(paths["body_blueprint"]), "--config", "local_api_keys.json", "--articles-dir", str(paths["articles_dir"]), "--queue-output", str(paths["publish_queue"])]
        if use_youtube:
            cmd.append("--use-youtube-context")
        if max_articles > 0:
            cmd.extend(["--max-articles", str(max_articles)])
        if overwrite:
            cmd.append("--overwrite")
        ok, output = run_command(cmd)
        logs.append(("Gemini完整正文", ok, output))
    else:
        ok, output = run_command([sys.executable, "scripts/body_writer_engine.py", str(paths["body_blueprint"]), "--articles-dir", str(paths["articles_dir"]), "--queue-output", str(paths["publish_queue"])])
        logs.append(("模板完整正文", ok, output))
    return paths, logs


def csv_download(path: Path, label: str) -> None:
    if path.exists():
        st.download_button(label, path.read_bytes(), file_name=path.name, mime="text/csv", use_container_width=True)


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
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("原始关键词", len(cluster) if not cluster.empty else "-")
    c2.metric("主文章数", len(queue) if not queue.empty else "-")
    c3.metric("Markdown正文", len(publish) if not publish.empty else "-")
    if not publish.empty and "word_count" in publish.columns:
        c4.metric("平均正文字数", int(pd.to_numeric(publish["word_count"], errors="coerce").fillna(0).mean()))
    else:
        c4.metric("平均正文字数", "-")
    if not publish.empty and "quality_status" in publish.columns:
        st.markdown("**正文质量状态**")
        st.bar_chart(publish["quality_status"].value_counts())


def show_article_preview(paths: dict[str, Path]) -> None:
    publish = read_csv_df(paths["publish_queue"])
    if publish.empty or "markdown_path" not in publish.columns:
        st.info("暂时没有生成 Markdown 正文。")
        return
    cols = [c for c in ["keyword", "title", "word_count", "api_model", "generation_status", "youtube_results_count", "quality_status", "publish_ready", "markdown_path"] if c in publish.columns]
    st.dataframe(publish[cols], use_container_width=True, height=300)
    selected = st.selectbox("预览 Markdown 正文", publish["markdown_path"].astype(str).tolist())
    path = Path(selected)
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="ignore")
        st.download_button("下载当前 Markdown", text.encode("utf-8"), file_name=path.name, mime="text/markdown", use_container_width=True)
        st.markdown(text[:30000])


ensure_dirs()
config = local_config()
has_gemini = bool(cfg_value(config, ["GEMINI_API_KEY", "OPENAI_API_KEY"]))
has_youtube = bool(cfg_value(config, ["YOUTUBE_DATA_API_KEY"]))
model_name = cfg_value(config, ["GEMINI_MODEL", "OPENAI_MODEL"], "gemini-3-flash-preview")
base_url = cfg_value(config, ["GEMINI_BASE_URL", "OPENAI_BASE_URL"], "")

st.title("Anqi Writer SEO Pipeline")
st.caption("支持 Weight Loss / CBD / Blood 同时跑：关键词聚类 → 标题 → 正文蓝图 → Gemini/模板 Markdown 正文。")

with st.sidebar:
    st.header("运行设置")
    selected_labels = st.multiselect("要运行的分类", list(CATEGORY_OPTIONS.keys()), default=list(CATEGORY_OPTIONS.keys()))
    selected_categories = [CATEGORY_OPTIONS[label] for label in selected_labels]
    run_name = st.text_input("运行名称", "multi_" + time.strftime("%Y%m%d_%H%M%S"))
    st.caption(f"本地配置：Gemini {'已检测' if has_gemini else '未检测'} · YouTube {'已检测' if has_youtube else '未检测'}")
    if base_url or model_name:
        st.caption(f"模型：{model_name} · Base：{base_url or 'default'}")
    use_ai = st.checkbox("使用 Gemini 中转 API 生成爆款正文", value=True)
    if use_ai and not has_gemini:
        st.warning("没有检测到 Gemini Key：请确认 local_api_keys.json 在项目根目录，且字段名是 GEMINI_API_KEY。")
    use_youtube = st.checkbox("使用 YouTube API 补充爆款角度", value=has_youtube)
    max_articles = st.number_input("每个分类最多生成几篇，0 = 全部", min_value=0, value=3, step=1)
    overwrite = st.checkbox("覆盖已存在 Markdown（AI 模式建议保持开启）", value=True)
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
        st.markdown(f"当前分类：**{CATEGORY_LABELS[category]}** · 待处理关键词：**{len(merged)}** 个")

if start:
    runnable = {category: kws for category, kws in category_keywords.items() if kws}
    if not runnable:
        st.error("请至少给一个分类上传或粘贴关键词。")
    else:
        paths_by_category: dict[str, dict[str, str]] = {}
        with st.status("正在运行多分类 SEO Pipeline...", expanded=True) as status:
            all_ok = True
            for category, keywords in runnable.items():
                st.markdown(f"#### {CATEGORY_LABELS[category]}")
                paths, logs = run_pipeline(keywords, run_name, category, use_ai, use_youtube, int(max_articles), bool(overwrite))
                paths_by_category[category] = {k: str(v) for k, v in paths.items()}
                for step, ok, output in logs:
                    all_ok = all_ok and ok
                    (st.success if ok else st.error)(f"{CATEGORY_LABELS[category]} · {step}")
                    if output:
                        st.code(output)
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
        rows.append({"category": CATEGORY_LABELS.get(category, category), "markdown_articles": len(publish) if not publish.empty else 0, "run_dir": str(paths["run_dir"])})
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    result_tabs = st.tabs([CATEGORY_LABELS.get(c, c) for c in paths_by_category.keys()])
    for tab, (category, raw_paths) in zip(result_tabs, paths_by_category.items()):
        with tab:
            paths = {k: Path(v) for k, v in raw_paths.items()}
            st.markdown(f"## {CATEGORY_LABELS.get(category, category)}")
            show_metrics(paths)
            d1, d2, d3, d4, d5 = st.columns(5)
            with d1: csv_download(paths["cluster_audit"], "下载聚类审计 CSV")
            with d2: csv_download(paths["primary_queue"], "下载主文章队列 CSV")
            with d3: csv_download(paths["title_audit"], "下载标题审计 CSV")
            with d4: csv_download(paths["body_blueprint"], "下载正文蓝图 CSV")
            with d5: csv_download(paths["publish_queue"], "下载发布队列 CSV")
            tab1, tab2, tab3, tab4, tab5 = st.tabs(["关键词聚类", "主文章队列", "标题审计", "正文蓝图", "完整正文"])
            with tab1: show_table("关键词聚类审计", paths["cluster_audit"], ["category", "keyword", "publish_role", "merge_usage", "primary_keyword", "cluster_size", "keyword_score", "score_reason"])
            with tab2: show_table("主文章队列", paths["primary_queue"], ["category", "primary_keyword", "cluster_size", "canonical_subject", "intent_family", "secondary_keywords", "faq_keywords", "h2_keywords"])
            with tab3: show_table("标题审计", paths["title_audit"], ["category", "keyword", "title", "title_shape", "ctr_angle", "title_score", "secondary_keywords", "faq_keywords", "h2_keywords"])
            with tab4: show_table("正文蓝图", paths["body_blueprint"], ["category", "keyword", "title", "body_template", "target_word_count", "word_count_range", "h2_1", "h2_2", "h2_3", "faq_keywords", "content_warnings"])
            with tab5: show_article_preview(paths)
