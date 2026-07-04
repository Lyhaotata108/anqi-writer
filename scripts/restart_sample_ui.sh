#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/4] Stopping old browser_ui.py processes..."
pkill -f "scripts/browser_ui.py" 2>/dev/null || true
sleep 1

echo "[2/4] Checking writer mode..."
python3 scripts/self_check_writer_mode.py

echo "[3/4] Compiling key scripts..."
python3 -m py_compile \
  scripts/keyword_cleaner.py \
  scripts/article_type_router.py \
  scripts/sample_style_writer.py \
  scripts/article_repair.py \
  scripts/youtube_finder.py \
  scripts/browser_ui.py

echo "[4/4] Starting Sample Style UI..."
python3 scripts/browser_ui.py
