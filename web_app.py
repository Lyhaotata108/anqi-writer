#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web UI for the keyword -> title -> body blueprint pipeline.

Run locally:
    streamlit run web_app.py
"""

from __future__ import annotations
from pathlib import Path
import csv
import subprocess
import sys
import time

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
WEB_RUN_DIR = OUTPUT_DIR / "web_runs"
DATA_DIR = ROOT / "data"


st.set_page_config(
    page_title="Anqi Writer SEO Pipeline",
    page_icon="✍️",
    layout="wide",
)


CUSTOM_CSS = """
<style>
.block-container {padding-top: 1.5rem; padding-bottom: 3rem;}
.metric-card {border: 1px solid #e5e7eb; border-radius: 14px; padding: 14px 16px; background: #ffffff;}
.small-note {font-size: 13px; color: #6b7280;}
.step-box {border-left: 4px solid #111827; padding: 10px 14px; background: #f9fafb; border-radius: 10px;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    WEB_RUN_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def read_text_keywords(text: str) -> list[str]:
    out = []
    seen = set()
    for line in str(text or "").splitlines():
        item = line.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def read_uploaded_keywords(uploaded_file) -> list[str]:
    if uploaded_file is None:
        return []
    raw = uploaded_file.getvalue().decode("utf-8-sig", errors="ignore")
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        lines = raw.splitlines()
        if not lines:
            return []
        reader = csv.DictReader(lines)
        if reader.fieldnames:
            fields = {f.lower(): f for f in reader.fieldnames}
            key_field = fields.get("keyword") or fields.get("primary_keyword") or reader.fieldnames[0]
            return [str(row.get(key_field, "")).strip() for row in reader if str(row.get(key_field, "")).strip()]
    return read_text_keywords(raw)


def run_command(args: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        args,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    output = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
    return proc.returncode == 0, output.strip()


def make_run_paths(run_name: str) -> dict[str, Path]:
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in run_name).strip("_") or "seo_run"
    run_dir = WEB_RUN_DIR / safe_name
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        "run_dir": run_dir,
        "keyword_input": run_dir / "keywords.txt",
        "cluster_audit": run_dir / "keyword_cluster_audit.csv",
        "primary_queue": run_dir / "primary_article_queue.csv",
        "title_audit": run_dir / "title_intent_audit.csv",
        "body_blueprint": run_dir / "body_blueprint_audit.csv",
    }


def run_pipeline(keywords: list[str], run_name: str, run_cluster: bool, run_titles: bool, run_body: bool) -> tuple[dict[str, Path], list[tuple[str, bool, str]]]:
    paths = make_run_paths(run_name)
    paths["keyword_input"].write_text("\n".join(keywords) + "\n", encoding="utf-8")
    logs: list[tuple[str, bool, str]] = []

    if run_cluster:
        ok, output = run_command([
            sys.executable,
            "scripts/keyword_cluster_engine.py",
            str(paths["keyword_input"]),
            "--audit-output", str(paths["cluster_audit"]),
            "--queue-output", str(paths["primary_queue"]),
        ])
        logs.append(("关键词聚类", ok, output))
        if not ok:
            return paths, logs

    title_input = paths["primary_queue"] if paths["primary_queue"].exists() else paths["keyword_input"]
    if run_titles:
        ok, output = run_command([
            sys.executable,
            "scripts/title_intent_audit.py",
            str(title_input),
            "--output", str(paths["title_audit"]),
        ])
        logs.append(("标题生成", ok, output))
        if not ok:
            return paths, logs

    if run_body:
        if not paths["title_audit"].exists():
            logs.append(("正文蓝图", False, "标题审计文件不存在，无法生成正文蓝图。"))
            return paths, logs
        ok, output = run_command([
            sys.executable,
            "scripts/body_blueprint_engine.py",
            str(paths["title_audit"]),
            "--output", str(paths["body_blueprint"]),
        ])
        logs.append(("正文蓝图", ok, output))

    return paths, logs


def csv_download_button(path: Path, label: str) -> None:
    if path.exists():
        st.download_button(
            label,
            data=path.read_bytes(),
            file_name=path.name,
            mime="text/csv",
            use_container_width=True,
        )


def show_table(title: str, path: Path, default_columns: list[str] | None = None, max_rows: int = 200) -> None:
    df = read_csv(path)
    if df.empty:
        st.info(f"暂时没有生成 {title}。")
        return
    st.subheader(title)
    st.caption(f"{path} · {len(df)} rows")
    if default_columns:
        cols = [c for c in default_columns if c in df.columns]
        if cols:
            st.dataframe(df[cols].head(max_rows), use_container_width=True, height=420)
            with st.expander("查看全部字段"):
                st.dataframe(df.head(max_rows), use_container_width=True, height=420)
            return
    st.dataframe(df.head(max_rows), use_container_width=True, height=420)


def show_metrics(paths: dict[str, Path]) -> None:
    cluster_df = read_csv(paths["cluster_audit"])
    queue_df = read_csv(paths["primary_queue"])
    title_df = read_csv(paths["title_audit"])
    body_df = read_csv(paths["body_blueprint"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("原始关键词", len(cluster_df) if not cluster_df.empty else "-")
    c2.metric("主文章数", len(queue_df) if not queue_df.empty else (len(title_df) if not title_df.empty else "-"))
    if not cluster_df.empty and not queue_df.empty:
        c3.metric("合并支持词", max(0, len(cluster_df) - len(queue_df)))
    else:
        c3.metric("合并支持词", "-")
    if not body_df.empty and "target_word_count" in body_df.columns:
        c4.metric("正文平均目标字数", int(pd.to_numeric(body_df["target_word_count"], errors="coerce").fillna(0).mean()))
    else:
        c4.metric("正文平均目标字数", "-")

    if not title_df.empty and "title_shape" in title_df.columns:
        st.markdown("**标题结构分布**")
        st.bar_chart(title_df["title_shape"].value_counts())
    if not body_df.empty and "body_template" in body_df.columns:
        st.markdown("**正文模板分布**")
        st.bar_chart(body_df["body_template"].value_counts())


ensure_dirs()

st.title("Anqi Writer SEO Pipeline")
st.caption("关键词聚类 → 主文章标题 → 正文蓝图。适合先审计，再进入批量正文生成。")

with st.sidebar:
    st.header("运行设置")
    default_run_name = time.strftime("run_%Y%m%d_%H%M%S")
    run_name = st.text_input("运行名称", default_run_name)
    uploaded = st.file_uploader("上传关键词 TXT / CSV", type=["txt", "csv"])
    st.caption("CSV 支持 keyword 或 primary_keyword 字段；TXT 一行一个关键词。")
    run_cluster = st.checkbox("1. 关键词聚类", value=True)
    run_titles = st.checkbox("2. 生成标题", value=True)
    run_body = st.checkbox("3. 生成正文蓝图", value=True)
    start = st.button("开始运行", type="primary", use_container_width=True)

sample_text = """ozempic for weight loss
weight loss pills
pink salt recipe for weight loss
metabolism booster for women
what does a dietitian do for weight loss
"""

keywords_text = st.text_area(
    "粘贴关键词",
    value=sample_text,
    height=180,
    help="一行一个关键词。上传文件和粘贴内容可以同时使用，会自动去重。",
)

pasted_keywords = read_text_keywords(keywords_text)
uploaded_keywords = read_uploaded_keywords(uploaded)
all_keywords = []
seen = set()
for kw in uploaded_keywords + pasted_keywords:
    key = kw.lower().strip()
    if key and key not in seen:
        seen.add(key)
        all_keywords.append(kw)

st.markdown(f"当前待处理关键词：**{len(all_keywords)}** 个")

if start:
    if not all_keywords:
        st.error("请先上传或粘贴关键词。")
    else:
        with st.status("正在运行 SEO Pipeline...", expanded=True) as status:
            paths, logs = run_pipeline(all_keywords, run_name, run_cluster, run_titles, run_body)
            for step, ok, output in logs:
                if ok:
                    st.success(step)
                else:
                    st.error(step)
                if output:
                    st.code(output)
            if all(ok for _, ok, _ in logs):
                status.update(label="运行完成", state="complete")
            else:
                status.update(label="运行失败", state="error")
        st.session_state["last_paths"] = {k: str(v) for k, v in paths.items()}

if "last_paths" not in st.session_state:
    st.info("先上传或粘贴关键词，然后点击左侧“开始运行”。")
else:
    paths = {k: Path(v) for k, v in st.session_state["last_paths"].items()}
    st.divider()
    show_metrics(paths)

    d1, d2, d3, d4 = st.columns(4)
    with d1:
        csv_download_button(paths["cluster_audit"], "下载聚类审计 CSV")
    with d2:
        csv_download_button(paths["primary_queue"], "下载主文章队列 CSV")
    with d3:
        csv_download_button(paths["title_audit"], "下载标题审计 CSV")
    with d4:
        csv_download_button(paths["body_blueprint"], "下载正文蓝图 CSV")

    tab1, tab2, tab3, tab4 = st.tabs(["关键词聚类", "主文章队列", "标题审计", "正文蓝图"])
    with tab1:
        show_table("关键词聚类审计", paths["cluster_audit"], ["keyword", "publish_role", "merge_usage", "primary_keyword", "cluster_size", "keyword_score", "score_reason"])
    with tab2:
        show_table("主文章队列", paths["primary_queue"], ["primary_keyword", "cluster_size", "canonical_subject", "intent_family", "secondary_keywords", "faq_keywords", "h2_keywords"])
    with tab3:
        show_table("标题审计", paths["title_audit"], ["keyword", "title", "title_shape", "ctr_angle", "title_score", "secondary_keywords", "faq_keywords", "h2_keywords"])
    with tab4:
        show_table("正文蓝图", paths["body_blueprint"], ["keyword", "title", "body_template", "target_word_count", "word_count_range", "h2_1", "h2_2", "h2_3", "faq_keywords", "content_warnings"])
