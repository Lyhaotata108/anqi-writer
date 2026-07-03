#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local browser-based UI for keyword generation, preview, and CMS import."""

from __future__ import annotations

import html
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlparse
import webbrowser

from cleanup_generated import cleanup_generated_outputs
from pipeline_controller import PipelineController


WORKSPACE_ROOT = Path("/Users/hjg/Documents/anqicms-writer")
HOST = "127.0.0.1"
PORT = 8765
controller = PipelineController(WORKSPACE_ROOT)
state_lock = threading.Lock()
state: dict[str, object] = {
    "stage": "Idle",
    "progress": 0,
    "logs": [],
    "result": None,
    "publish": None,
    "running": False,
    "category_id": 1,
    "mode": "single",
    "batch_jobs": [],
    "batch_summary": {"total_jobs": 0, "running_jobs": 0, "completed_jobs": 0, "failed_jobs": 0},
    "current_item": "",
    "last_batch_input": "",
    "auto_publish": False,
    "batch_group_count": 3,
}


def append_log(message: str) -> None:
    with state_lock:
        logs = list(state.get("logs", []))
        logs.append(message)
        state["logs"] = logs[-200:]


def progress_callback(stage: str, percent: int, message: str) -> None:
    with state_lock:
        state["stage"] = stage
        state["progress"] = percent
    append_log(f"[{stage}] {message}")


def make_batch_progress_callback(item_index: int, total: int, label: str):
    def callback(stage: str, percent: int, message: str) -> None:
        overall = int((((item_index - 1) + (percent / 100)) / total) * 100)
        with state_lock:
            state["stage"] = stage
            state["progress"] = overall
            state["current_item"] = f"[{item_index}/{total}] {label}"
        append_log(f"[{item_index}/{total}][{stage}] {message}")

    return callback


def parse_batch_keywords(raw: str) -> list[str]:
    keywords: list[str] = []
    for line in raw.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        keywords.append(value)
    return keywords


def parse_industry_groups(raw: str) -> list[dict[str, object]]:
    lane_labels = [
        ("WEIGHT_LOSS", "Weight Loss", 1),
        ("BLOOD", "Blood", 9),
        ("CBD", "CBD", 5),
    ]
    chunks = [parse_batch_keywords(chunk) for chunk in re.split(r"\n\s*\n+", raw) if parse_batch_keywords(chunk)]
    groups: list[dict[str, object]] = []
    for index, (topic_category, label, category_id) in enumerate(lane_labels):
        keywords = chunks[index] if index < len(chunks) else []
        groups.append({"name": label, "topic_category": topic_category, "category_id": category_id, "keywords": keywords})
    return groups


def make_output_dir(group_index: int, group_name: str) -> Path:
    safe_name = re.sub(r"[^a-z0-9]+", "-", group_name.lower()).strip("-") or f"industry-{group_index}"
    return WORKSPACE_ROOT / f"industry_{group_index}_{safe_name}"


def update_batch_job(job_index: int, **changes: object) -> None:
    with state_lock:
        jobs = [dict(item) for item in state.get("batch_jobs", []) if isinstance(item, dict)]
        if job_index >= len(jobs):
            return
        jobs[job_index].update(changes)
        state["batch_jobs"] = jobs
        completed_jobs = sum(1 for job in jobs if job.get("status") == "completed")
        failed_jobs = sum(1 for job in jobs if job.get("status") == "failed")
        running_jobs = sum(1 for job in jobs if job.get("status") == "running")
        state["batch_summary"] = {
            "total_jobs": len(jobs),
            "running_jobs": running_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
        }


def index_html() -> str:
    with state_lock:
        stage = str(state.get("stage", "Idle"))
        progress = int(state.get("progress", 0) or 0)
        logs = list(state.get("logs", []))
        result = state.get("result")
        publish = state.get("publish")
        running = bool(state.get("running", False))
        category_id = int(state.get("category_id", 1) or 1)
        batch_jobs = [dict(item) for item in state.get("batch_jobs", []) if isinstance(item, dict)]
        batch_summary = dict(state.get("batch_summary", {"total_jobs": 0, "running_jobs": 0, "completed_jobs": 0, "failed_jobs": 0}))
        current_item = html.escape(str(state.get("current_item", "") or ""))
        last_batch_input = str(state.get("last_batch_input", "") or "")
        auto_publish = bool(state.get("auto_publish", False))

    lane_values = ["", "", ""]
    if last_batch_input:
        lane_chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n+", last_batch_input) if chunk.strip()]
        for index, chunk in enumerate(lane_chunks[:3]):
            lane_values[index] = html.escape(chunk)

    result_html = "<p>No article generated yet.</p>"
    if isinstance(result, dict):
        preview_link = html.escape(str(result.get("preview_url", "#")))
        markdown_path = html.escape(str(result.get("markdown_path", "")))
        title = html.escape(str(result.get("title", "")))
        description = html.escape(str(result.get("description", "")))
        stage1_1_path = html.escape(str(result.get("stage1_1_path", "")))
        stage1_2_path = html.escape(str(result.get("stage1_2_path", "")))
        result_html = f"""
        <div class='card'>
          <h3>Latest result</h3>
          <p><strong>Title:</strong> {title}</p>
          <p><strong>Description:</strong> {description}</p>
          <p><strong>Stage 1-1:</strong> {stage1_1_path}</p>
          <p><strong>Stage 1-2:</strong> {stage1_2_path}</p>
          <p><strong>Markdown:</strong> {markdown_path}</p>
          <p><a href='{preview_link}' target='_blank' rel='noopener noreferrer'>Open preview</a></p>
        </div>
        """

    publish_html = "<p>Publish status: not started.</p>"
    if isinstance(publish, dict):
        publish_html = f"""
        <div class='card'>
          <h3>Publish status</h3>
          <p><strong>ok:</strong> {html.escape(str(publish.get('ok')))}</p>
          <p><strong>HTTP:</strong> {html.escape(str(publish.get('http_status')))}</p>
          <p><strong>API:</strong> {html.escape(str(publish.get('api_code')))}</p>
          <p><strong>Remote ID:</strong> {html.escape(str(publish.get('remote_id')))}</p>
          <p><strong>Message:</strong> {html.escape(str(publish.get('message')))}</p>
        </div>
        """

    batch_summary_html = ""
    if batch_summary.get("total_jobs", 0):
        batch_summary_html = (
            f"<p><strong>Industry jobs:</strong> Total {int(batch_summary.get('total_jobs', 0))}, "
            f"Running {int(batch_summary.get('running_jobs', 0))}, "
            f"Completed {int(batch_summary.get('completed_jobs', 0))}, "
            f"Failed {int(batch_summary.get('failed_jobs', 0))}</p>"
        )
    current_item_html = f"<p><strong>Current item:</strong> {current_item}</p>" if current_item else ""

    batch_results_html = "<p>No batch generation yet.</p>"
    if batch_jobs:
        cards: list[str] = []
        for job_index, job in enumerate(batch_jobs, 1):
            results = [dict(item) for item in job.get("results", []) if isinstance(item, dict)]
            rows: list[str] = []
            for index, item in enumerate(results, 1):
                preview_url = str(item.get("preview_url", "")).strip()
                preview_html = (
                    f"<a href='{html.escape(preview_url)}' target='_blank' rel='noopener noreferrer'>Preview</a>"
                    if preview_url
                    else "-"
                )
                rows.append(
                    "<tr>"
                    f"<td>{index}</td>"
                    f"<td>{html.escape(str(item.get('source_keyword', '')))}</td>"
                    f"<td>{html.escape(str(item.get('title', '')))}</td>"
                    f"<td>{html.escape(str(item.get('topic_category', '')))}</td>"
                    f"<td>{html.escape(str(item.get('status', '')))}</td>"
                    f"<td>{preview_html}</td>"
                    f"<td>{html.escape(str(item.get('markdown_path', '')))}</td>"
                    f"<td>{html.escape(str(item.get('publish_remote_id', '')) if item.get('publish_remote_id') is not None else '')}</td>"
                    f"<td>{html.escape(str(item.get('publish_message', '')))}</td>"
                    f"<td>{html.escape(str(item.get('error', '')))}</td>"
                    "</tr>"
                )
            cards.append(f"""
            <div class='card section-gap'>
              <h3>{html.escape(str(job.get('name', f'Industry {job_index}')))}</h3>
              <p><strong>Lane:</strong> {html.escape(str(job.get('topic_category', 'WEIGHT_LOSS')))}</p>
              <p><strong>Category ID:</strong> {html.escape(str(job.get('category_id', '')))}</p>
              <p><strong>Status:</strong> {html.escape(str(job.get('status', 'pending')))}</p>
              <p><strong>Progress:</strong> {int(job.get('progress', 0) or 0)}%</p>
              <p><strong>Output:</strong> {html.escape(str(job.get('output_dir', '')))}</p>
              <p><strong>Summary:</strong> Completed {int(job.get('completed', 0) or 0)}/{int(job.get('total', 0) or 0)}, Failed {int(job.get('failed', 0) or 0)}</p>
              <div class='table-wrap'>
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Source keyword</th>
                      <th>Generated title</th>
                      <th>Topic</th>
                      <th>Status</th>
                      <th>Preview</th>
                      <th>Markdown</th>
                      <th>Remote ID</th>
                      <th>Publish message</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {''.join(rows) if rows else '<tr><td colspan="10">No results yet.</td></tr>'}
                  </tbody>
                </table>
              </div>
            </div>
            """)
        batch_results_html = f"<div class='card'><h3>Industry batch results</h3>{batch_summary_html}{current_item_html}</div>{''.join(cards)}"

    logs_html = "\n".join(f"<div>{html.escape(str(line))}</div>" for line in logs)
    disabled_attr = "disabled" if running else ""
    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='UTF-8' />
<meta name='viewport' content='width=device-width, initial-scale=1.0' />
<title>AnQiCMS Local Web UI</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f4f6fb;color:#111827;margin:0;}}
.wrap{{max-width:1240px;margin:32px auto;padding:0 16px;}}
.grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:16px;}}
.card{{background:#fff;border:1px solid #dbe3ee;border-radius:14px;padding:16px;box-shadow:0 8px 24px rgba(15,23,42,.05);}}
input,select,textarea{{width:100%;padding:10px 12px;border:1px solid #cbd5e1;border-radius:10px;font-size:14px;}}
textarea{{min-height:160px;resize:vertical;}}
button{{padding:10px 14px;border:none;border-radius:10px;background:#2563eb;color:#fff;font-weight:600;cursor:pointer;}}
button[disabled]{{background:#94a3b8;cursor:not-allowed;}}
.progress{{height:12px;background:#e5e7eb;border-radius:999px;overflow:hidden;margin-top:8px;}}
.progress > div{{height:100%;background:#2563eb;width:{progress}%;}}
.logs{{max-height:360px;overflow:auto;background:#0f172a;color:#e2e8f0;border-radius:12px;padding:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;}}
.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;align-items:center;}}
small{{color:#64748b;}}
table{{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px;}}
th,td{{text-align:left;border-bottom:1px solid #e5e7eb;padding:8px;vertical-align:top;}}
th{{background:#f8fafc;position:sticky;top:0;}}
.table-wrap{{overflow:auto;max-height:360px;}}
.section-gap{{margin-top:16px;}}
</style>
</head>
<body>
  <div class='wrap'>
    <h1>AnQiCMS Local Web UI</h1>
    <div class='grid'>
      <div>
        <div class='card'>
          <h3>Single article</h3>
          <form method='POST' action='/generate'>
            <label><strong>Keyword</strong></label>
            <input name='keyword' placeholder='Enter keyword' required />
            <div class='actions'>
              <label><strong>Category ID</strong></label>
              <select name='category_id'>
                <option value='1' {'selected' if category_id == 1 else ''}>1</option>
                <option value='5' {'selected' if category_id == 5 else ''}>5</option>
              </select>
            </div>
            <div class='actions'>
              <label><input type='checkbox' name='auto_publish' value='1' {'checked' if auto_publish else ''} /> Auto import after generation</label>
            </div>
            <div class='actions'>
              <button type='submit' {disabled_attr}>Start generation</button>
            </div>
          </form>
          <form method='POST' action='/publish'>
            <div class='actions'>
              <button type='submit' {disabled_attr}>Import to CMS</button>
              <button type='button' onclick='location.reload()'>Refresh status</button>
            </div>
          </form>
          <p><small>Current stage: {html.escape(stage)}</small></p>
          <div class='progress'><div></div></div>
        </div>
        <div class='card section-gap'>
          <h3>Batch generation</h3>
          <form method='POST' action='/generate-batch'>
            <label><strong>Weight Loss</strong></label>
            <textarea name='weight_loss_keywords' placeholder='One weight-loss keyword per line'>{lane_values[0]}</textarea>
            <div class='section-gap'></div>
            <label><strong>Blood</strong></label>
            <textarea name='blood_keywords' placeholder='One blood keyword per line'>{lane_values[1]}</textarea>
            <div class='section-gap'></div>
            <label><strong>CBD</strong></label>
            <textarea name='cbd_keywords' placeholder='One CBD keyword per line'>{lane_values[2]}</textarea>
            <div class='card section-gap' style='padding:12px;'>
              <p><strong>Fixed Category IDs</strong></p>
              <p>Weight Loss = 1</p>
              <p>Blood = 9</p>
              <p>CBD = 5</p>
            </div>
            <div class='actions'>
              <label><input type='checkbox' name='auto_publish' value='1' {'checked' if auto_publish else ''} /> Auto import each article after generation</label>
            </div>
            <div class='actions'>
              <button type='submit' {disabled_attr}>Start batch generation</button>
            </div>
          </form>
          <p><small>These three fixed lanes run in parallel. Each lane only writes content for its own topic.</small></p>
        </div>
        <div class='card section-gap'>
          <h3>Logs</h3>
          <div class='logs'>{logs_html}</div>
        </div>
      </div>
      <div>
        {result_html}
        {publish_html}
        {batch_results_html}
      </div>
    </div>
  </div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send_html(self, content: str, status: int = 200) -> None:
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect_home(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(index_html())
            return
        file_path = (WORKSPACE_ROOT / parsed.path.lstrip("/")).resolve()
        if WORKSPACE_ROOT in file_path.parents and file_path.is_file():
            content_type = "text/plain; charset=utf-8"
            if file_path.suffix == ".html":
                content_type = "text/html; charset=utf-8"
            elif file_path.suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                content_type = f"image/{file_path.suffix.lstrip('.').replace('jpg', 'jpeg')}"
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send_html("<h1>Not found</h1>", 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw)
        if self.path == "/generate":
            keyword = (form.get("keyword", [""])[0]).strip()
            category_id_raw = (form.get("category_id", ["1"])[0]).strip()
            category_id = 5 if category_id_raw == "5" else 1
            auto_publish = form.get("auto_publish", [""])[0] == "1"
            if keyword:
                with state_lock:
                    state["running"] = True
                    state["logs"] = []
                    state["publish"] = None
                    state["category_id"] = category_id
                    state["mode"] = "single"
                    state["batch_jobs"] = []
                    state["batch_summary"] = {"total_jobs": 0, "running_jobs": 0, "completed_jobs": 0, "failed_jobs": 0}
                    state["current_item"] = keyword
                    state["auto_publish"] = auto_publish
                style = controller.suggest_title_styles(keyword)[0]
                append_log(f"[Input] keyword={keyword} category_id={category_id} style={style} auto_publish={auto_publish}")
                result = controller.run_generation(keyword, category_id=category_id, style=style, progress=progress_callback)
                latest_result = {
                    "title": result.title,
                    "description": result.description,
                    "stage1_1_path": str(result.stage1_1_path),
                    "stage1_2_path": str(result.stage1_2_path),
                    "markdown_path": str(result.markdown_path),
                    "preview_url": f"/{result.preview_path.name}",
                }
                publish_result = None
                if auto_publish:
                    append_log(f"[Publishing] Auto importing {result.markdown_path.name}")
                    publish_result = controller.publish_existing(result.markdown_path, progress=progress_callback)
                with state_lock:
                    state["result"] = latest_result
                    if publish_result is not None:
                        state["publish"] = publish_result
                    state["running"] = False
            self._redirect_home()
            return
        if self.path == "/generate-batch":
            weight_loss_keywords = (form.get("weight_loss_keywords", [""])[0])
            blood_keywords = (form.get("blood_keywords", [""])[0])
            cbd_keywords = (form.get("cbd_keywords", [""])[0])
            raw_batch = "\n\n".join([weight_loss_keywords, blood_keywords, cbd_keywords])
            auto_publish = form.get("auto_publish", [""])[0] == "1"
            groups = parse_industry_groups(raw_batch)
            with state_lock:
                state["running"] = True
                state["logs"] = []
                state["publish"] = None
                state["category_id"] = 0
                state["mode"] = "batch"
                state["batch_jobs"] = []
                state["batch_summary"] = {"total_jobs": len(groups), "running_jobs": 0, "completed_jobs": 0, "failed_jobs": 0}
                state["current_item"] = ""
                state["last_batch_input"] = raw_batch
                state["auto_publish"] = auto_publish
            if not groups:
                append_log("[Failed] No valid industry groups found.")
                with state_lock:
                    state["running"] = False
                    state["stage"] = "Failed"
                    state["progress"] = 0
                self._redirect_home()
                return

            jobs: list[dict[str, object]] = []
            for job_index, group in enumerate(groups, 1):
                group_name = str(group.get("name", f"Industry {job_index}"))
                topic_category = str(group.get("topic_category", "WEIGHT_LOSS"))
                lane_category_id = int(group.get("category_id", 1) or 1)
                output_dir = make_output_dir(job_index, group_name)
                jobs.append(
                    {
                        "name": group_name,
                        "topic_category": topic_category,
                        "category_id": lane_category_id,
                        "status": "pending",
                        "progress": 0,
                        "completed": 0,
                        "failed": 0,
                        "total": len(group.get("keywords", [])),
                        "results": [],
                        "output_dir": str(output_dir),
                    }
                )
            with state_lock:
                state["batch_jobs"] = jobs
                state["batch_summary"] = {"total_jobs": len(jobs), "running_jobs": len(jobs), "completed_jobs": 0, "failed_jobs": 0}

            append_log("[Batch] fixed lane category IDs: Weight Loss=1, Blood=9, CBD=5")
            append_log(f"[Batch] industries={len(groups)} auto_publish={auto_publish}")

            def run_group(job_index: int, group_name: str, topic_category: str, lane_category_id: int, keywords: list[str], output_dir: Path) -> None:
                local_controller = PipelineController(WORKSPACE_ROOT, output_root=output_dir)
                update_batch_job(job_index, status="running", progress=0, results=[], completed=0, failed=0)
                completed = 0
                failed = 0
                results: list[dict[str, object]] = []
                total = len(keywords)
                for item_index, raw_keyword in enumerate(keywords, 1):
                    with state_lock:
                        state["current_item"] = f"[{group_name}] {raw_keyword}"
                    append_log(f"[{group_name}][{item_index}/{total}] raw keyword={raw_keyword}")
                    style = local_controller.suggest_title_styles(raw_keyword)[0]
                    title_plan = local_controller.generate_title_plan(raw_keyword, style=style, topic_category=topic_category)
                    if title_plan is None:
                        failed += 1
                        results.append(
                            {
                                "source_keyword": raw_keyword,
                                "title": "",
                                "topic_category": "",
                                "style": "",
                                "candidate_styles": list(local_controller.suggest_title_styles(raw_keyword)),
                                "status": "failed",
                                "error": "Gemini title generation did not produce any acceptable title after retry; skipped without fallback template",
                                "markdown_path": "",
                                "preview_url": "",
                            }
                        )
                        append_log(f"[{group_name}][{item_index}/{total}][Failed] Gemini title generation failed twice; skipped")
                        progress = int((item_index / total) * 100) if total else 0
                        update_batch_job(job_index, results=list(results), completed=completed, failed=failed, progress=progress)
                        continue

                    append_log(
                        f"[{group_name}][{item_index}/{total}] style={title_plan.style} candidates={','.join(title_plan.candidate_styles)} "
                        f"generated title={title_plan.title} topic_category={title_plan.topic_category}"
                    )

                    def callback(stage: str, percent: int, message: str) -> None:
                        overall = int((((item_index - 1) + (percent / 100)) / total) * 100) if total else percent
                        update_batch_job(job_index, progress=overall)
                        with state_lock:
                            state["stage"] = stage
                            state["progress"] = overall
                            state["current_item"] = f"[{group_name}] {title_plan.title}"
                        append_log(f"[{group_name}][{item_index}/{total}][{stage}] {message}")

                    try:
                        result = local_controller.run_generation(
                            title_plan.title,
                            category_id=lane_category_id,
                            style=title_plan.style,
                            progress=callback,
                        )
                        preview_relative = result.preview_path.relative_to(WORKSPACE_ROOT)
                        latest_result = {
                            "title": result.title,
                            "description": result.description,
                            "stage1_1_path": str(result.stage1_1_path),
                            "stage1_2_path": str(result.stage1_2_path),
                            "markdown_path": str(result.markdown_path),
                            "preview_url": f"/{preview_relative.as_posix()}",
                        }
                        record = {
                            "source_keyword": raw_keyword,
                            "title": title_plan.title,
                            "topic_category": title_plan.topic_category,
                            "style": title_plan.style,
                            "candidate_styles": list(title_plan.candidate_styles),
                            "status": "generated",
                            "description": result.description,
                            "stage1_1_path": str(result.stage1_1_path),
                            "stage1_2_path": str(result.stage1_2_path),
                            "markdown_path": str(result.markdown_path),
                            "preview_url": f"/{preview_relative.as_posix()}",
                        }
                        if auto_publish:
                            append_log(f"[{group_name}][{item_index}/{total}][Publishing] Auto importing {result.markdown_path.name}")
                            publish_result = local_controller.publish_existing(result.markdown_path, progress=callback)
                            record["publish_ok"] = publish_result.get("ok")
                            record["publish_http"] = publish_result.get("http_status")
                            record["publish_api"] = publish_result.get("api_code")
                            record["publish_message"] = publish_result.get("message")
                            record["publish_remote_id"] = publish_result.get("remote_id")
                            with state_lock:
                                state["publish"] = publish_result
                        results.append(record)
                        completed += 1
                        with state_lock:
                            state["result"] = latest_result
                    except Exception as error:  # noqa: BLE001
                        failed += 1
                        results.append(
                            {
                                "source_keyword": raw_keyword,
                                "title": title_plan.title,
                                "topic_category": title_plan.topic_category,
                                "status": "failed",
                                "error": str(error),
                                "markdown_path": "",
                                "preview_url": "",
                            }
                        )
                        append_log(f"[{group_name}][{item_index}/{total}][Failed] {error}")
                    progress = int((item_index / total) * 100) if total else 100
                    update_batch_job(job_index, results=list(results), completed=completed, failed=failed, progress=progress)

                final_status = "failed" if failed and completed == 0 else "completed"
                update_batch_job(job_index, status=final_status, progress=100 if total else 0, results=list(results), completed=completed, failed=failed)

            with ThreadPoolExecutor(max_workers=min(3, len(groups))) as executor:
                futures = [
                    executor.submit(
                        run_group,
                        job_index - 1,
                        str(group.get("name", f"Industry {job_index}")),
                        str(group.get("topic_category", "WEIGHT_LOSS")),
                        int(group.get("category_id", 1) or 1),
                        list(group.get("keywords", [])),
                        make_output_dir(job_index, str(group.get("name", f"Industry {job_index}"))),
                    )
                    for job_index, group in enumerate(groups, 1)
                ]
                for future in as_completed(futures):
                    future.result()

            with state_lock:
                summary = dict(state.get("batch_summary", {}))
                state["running"] = False
                state["stage"] = "Published" if summary.get("failed_jobs", 0) == 0 else "Ready_to_Publish"
                state["progress"] = 100
                state["current_item"] = ""
            self._redirect_home()
            return
        if self.path == "/publish":
            with state_lock:
                result = state.get("result")
                state["running"] = True
            if isinstance(result, dict):
                markdown_path = Path(str(result.get("markdown_path")))
                publish = controller.publish_existing(markdown_path, progress=progress_callback)
                with state_lock:
                    state["publish"] = publish
                    state["running"] = False
            else:
                append_log("[Failed] No generated article available to publish.")
                with state_lock:
                    state["running"] = False
            self._redirect_home()
            return
        self._send_html("<h1>Not found</h1>", 404)


def main() -> None:
    summary = cleanup_generated_outputs(WORKSPACE_ROOT)
    print(
        "Cleanup complete: "
        f"removed_files={summary.removed_files} "
        f"removed_directories={summary.removed_directories}"
    )
    append_log(
        "[Cleanup] Cleanup complete: "
        f"removed_files={summary.removed_files} "
        f"removed_directories={summary.removed_directories}"
    )
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"Local web UI running at {url}")
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
