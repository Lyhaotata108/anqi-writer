#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Browser-based local UI for AnQiCMS article generation.

Run:
    python3 scripts/browser_ui.py

Then open:
    http://127.0.0.1:8765

This browser UI supports three category keyword buckets and batch generation.
It avoids macOS Tkinter rendering issues by using a local HTTP server.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import uuid
import webbrowser

from editorial_pipeline_controller import EditorialPipelineController, PipelineResult


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
WORKSPACE_ROOT = Path("/Users/hjg/Documents/anqicms-writer")
OUTPUT_ROOT = WORKSPACE_ROOT
DEFAULT_CATEGORY_IDS = [1, 5, 9]

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
CONTROLLER = EditorialPipelineController(WORKSPACE_ROOT, output_root=OUTPUT_ROOT)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AnQiCMS Batch Generator</title>
  <style>
    :root {
      --bg: #f3f4f6;
      --card: #ffffff;
      --text: #111827;
      --muted: #6b7280;
      --border: #d1d5db;
      --black: #111827;
      --green: #166534;
      --red: #991b1b;
      --blue: #1d4ed8;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Arial, Helvetica, sans-serif; background: var(--bg); color: var(--text); }
    .wrap { max-width: 1380px; margin: 0 auto; padding: 24px; }
    .header { margin-bottom: 18px; }
    h1 { margin: 0; font-size: 24px; line-height: 1.2; }
    .sub { margin-top: 6px; color: var(--muted); font-size: 14px; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 18px; box-shadow: 0 8px 24px rgba(17,24,39,0.06); }
    .category-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
    .bucket { border: 1px solid var(--border); border-radius: 12px; padding: 14px; background: #fff; }
    .bucket-head { display: grid; grid-template-columns: 1fr 90px; gap: 10px; align-items: end; margin-bottom: 10px; }
    label { display: block; font-weight: 700; font-size: 13px; margin-bottom: 6px; }
    input, textarea { width: 100%; border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; font-size: 14px; outline: none; background: #fff; color: var(--text); }
    input { height: 40px; }
    textarea { min-height: 150px; resize: vertical; font-family: Menlo, Consolas, monospace; line-height: 1.45; }
    input:focus, textarea:focus { border-color: var(--black); }
    button { height: 42px; border: 0; border-radius: 10px; padding: 0 14px; font-size: 14px; font-weight: 700; background: var(--black); color: #fff; cursor: pointer; }
    button.blue { background: var(--blue); }
    button.green { background: var(--green); }
    button.secondary { background: #374151; }
    button:disabled { background: #9ca3af; cursor: not-allowed; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 14px; }
    .status-row { margin-top: 14px; display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center; }
    .status { font-weight: 700; }
    .progress { width: 100%; height: 12px; background: #e5e7eb; border-radius: 99px; overflow: hidden; margin-top: 8px; }
    .bar { height: 100%; width: 0%; background: var(--black); transition: width .25s ease; }
    .main { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
    .panel-title { margin: 0 0 10px; font-size: 15px; font-weight: 800; }
    pre, .markdown-box { width: 100%; min-height: 500px; border: 1px solid var(--border); border-radius: 12px; background: #fff; color: var(--text); padding: 14px; white-space: pre-wrap; word-break: break-word; overflow: auto; font-family: Menlo, Consolas, monospace; font-size: 13px; line-height: 1.55; margin: 0; }
    .summary { min-height: 150px; max-height: 230px; margin-bottom: 12px; }
    .tiny { color: var(--muted); font-size: 12px; margin-top: 8px; line-height: 1.5; }
    .result-list { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; }
    .result-link { display: inline-block; padding: 6px 9px; border-radius: 8px; background: #eef2ff; color: #1d4ed8; text-decoration: none; font-size: 12px; font-weight: 700; }
    .err { color: var(--red); font-weight: 700; }
    .ok { color: var(--green); font-weight: 700; }
    @media (max-width: 1000px) { .category-grid { grid-template-columns: 1fr; } .status-row { grid-template-columns: 1fr; } .main { grid-template-columns: 1fr; } pre, .markdown-box { min-height: 320px; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <h1>AnQiCMS Batch Generator</h1>
      <div class="sub">Three categories · batch keywords · editorial segmented generation · markdown preview · CMS import</div>
    </div>

    <div class="card">
      <div class="category-grid">
        <div class="bucket">
          <div class="bucket-head">
            <div><label>Category 1 Name</label><input id="catName1" value="Weight Loss" /></div>
            <div><label>ID</label><input id="catId1" value="1" /></div>
          </div>
          <label>Keywords, one per line</label>
          <textarea id="keywords1" placeholder="mounjaro weight loss&#10;what does a dietitian do for weight loss"></textarea>
        </div>
        <div class="bucket">
          <div class="bucket-head">
            <div><label>Category 2 Name</label><input id="catName2" value="Blood Health" /></div>
            <div><label>ID</label><input id="catId2" value="5" /></div>
          </div>
          <label>Keywords, one per line</label>
          <textarea id="keywords2" placeholder="cholesterol symptoms&#10;blood sugar after eating"></textarea>
        </div>
        <div class="bucket">
          <div class="bucket-head">
            <div><label>Category 3 Name</label><input id="catName3" value="CBD" /></div>
            <div><label>ID</label><input id="catId3" value="9" /></div>
          </div>
          <label>Keywords, one per line</label>
          <textarea id="keywords3" placeholder="cbd gummies for sleep&#10;cbd oil side effects"></textarea>
        </div>
      </div>

      <div class="actions">
        <button id="startBtn" onclick="startBatchGeneration()">Start Batch Generation</button>
        <button class="secondary" onclick="fillDemo()">Fill Demo</button>
        <button class="secondary" onclick="clearAll()">Clear</button>
        <span class="tiny">批量规则：每行一个关键词；系统会按所属分类 ID 逐个生成 `.md`。</span>
      </div>

      <div class="status-row">
        <div>
          <div id="status" class="status">Idle</div>
          <div class="progress"><div id="bar" class="bar"></div></div>
        </div>
        <button id="previewBtn" class="blue" onclick="openFirstPreview()" disabled>Open First Preview</button>
        <button id="publishBtn" class="green" onclick="publishToCms()" disabled>Import All to CMS</button>
      </div>
      <div id="publishStatus" class="tiny">Publish status: not started</div>
      <div id="resultLinks" class="result-list"></div>
    </div>

    <div class="main">
      <div class="card">
        <div class="panel-title">Logs</div>
        <pre id="logs">Waiting...</pre>
      </div>
      <div class="card">
        <div class="panel-title">Result Summary</div>
        <pre id="summary" class="summary">No articles generated yet.</pre>
        <div class="panel-title">Markdown Preview</div>
        <textarea id="markdown" class="markdown-box" readonly></textarea>
      </div>
    </div>
  </div>

<script>
let currentJobId = null;
let polling = null;
let currentResults = [];

function lines(text) {
  return text.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
}

function collectTasks() {
  const buckets = [1, 2, 3].map(i => ({
    category_id: document.getElementById('catId' + i).value.trim(),
    category_name: document.getElementById('catName' + i).value.trim(),
    keywords: lines(document.getElementById('keywords' + i).value)
  }));
  const tasks = [];
  for (const bucket of buckets) {
    if (!bucket.category_id && bucket.keywords.length) throw new Error('Category ID is required for ' + (bucket.category_name || 'a bucket'));
    for (const keyword of bucket.keywords) {
      tasks.push({keyword, category_id: bucket.category_id, category_name: bucket.category_name});
    }
  }
  return tasks;
}

function setStatus(text, percent) {
  document.getElementById('status').textContent = text;
  document.getElementById('bar').style.width = Math.max(0, Math.min(100, percent || 0)) + '%';
}

function fillDemo() {
  document.getElementById('keywords1').value = 'mounjaro weight loss\nwhat does a dietitian do for weight loss';
  document.getElementById('keywords2').value = 'cholesterol symptoms\nblood sugar after eating';
  document.getElementById('keywords3').value = 'cbd gummies for sleep\ncbd oil side effects';
}

function clearAll() {
  document.getElementById('keywords1').value = '';
  document.getElementById('keywords2').value = '';
  document.getElementById('keywords3').value = '';
}

function renderResultLinks(results) {
  currentResults = results || [];
  const box = document.getElementById('resultLinks');
  box.innerHTML = '';
  currentResults.forEach((item, index) => {
    const a = document.createElement('a');
    a.className = 'result-link';
    a.href = '/preview?job_id=' + encodeURIComponent(currentJobId) + '&index=' + index;
    a.target = '_blank';
    a.textContent = (index + 1) + '. ' + item.keyword + ' · cat ' + item.category_id;
    box.appendChild(a);
  });
}

async function startBatchGeneration() {
  let tasks;
  try {
    tasks = collectTasks();
  } catch (error) {
    alert(error.message);
    return;
  }
  if (!tasks.length) {
    alert('Please paste at least one keyword under one category.');
    return;
  }
  document.getElementById('startBtn').disabled = true;
  document.getElementById('previewBtn').disabled = true;
  document.getElementById('publishBtn').disabled = true;
  document.getElementById('logs').textContent = 'Starting batch...';
  document.getElementById('summary').textContent = 'Queued ' + tasks.length + ' keywords...';
  document.getElementById('markdown').value = '';
  document.getElementById('publishStatus').textContent = 'Publish status: not started';
  document.getElementById('resultLinks').innerHTML = '';
  setStatus('Queued', 5);

  const res = await fetch('/api/generate_batch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({tasks})
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById('startBtn').disabled = false;
    alert(data.error || 'Failed to start batch');
    return;
  }
  currentJobId = data.job_id;
  if (polling) clearInterval(polling);
  polling = setInterval(pollStatus, 1000);
  await pollStatus();
}

async function pollStatus() {
  if (!currentJobId) return;
  const res = await fetch('/api/status?job_id=' + encodeURIComponent(currentJobId));
  const data = await res.json();
  const percent = data.percent || 0;
  setStatus((data.stage || data.status || 'Running') + ' · ' + (data.message || ''), percent);
  document.getElementById('logs').textContent = (data.logs || []).join('\n') || 'No logs yet.';
  document.getElementById('summary').textContent = data.summary_text || 'Generating...';
  document.getElementById('markdown').value = data.markdown || '';
  renderResultLinks(data.results || []);

  if (data.status === 'done') {
    clearInterval(polling);
    polling = null;
    document.getElementById('startBtn').disabled = false;
    document.getElementById('previewBtn').disabled = !(data.results || []).length;
    document.getElementById('publishBtn').disabled = !(data.results || []).length;
    setStatus('Done · Batch completed', 100);
  }
  if (data.status === 'failed') {
    clearInterval(polling);
    polling = null;
    document.getElementById('startBtn').disabled = false;
    document.getElementById('summary').textContent = 'Failed\n' + (data.error || 'Unknown error');
    setStatus('Failed', 0);
  }
}

function openFirstPreview() {
  if (!currentJobId) return;
  window.open('/preview?job_id=' + encodeURIComponent(currentJobId) + '&index=0', '_blank');
}

async function publishToCms() {
  if (!currentJobId) return;
  document.getElementById('publishBtn').disabled = true;
  document.getElementById('publishStatus').textContent = 'Publishing all generated markdown files...';
  const res = await fetch('/api/publish', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({job_id: currentJobId})
  });
  const data = await res.json();
  document.getElementById('publishStatus').textContent = data.message || JSON.stringify(data);
  document.getElementById('publishBtn').disabled = false;
  await pollStatus();
}
</script>
</body>
</html>
"""


def _json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler: BaseHTTPRequestHandler, body: str, status: int = 200) -> None:
    encoded = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _text_response(handler: BaseHTTPRequestHandler, body: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
    encoded = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _read_request_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(length).decode("utf-8") if length else "{}"
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {key: values[-1] for key, values in parse_qs(raw).items()}


def _safe_job(job_id: str) -> dict | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def _update_job(job_id: str, **updates) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)


def _append_log(job_id: str, message: str) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].setdefault("logs", []).append(message)


def _progress(job_id: str, base: int = 0, span: int = 100):
    def _callback(stage: str, percent: int, message: str) -> None:
        overall = base + int(max(0, min(100, percent)) * span / 100)
        _update_job(job_id, stage=stage, percent=overall, message=message)
        _append_log(job_id, f"[{stage}] {message}")
    return _callback


def _parse_tasks(payload: dict) -> list[dict]:
    raw_tasks = payload.get("tasks") or []
    tasks: list[dict] = []
    for item in raw_tasks:
        keyword = str(item.get("keyword", "")).strip()
        if not keyword:
            continue
        try:
            category_id = int(str(item.get("category_id", "")).strip())
        except ValueError as exc:
            raise ValueError(f"Invalid category_id for keyword {keyword}") from exc
        category_name = str(item.get("category_name", "")).strip()
        tasks.append({"keyword": keyword, "category_id": category_id, "category_name": category_name})
    return tasks


def _run_batch_generation(job_id: str, tasks: list[dict]) -> None:
    try:
        total = len(tasks)
        results: list[dict] = []
        combined_markdown_parts: list[str] = []
        _update_job(job_id, status="running", stage="Starting", percent=5, message=f"Batch started: {total} keywords")

        for index, task in enumerate(tasks, start=1):
            keyword = task["keyword"]
            category_id = task["category_id"]
            category_name = task.get("category_name") or f"Category {category_id}"
            base = 5 + int((index - 1) * 90 / total)
            span = max(1, int(90 / total))
            _append_log(job_id, f"[Batch] {index}/{total} · category {category_id} · {keyword}")
            _update_job(job_id, stage="Batch", percent=base, message=f"Generating {index}/{total}: {keyword}")

            result: PipelineResult = CONTROLLER.run_generation(
                keyword,
                category_id=category_id,
                keyword_id=None,
                progress=_progress(job_id, base=base, span=span),
            )
            markdown = result.markdown_path.read_text(encoding="utf-8")
            item = {
                "index": index - 1,
                "keyword": keyword,
                "category_id": category_id,
                "category_name": category_name,
                "title": result.title,
                "description": result.description,
                "markdown_path": str(result.markdown_path),
                "preview_path": str(result.preview_path),
            }
            results.append(item)
            combined_markdown_parts.append(f"<!-- {index}. {keyword} · category {category_id} -->\n\n{markdown}")
            summary_text = _build_summary_text(results, total)
            _update_job(job_id, results=results, summary_text=summary_text, markdown="\n\n\n".join(combined_markdown_parts))
            _append_log(job_id, f"[Done] {keyword} -> {result.markdown_path}")

        _update_job(
            job_id,
            status="done",
            stage="Done",
            percent=100,
            message=f"Batch completed: {len(results)}/{total} generated",
            results=results,
            summary_text=_build_summary_text(results, total),
            markdown="\n\n\n".join(combined_markdown_parts),
        )
    except Exception as error:
        tb = traceback.format_exc()
        _update_job(job_id, status="failed", stage="Failed", percent=0, message=str(error), error=f"{error}\n\n{tb}")
        _append_log(job_id, f"[Failed] {error}")
        _append_log(job_id, tb)


def _build_summary_text(results: list[dict], total: int) -> str:
    lines = [f"Generated {len(results)}/{total} articles", ""]
    for item in results:
        lines.append(f"{item['index'] + 1}. [{item['category_id']}] {item['keyword']}")
        lines.append(f"   Title: {item.get('title', '')}")
        lines.append(f"   Markdown: {item.get('markdown_path', '')}")
        lines.append(f"   Preview: {item.get('preview_path', '')}")
    return "\n".join(lines)


class BrowserUIHandler(BaseHTTPRequestHandler):
    server_version = "AnQiCMSBrowserUI/2.0"

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            _html_response(self, INDEX_HTML)
            return
        if parsed.path == "/api/status":
            qs = parse_qs(parsed.query)
            job_id = (qs.get("job_id") or [""])[0]
            job = _safe_job(job_id)
            if not job:
                _json_response(self, {"error": "job not found"}, status=404)
                return
            _json_response(self, job)
            return
        if parsed.path == "/preview":
            qs = parse_qs(parsed.query)
            job_id = (qs.get("job_id") or [""])[0]
            index_raw = (qs.get("index") or ["0"])[0]
            try:
                index = int(index_raw)
            except ValueError:
                index = 0
            job = _safe_job(job_id)
            results = job.get("results", []) if job else []
            if not results or index < 0 or index >= len(results):
                _html_response(self, "<h1>Preview not available</h1>", status=404)
                return
            path = Path(results[index]["preview_path"])
            if not path.exists():
                _html_response(self, "<h1>Preview file not found</h1>", status=404)
                return
            _text_response(self, path.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")
            return
        _json_response(self, {"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/api/generate_batch", "/api/generate"}:
            payload = _read_request_json(self)
            try:
                if parsed.path == "/api/generate":
                    keyword = str(payload.get("keyword", "")).strip()
                    if not keyword:
                        _json_response(self, {"error": "keyword is required"}, status=400)
                        return
                    category_id = int(str(payload.get("category_id", DEFAULT_CATEGORY_IDS[0])).strip())
                    tasks = [{"keyword": keyword, "category_id": category_id, "category_name": "Single"}]
                else:
                    tasks = _parse_tasks(payload)
                if not tasks:
                    _json_response(self, {"error": "No keywords found"}, status=400)
                    return
            except ValueError as error:
                _json_response(self, {"error": str(error)}, status=400)
                return

            job_id = uuid.uuid4().hex
            with JOBS_LOCK:
                JOBS[job_id] = {
                    "job_id": job_id,
                    "status": "queued",
                    "stage": "Queued",
                    "percent": 5,
                    "message": f"Queued {len(tasks)} keywords",
                    "tasks": tasks,
                    "logs": [f"[{datetime.now().isoformat(timespec='seconds')}] Queued {len(tasks)} keywords"],
                    "results": [],
                    "markdown": "",
                    "summary_text": f"Queued {len(tasks)} keywords...",
                }
            threading.Thread(target=_run_batch_generation, args=(job_id, tasks), daemon=True).start()
            _json_response(self, {"job_id": job_id})
            return

        if parsed.path == "/api/publish":
            payload = _read_request_json(self)
            job_id = str(payload.get("job_id", "")).strip()
            job = _safe_job(job_id)
            if not job:
                _json_response(self, {"error": "job not found"}, status=404)
                return
            results = job.get("results", [])
            if job.get("status") != "done" or not results:
                _json_response(self, {"error": "articles are not ready"}, status=400)
                return
            publish_results = []
            try:
                for index, item in enumerate(results, start=1):
                    markdown_path = Path(item["markdown_path"])
                    _append_log(job_id, f"[Publish] {index}/{len(results)} · {markdown_path.name}")
                    result = CONTROLLER.publish_existing(markdown_path, progress=_progress(job_id, base=0, span=100))
                    publish_results.append({"keyword": item.get("keyword"), "markdown_path": str(markdown_path), "result": result})
                message = f"Publish finished: {len(publish_results)}/{len(results)} attempted."
                _append_log(job_id, message)
                _json_response(self, {"ok": True, "message": message, "results": publish_results})
            except Exception as error:
                tb = traceback.format_exc()
                _append_log(job_id, tb)
                _json_response(self, {"ok": False, "message": f"Publish failed: {error}", "traceback": tb}, status=500)
            return

        _json_response(self, {"error": "not found"}, status=404)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start AnQiCMS browser batch UI")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the browser")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), BrowserUIHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"AnQiCMS Batch Generator running at {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
