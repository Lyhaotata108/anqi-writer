#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Browser-based local UI for AnQiCMS sample-style article generation.

Run:
    python3 scripts/browser_ui.py

Then open:
    http://127.0.0.1:8765

Batch flow:
    keywords -> cleanup/classification/router -> sample-style AI writer -> repair -> quality guard -> preview -> CMS import
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import uuid
import webbrowser

from article_type_router import route_article_type
from editorial_pipeline_controller import EditorialPipelineController
from intent_classifier import classify_keyword
from keyword_cleaner import clean_keyword
from quality_guard import evaluate_markdown
from sample_style_writer import generate_sample_style_article


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
WORKSPACE_ROOT = Path("/Users/hjg/Documents/anqicms-writer")
OUTPUT_ROOT = WORKSPACE_ROOT
QUALITY_MIN_SCORE = 85

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
CONTROLLER = EditorialPipelineController(WORKSPACE_ROOT, output_root=OUTPUT_ROOT)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AnQiCMS Sample Style Generator</title>
  <style>
    *{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f3f4f6;color:#111827}.wrap{max-width:1380px;margin:0 auto;padding:24px}.card{background:#fff;border:1px solid #d1d5db;border-radius:14px;padding:18px;box-shadow:0 8px 24px rgba(17,24,39,.06)}h1{margin:0 0 6px;font-size:24px}.sub,.tiny{color:#6b7280;font-size:13px;line-height:1.5}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:18px}.bucket{border:1px solid #d1d5db;border-radius:12px;padding:14px}.bucket-head{display:grid;grid-template-columns:1fr 90px;gap:10px;align-items:end;margin-bottom:10px}label{display:block;font-weight:700;font-size:13px;margin-bottom:6px}input,textarea{width:100%;border:1px solid #d1d5db;border-radius:10px;padding:10px 12px;font-size:14px;outline:none}input{height:40px}textarea{min-height:150px;resize:vertical;font-family:Menlo,Consolas,monospace;line-height:1.45}button{height:42px;border:0;border-radius:10px;padding:0 14px;font-weight:700;color:#fff;background:#111827;cursor:pointer}button.secondary{background:#374151}button.blue{background:#1d4ed8}button.green{background:#166534}button:disabled{background:#9ca3af;cursor:not-allowed}.actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:14px}.status-row{display:grid;grid-template-columns:1fr auto auto;gap:10px;align-items:center;margin-top:14px}.progress{width:100%;height:12px;background:#e5e7eb;border-radius:99px;overflow:hidden;margin-top:8px}.bar{height:100%;width:0%;background:#111827;transition:width .25s ease}.main{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}pre,.markdown-box{width:100%;min-height:480px;border:1px solid #d1d5db;border-radius:12px;background:#fff;padding:14px;white-space:pre-wrap;word-break:break-word;overflow:auto;font-family:Menlo,Consolas,monospace;font-size:13px;line-height:1.55;margin:0}.summary{min-height:170px;max-height:260px;margin-bottom:12px}.links{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}.link{display:inline-block;padding:6px 9px;border-radius:8px;background:#eef2ff;color:#1d4ed8;text-decoration:none;font-size:12px;font-weight:700}.link.warn{background:#fef3c7;color:#92400e}.link.fail{background:#fee2e2;color:#991b1b}@media(max-width:1000px){.grid,.main,.status-row{grid-template-columns:1fr}pre,.markdown-box{min-height:320px}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>AnQiCMS Sample Style Generator</h1>
      <div class="sub">Category mapping: 1 减肥药 · 5 CBD · 9 Blood · sample-style AI writer · intent router · quality guard · YouTube placeholder · CMS import</div>
      <div class="grid">
        <div class="bucket"><div class="bucket-head"><div><label>Category 1 Name</label><input id="catName1" value="减肥药" /></div><div><label>ID</label><input id="catId1" value="1" /></div></div><label>Keywords, one per line</label><textarea id="keywords1" placeholder="metabolism boosters for women over 40&#10;top 10 green tea for weight loss"></textarea></div>
        <div class="bucket"><div class="bucket-head"><div><label>Category 2 Name</label><input id="catName2" value="CBD" /></div><div><label>ID</label><input id="catId2" value="5" /></div></div><label>Keywords, one per line</label><textarea id="keywords2" placeholder="cbd gummies for sleep&#10;cbd oil side effects"></textarea></div>
        <div class="bucket"><div class="bucket-head"><div><label>Category 3 Name</label><input id="catName3" value="Blood" /></div><div><label>ID</label><input id="catId3" value="9" /></div></div><label>Keywords, one per line</label><textarea id="keywords3" placeholder="blood sugar after eating&#10;cholesterol symptoms"></textarea></div>
      </div>
      <div class="actions">
        <button id="startBtn" onclick="startBatchGeneration()">Start Test Generation</button>
        <button class="secondary" onclick="fillDemo()">Fill Demo</button>
        <button class="secondary" onclick="clearAll()">Clear</button>
        <span class="tiny">现在建议先测 5-10 个词；AI 会按样本文风完整成稿，导入格式不变。</span>
      </div>
      <div class="status-row">
        <div><div id="status"><b>Idle</b></div><div class="progress"><div id="bar" class="bar"></div></div></div>
        <button id="previewBtn" class="blue" onclick="openFirstPreview()" disabled>Open First Preview</button>
        <button id="publishBtn" class="green" onclick="publishToCms()" disabled>Import All to CMS</button>
      </div>
      <div id="publishStatus" class="tiny">Publish status: not started</div>
      <div id="resultLinks" class="links"></div>
    </div>
    <div class="main">
      <div class="card"><h3>Logs</h3><pre id="logs">Waiting...</pre></div>
      <div class="card"><h3>Result Summary</h3><pre id="summary" class="summary">No articles generated yet.</pre><h3>Markdown Preview</h3><textarea id="markdown" class="markdown-box" readonly></textarea></div>
    </div>
  </div>
<script>
let currentJobId=null;let polling=null;
function lines(text){return text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean)}
function setStatus(text,percent){document.getElementById('status').textContent=text;document.getElementById('bar').style.width=Math.max(0,Math.min(100,percent||0))+'%'}
function fillDemo(){document.getElementById('keywords1').value='metabolism boosters for women over 40\ntop 10 green tea for weight loss\nwhat does a dietitian do for weight loss';document.getElementById('keywords2').value='cbd gummies for sleep\ncbd oil side effects';document.getElementById('keywords3').value='blood sugar after eating'}
function clearAll(){['keywords1','keywords2','keywords3'].forEach(id=>document.getElementById(id).value='')}
function collectTasks(){const tasks=[];[1,2,3].forEach(i=>{const category_id=document.getElementById('catId'+i).value.trim();const category_name=document.getElementById('catName'+i).value.trim();lines(document.getElementById('keywords'+i).value).forEach(keyword=>tasks.push({keyword,category_id,category_name}))});return tasks}
function renderResultLinks(results){const box=document.getElementById('resultLinks');box.innerHTML='';(results||[]).forEach((item,index)=>{const a=document.createElement('a');a.className='link';if(item.quality_passed===false)a.className+=' fail';else if((item.quality_score||0)<90)a.className+=' warn';a.href='/preview?job_id='+encodeURIComponent(currentJobId)+'&index='+index;a.target='_blank';a.textContent=(index+1)+'. '+item.keyword+' · '+(item.article_type||'type')+' · Q'+(item.quality_score||'?');box.appendChild(a)})}
async function startBatchGeneration(){const tasks=collectTasks();if(!tasks.length){alert('Please paste at least one keyword.');return}document.getElementById('startBtn').disabled=true;document.getElementById('previewBtn').disabled=true;document.getElementById('publishBtn').disabled=true;document.getElementById('logs').textContent='Starting batch...';document.getElementById('summary').textContent='Queued '+tasks.length+' keywords...';document.getElementById('markdown').value='';document.getElementById('publishStatus').textContent='Publish status: not started';document.getElementById('resultLinks').innerHTML='';setStatus('Queued',5);const res=await fetch('/api/generate_batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tasks})});const data=await res.json();if(!res.ok){document.getElementById('startBtn').disabled=false;alert(data.error||'Failed to start batch');return}currentJobId=data.job_id;if(polling)clearInterval(polling);polling=setInterval(pollStatus,2000);await pollStatus()}
async function pollStatus(){if(!currentJobId)return;const res=await fetch('/api/status?job_id='+encodeURIComponent(currentJobId));const data=await res.json();setStatus((data.stage||data.status||'Running')+' · '+(data.message||''),data.percent||0);document.getElementById('logs').textContent=(data.logs||[]).join('\n')||'No logs yet.';document.getElementById('summary').textContent=data.summary_text||'Generating...';document.getElementById('markdown').value=data.markdown||'';renderResultLinks(data.results||[]);if(data.status==='done'||data.status==='failed'){clearInterval(polling);polling=null;document.getElementById('startBtn').disabled=false;document.getElementById('previewBtn').disabled=!(data.results||[]).length;document.getElementById('publishBtn').disabled=!(data.results||[]).length}}
function openFirstPreview(){if(currentJobId)window.open('/preview?job_id='+encodeURIComponent(currentJobId)+'&index=0','_blank')}
async function publishToCms(){if(!currentJobId)return;document.getElementById('publishBtn').disabled=true;document.getElementById('publishStatus').textContent='Publishing...';const res=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:currentJobId})});const data=await res.json();document.getElementById('publishStatus').textContent=data.message||JSON.stringify(data);document.getElementById('publishBtn').disabled=false;await pollStatus()}
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
    tasks: list[dict] = []
    for item in payload.get("tasks") or []:
        keyword = str(item.get("keyword", "")).strip()
        if not keyword:
            continue
        category_id = int(str(item.get("category_id", "")).strip())
        tasks.append({"keyword": keyword, "category_id": category_id, "category_name": str(item.get("category_name", "")).strip()})
    return tasks


def _quality_payload(markdown_path: Path) -> dict:
    report = evaluate_markdown(markdown_path, corpus_dir=OUTPUT_ROOT, min_score=QUALITY_MIN_SCORE)
    payload = asdict(report)
    payload["score"] = int(payload.get("score") or 0)
    payload["passed"] = bool(payload.get("passed"))
    return payload


def _run_batch_generation(job_id: str, tasks: list[dict]) -> None:
    try:
        total = len(tasks)
        results: list[dict] = []
        combined_markdown_parts: list[str] = []
        _update_job(job_id, status="running", stage="Starting", percent=5, message=f"Batch started: {total} keywords")
        for index, task in enumerate(tasks, start=1):
            raw_keyword = task["keyword"]
            category_id = task["category_id"]
            category_name = task.get("category_name") or f"Category {category_id}"
            base = 5 + int((index - 1) * 90 / total)
            span = max(1, int(90 / total))
            cleaned = clean_keyword(raw_keyword)
            _append_log(job_id, f"[Batch] {index}/{total} · category {category_id} · {raw_keyword}")
            _append_log(job_id, f"[Keyword] status={cleaned.keyword_status} · clean={cleaned.clean_keyword} · reason={cleaned.reason}")
            if cleaned.keyword_status in {"skip", "low_quality", "brand_unknown"}:
                item = {"index": index - 1, "keyword": raw_keyword, "category_id": category_id, "category_name": category_name, "article_type": "skipped", "quality_score": 0, "quality_passed": False, "quality_issues": [cleaned.reason], "quality_warnings": [], "quality_stats": {}, "markdown_path": "", "preview_path": "", "title": "Skipped", "description": ""}
                results.append(item)
                _update_job(job_id, results=results, summary_text=_build_summary_text(results, total), markdown="\n\n\n".join(combined_markdown_parts))
                continue
            classification = asdict(classify_keyword(cleaned.clean_keyword))
            route = asdict(route_article_type(cleaned.clean_keyword, classification))
            _append_log(job_id, f"[Route] type={route['article_type']} · entity={classification.get('entity')} · intent={classification.get('intent')} · reason={route.get('reason')}")
            result = generate_sample_style_article(cleaned.clean_keyword, WORKSPACE_ROOT, OUTPUT_ROOT, category_id, progress=_progress(job_id, base=base, span=max(1, span - 5)))
            markdown = result.markdown_path.read_text(encoding="utf-8")
            quality = _quality_payload(result.markdown_path)
            score = int(quality.get("score") or 0)
            passed = bool(quality.get("passed"))
            _append_log(job_id, f"[Quality {'PASS' if passed else 'REVIEW'}] {cleaned.clean_keyword} · score={score}")
            for issue in (quality.get("issues") or [])[:5]:
                _append_log(job_id, f"  - {issue}")
            item = {"index": index - 1, "keyword": cleaned.clean_keyword, "raw_keyword": raw_keyword, "category_id": category_id, "category_name": category_name, "article_type": route["article_type"], "classification": classification, "title": result.title, "description": result.description, "markdown_path": str(result.markdown_path), "preview_path": str(result.preview_path), "quality_score": score, "quality_passed": passed, "quality_issues": quality.get("issues") or [], "quality_warnings": quality.get("warnings") or [], "quality_stats": quality.get("stats") or {}}
            results.append(item)
            combined_markdown_parts.append(f"<!-- {index}. {cleaned.clean_keyword} · {route['article_type']} · category {category_id} · quality {score} -->\n\n{markdown}")
            _update_job(job_id, results=results, summary_text=_build_summary_text(results, total), markdown="\n\n\n".join(combined_markdown_parts))
            _append_log(job_id, f"[Done] {cleaned.clean_keyword} -> {result.markdown_path}")
        failed_quality = sum(1 for item in results if not item.get("quality_passed"))
        final_message = f"Batch completed: {len(results)}/{total} processed"
        if failed_quality:
            final_message += f" · review needed: {failed_quality}"
        _update_job(job_id, status="done", stage="Done", percent=100, message=final_message, results=results, summary_text=_build_summary_text(results, total), markdown="\n\n\n".join(combined_markdown_parts))
    except Exception as error:
        tb = traceback.format_exc()
        _update_job(job_id, status="failed", stage="Failed", percent=0, message=str(error), error=f"{error}\n\n{tb}")
        _append_log(job_id, f"[Failed] {error}")
        _append_log(job_id, tb)


def _build_summary_text(results: list[dict], total: int) -> str:
    passed = sum(1 for item in results if item.get("quality_passed"))
    failed = len(results) - passed
    lines = [f"Processed {len(results)}/{total} keywords", f"Quality: {passed} passed · {failed} needs review", ""]
    for item in results:
        status = "PASS" if item.get("quality_passed") else "REVIEW"
        lines.append(f"{item['index'] + 1}. [{item['category_id']}] {item['keyword']} · {item.get('article_type')} · Q{item.get('quality_score', '?')} · {status}")
        lines.append(f"   Title: {item.get('title', '')}")
        if item.get("markdown_path"):
            lines.append(f"   Markdown: {item.get('markdown_path', '')}")
            lines.append(f"   Preview: {item.get('preview_path', '')}")
        issues = item.get("quality_issues") or []
        if issues:
            lines.append("   Issues: " + " | ".join(str(issue) for issue in issues[:3]))
    return "\n".join(lines)


class BrowserUIHandler(BaseHTTPRequestHandler):
    server_version = "AnQiCMSSampleStyleUI/1.0"

    def log_message(self, format: str, *args) -> None:
        message = format % args
        if "GET /api/status?" in message:
            return
        print(f"[{self.log_date_time_string()}] {message}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            _html_response(self, INDEX_HTML)
            return
        if parsed.path == "/api/status":
            job_id = (parse_qs(parsed.query).get("job_id") or [""])[0]
            job = _safe_job(job_id)
            if not job:
                _json_response(self, {"error": "job not found"}, status=404)
                return
            _json_response(self, job)
            return
        if parsed.path == "/preview":
            qs = parse_qs(parsed.query)
            job_id = (qs.get("job_id") or [""])[0]
            try:
                index = int((qs.get("index") or ["0"])[0])
            except ValueError:
                index = 0
            job = _safe_job(job_id)
            results = job.get("results", []) if job else []
            if not results or index < 0 or index >= len(results) or not results[index].get("preview_path"):
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
                    tasks = [{"keyword": keyword, "category_id": int(payload.get("category_id", 1)), "category_name": "Single"}]
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
                JOBS[job_id] = {"job_id": job_id, "status": "queued", "stage": "Queued", "percent": 5, "message": f"Queued {len(tasks)} keywords", "tasks": tasks, "logs": [f"[{datetime.now().isoformat(timespec='seconds')}] Queued {len(tasks)} keywords"], "results": [], "markdown": "", "summary_text": f"Queued {len(tasks)} keywords..."}
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
            results = [item for item in job.get("results", []) if item.get("markdown_path")]
            if job.get("status") != "done" or not results:
                _json_response(self, {"error": "articles are not ready"}, status=400)
                return
            publish_results = []
            try:
                for index, item in enumerate(results, start=1):
                    if item.get("quality_passed") is False:
                        _append_log(job_id, f"[Publish Warning] {item.get('keyword')} quality score {item.get('quality_score')} needs review")
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
    parser = argparse.ArgumentParser(description="Start AnQiCMS sample-style browser UI")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the browser")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), BrowserUIHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"AnQiCMS Sample Style Generator running at {url}")
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
