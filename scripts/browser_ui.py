#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Browser-based local UI for AnQiCMS article generation.

Run:
    python3 scripts/browser_ui.py

Then open:
    http://127.0.0.1:8765

This avoids macOS Tkinter rendering issues by using a standard local HTTP
server and browser UI. It uses only Python standard library modules plus the
existing project pipeline.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import html
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

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
CONTROLLER = EditorialPipelineController(WORKSPACE_ROOT, output_root=OUTPUT_ROOT)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AnQiCMS Browser Generator</title>
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
    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    .wrap { max-width: 1280px; margin: 0 auto; padding: 24px; }
    .header { margin-bottom: 18px; }
    h1 { margin: 0; font-size: 24px; line-height: 1.2; }
    .sub { margin-top: 6px; color: var(--muted); font-size: 14px; }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px;
      box-shadow: 0 8px 24px rgba(17,24,39,0.06);
    }
    .form-grid {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) 120px 140px 160px;
      gap: 12px;
      align-items: end;
    }
    label { display: block; font-weight: 700; font-size: 13px; margin-bottom: 6px; }
    input {
      width: 100%;
      height: 42px;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0 12px;
      font-size: 15px;
      outline: none;
      background: #fff;
    }
    input:focus { border-color: var(--black); }
    button {
      height: 42px;
      border: 0;
      border-radius: 10px;
      padding: 0 14px;
      font-size: 14px;
      font-weight: 700;
      background: var(--black);
      color: #fff;
      cursor: pointer;
    }
    button.secondary { background: #374151; }
    button.blue { background: var(--blue); }
    button.green { background: var(--green); }
    button:disabled { background: #9ca3af; cursor: not-allowed; }
    .status-row { margin-top: 14px; display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center; }
    .status { font-weight: 700; }
    .progress { width: 100%; height: 12px; background: #e5e7eb; border-radius: 99px; overflow: hidden; margin-top: 8px; }
    .bar { height: 100%; width: 0%; background: var(--black); transition: width .25s ease; }
    .main { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
    .panel-title { margin: 0 0 10px; font-size: 15px; font-weight: 800; }
    pre, textarea {
      width: 100%;
      min-height: 520px;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: #fff;
      color: var(--text);
      padding: 14px;
      white-space: pre-wrap;
      word-break: break-word;
      overflow: auto;
      font-family: Menlo, Consolas, monospace;
      font-size: 13px;
      line-height: 1.55;
      margin: 0;
    }
    textarea { resize: vertical; }
    .summary {
      min-height: 120px;
      max-height: 180px;
      margin-bottom: 12px;
    }
    .tiny { color: var(--muted); font-size: 12px; margin-top: 8px; }
    .err { color: var(--red); font-weight: 700; }
    .ok { color: var(--green); font-weight: 700; }
    @media (max-width: 900px) {
      .form-grid { grid-template-columns: 1fr; }
      .status-row { grid-template-columns: 1fr; }
      .main { grid-template-columns: 1fr; }
      pre, textarea { min-height: 320px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <h1>AnQiCMS Browser Generator</h1>
      <div class="sub">Browser UI · editorial segmented generation · markdown preview · CMS import</div>
    </div>

    <div class="card">
      <div class="form-grid">
        <div>
          <label for="keyword">Keyword</label>
          <input id="keyword" value="mounjaro weight loss" placeholder="Enter keyword" />
        </div>
        <div>
          <label for="category">Category ID</label>
          <input id="category" value="1" />
        </div>
        <div>
          <label for="keywordId">Keyword ID</label>
          <input id="keywordId" placeholder="optional" />
        </div>
        <button id="startBtn" onclick="startGeneration()">Start generation</button>
      </div>
      <div class="status-row">
        <div>
          <div id="status" class="status">Idle</div>
          <div class="progress"><div id="bar" class="bar"></div></div>
        </div>
        <button id="previewBtn" class="blue" onclick="openPreview()" disabled>Open Preview</button>
        <button id="publishBtn" class="green" onclick="publishToCms()" disabled>Import to CMS</button>
      </div>
      <div id="publishStatus" class="tiny">Publish status: not started</div>
    </div>

    <div class="main">
      <div class="card">
        <div class="panel-title">Logs</div>
        <pre id="logs">Waiting...</pre>
      </div>
      <div class="card">
        <div class="panel-title">Result Summary</div>
        <pre id="summary" class="summary">No article generated yet.</pre>
        <div class="panel-title">Markdown Preview</div>
        <textarea id="markdown" readonly></textarea>
      </div>
    </div>
  </div>

<script>
let currentJobId = null;
let polling = null;

function setStatus(text, percent) {
  document.getElementById('status').textContent = text;
  document.getElementById('bar').style.width = Math.max(0, Math.min(100, percent || 0)) + '%';
}

async function startGeneration() {
  const keyword = document.getElementById('keyword').value.trim();
  const category_id = document.getElementById('category').value.trim();
  const keyword_id = document.getElementById('keywordId').value.trim();
  if (!keyword) {
    alert('Please enter a keyword.');
    return;
  }
  document.getElementById('startBtn').disabled = true;
  document.getElementById('previewBtn').disabled = true;
  document.getElementById('publishBtn').disabled = true;
  document.getElementById('logs').textContent = 'Starting...';
  document.getElementById('summary').textContent = 'Generating...';
  document.getElementById('markdown').value = '';
  document.getElementById('publishStatus').textContent = 'Publish status: not started';
  setStatus('Queued', 5);

  const res = await fetch('/api/generate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({keyword, category_id, keyword_id})
  });
  const data = await res.json();
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

  if (data.status === 'done') {
    clearInterval(polling);
    polling = null;
    document.getElementById('startBtn').disabled = false;
    document.getElementById('previewBtn').disabled = false;
    document.getElementById('publishBtn').disabled = false;
    setStatus('Done · Generation completed', 100);
  }
  if (data.status === 'failed') {
    clearInterval(polling);
    polling = null;
    document.getElementById('startBtn').disabled = false;
    document.getElementById('summary').innerHTML = '<span class="err">Failed</span>\n' + (data.error || 'Unknown error');
    setStatus('Failed', 0);
  }
}

function openPreview() {
  if (!currentJobId) return;
  window.open('/preview?job_id=' + encodeURIComponent(currentJobId), '_blank');
}

async function publishToCms() {
  if (!currentJobId) return;
  document.getElementById('publishBtn').disabled = true;
  document.getElementById('publishStatus').textContent = 'Publishing...';
  const res = await fetch('/api/publish', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({job_id: currentJobId})
  });
  const data = await res.json();
  document.getElementById('publishStatus').textContent = data.message || JSON.stringify(data);
  document.getElementById('publishBtn').disabled = false;
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


def _progress(job_id: str):
    def _callback(stage: str, percent: int, message: str) -> None:
        _update_job(job_id, stage=stage, percent=percent, message=message)
        _append_log(job_id, f"[{stage}] {message}")
    return _callback


def _run_generation(job_id: str, keyword: str, category_id: int | None, keyword_id: int | None) -> None:
    try:
        _update_job(job_id, status="running", stage="Starting", percent=10, message="Generation started")
        result: PipelineResult = CONTROLLER.run_generation(
            keyword,
            category_id=category_id,
            keyword_id=keyword_id,
            progress=_progress(job_id),
        )
        markdown = result.markdown_path.read_text(encoding="utf-8")
        summary_text = (
            f"Title: {result.title}\n"
            f"Description: {result.description}\n"
            f"Markdown: {result.markdown_path}\n"
            f"Preview: {result.preview_path}\n"
            f"Finished: {datetime.now().isoformat(timespec='seconds')}"
        )
        _update_job(
            job_id,
            status="done",
            stage="Done",
            percent=100,
            message="Generation completed",
            result=result,
            markdown=markdown,
            summary_text=summary_text,
            markdown_path=str(result.markdown_path),
            preview_path=str(result.preview_path),
        )
        _append_log(job_id, f"[Done] Markdown saved: {result.markdown_path}")
    except Exception as error:
        tb = traceback.format_exc()
        _update_job(
            job_id,
            status="failed",
            stage="Failed",
            percent=0,
            message=str(error),
            error=f"{error}\n\n{tb}",
        )
        _append_log(job_id, f"[Failed] {error}")
        _append_log(job_id, tb)


class BrowserUIHandler(BaseHTTPRequestHandler):
    server_version = "AnQiCMSBrowserUI/1.0"

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
            payload = {k: v for k, v in job.items() if k != "result"}
            _json_response(self, payload)
            return
        if parsed.path == "/preview":
            qs = parse_qs(parsed.query)
            job_id = (qs.get("job_id") or [""])[0]
            job = _safe_job(job_id)
            if not job or not job.get("preview_path"):
                _html_response(self, "<h1>Preview not available</h1>", status=404)
                return
            path = Path(job["preview_path"])
            if not path.exists():
                _html_response(self, "<h1>Preview file not found</h1>", status=404)
                return
            _text_response(self, path.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")
            return
        _json_response(self, {"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/generate":
            payload = _read_request_json(self)
            keyword = str(payload.get("keyword", "")).strip()
            if not keyword:
                _json_response(self, {"error": "keyword is required"}, status=400)
                return
            try:
                category_raw = str(payload.get("category_id", "")).strip()
                category_id = int(category_raw) if category_raw else None
            except ValueError:
                _json_response(self, {"error": "category_id must be an integer"}, status=400)
                return
            try:
                keyword_id_raw = str(payload.get("keyword_id", "")).strip()
                keyword_id = int(keyword_id_raw) if keyword_id_raw else None
            except ValueError:
                _json_response(self, {"error": "keyword_id must be an integer"}, status=400)
                return

            job_id = uuid.uuid4().hex
            with JOBS_LOCK:
                JOBS[job_id] = {
                    "job_id": job_id,
                    "status": "queued",
                    "stage": "Queued",
                    "percent": 5,
                    "message": "Queued",
                    "keyword": keyword,
                    "logs": [f"[{datetime.now().isoformat(timespec='seconds')}] Queued keyword: {keyword}"],
                    "markdown": "",
                    "summary_text": "Queued...",
                }
            thread = threading.Thread(target=_run_generation, args=(job_id, keyword, category_id, keyword_id), daemon=True)
            thread.start()
            _json_response(self, {"job_id": job_id})
            return

        if parsed.path == "/api/publish":
            payload = _read_request_json(self)
            job_id = str(payload.get("job_id", "")).strip()
            job = _safe_job(job_id)
            if not job:
                _json_response(self, {"error": "job not found"}, status=404)
                return
            if job.get("status") != "done" or not job.get("markdown_path"):
                _json_response(self, {"error": "article is not ready"}, status=400)
                return
            try:
                markdown_path = Path(job["markdown_path"])
                result = CONTROLLER.publish_existing(markdown_path, progress=_progress(job_id))
                message = (
                    f"Publish status: ok={result.get('ok')} · HTTP={result.get('http_status')} · "
                    f"API={result.get('api_code')} · ID={result.get('remote_id')} · {result.get('message')}"
                )
                _append_log(job_id, message)
                _json_response(self, {"ok": True, "message": message, "result": result})
            except Exception as error:
                tb = traceback.format_exc()
                _append_log(job_id, tb)
                _json_response(self, {"ok": False, "message": f"Publish failed: {error}", "traceback": tb}, status=500)
            return

        _json_response(self, {"error": "not found"}, status=404)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start AnQiCMS browser UI")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the browser")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), BrowserUIHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"AnQiCMS Browser Generator running at {url}")
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
