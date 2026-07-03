#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daily cleanup for stale generated article artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil


@dataclass(frozen=True)
class CleanupSummary:
    removed_files: int
    removed_directories: int


def cleanup_generated_outputs(workspace_root: Path) -> CleanupSummary:
    """Remove all previously generated artifacts before a new run."""
    removed_files = 0
    removed_directories = 0

    for path in sorted(workspace_root.iterdir()):
        if not _is_generated_artifact(path):
            continue
        if path.is_dir():
            shutil.rmtree(path)
            removed_directories += 1
        elif path.is_file():
            path.unlink()
            removed_files += 1

    return CleanupSummary(
        removed_files=removed_files,
        removed_directories=removed_directories,
    )


def _is_generated_artifact(path: Path) -> bool:
    if path.name == "generated_media":
        return True
    if path.is_dir() and re.fullmatch(r"industry_\d+(?:_[a-z0-9-]+)?", path.name):
        return True
    if not path.name.startswith("ui_"):
        return False
    return path.suffix in {".md", ".html", ".json"}

