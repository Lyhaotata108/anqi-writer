#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local Tkinter UI for keyword-driven preview and CMS import."""

from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from pipeline_controller import PipelineController, PipelineResult


WORKSPACE_ROOT = Path("/Users/hjg/Documents/anqicms-writer")


class LocalPipelineUI:
    """Minimal GUI for local generation, preview, and CMS import."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AnQiCMS Local Generator")
        self.root.geometry("980x760")
        self.root.minsize(900, 680)
        self.controller = PipelineController(WORKSPACE_ROOT)
        self.current_result: PipelineResult | None = None
        self._configure_style()
        self._build()

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.root.configure(background="#f3f4f6")
        style.configure("Header.TLabel", font=("Arial", 16, "bold"), foreground="#111827", background="#f3f4f6")
        style.configure("Section.TLabel", font=("Arial", 11, "bold"), foreground="#111827")
        style.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("TLabel", foreground="#111827")
        style.configure("TButton", padding=6)

    def _build(self) -> None:
        shell = ttk.Frame(self.root, padding=12, style="Card.TFrame")
        shell.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(shell, text="AnQiCMS Local Generator", style="Header.TLabel").pack(anchor="w", pady=(0, 12))

        top = ttk.Frame(shell, padding=12, style="Card.TFrame")
        top.pack(fill="x")

        ttk.Label(top, text="Keyword", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.keyword_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.keyword_var, width=70).grid(row=0, column=1, columnspan=3, sticky="ew", padx=8)

        ttk.Label(top, text="Category ID").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.category_var = tk.StringVar(value="16")
        ttk.Entry(top, textvariable=self.category_var, width=18).grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))

        ttk.Label(top, text="Keyword ID").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.keyword_id_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.keyword_id_var, width=18).grid(row=1, column=3, sticky="w", padx=8, pady=(8, 0))

        self.start_btn = ttk.Button(top, text="Start generation", command=self.start_generation)
        self.start_btn.grid(row=0, column=4, padx=(12, 0))
        self.publish_btn = ttk.Button(top, text="Import to CMS", command=self.publish_to_cms, state="disabled")
        self.publish_btn.grid(row=1, column=4, padx=(12, 0), pady=(8, 0))
        self.preview_btn = ttk.Button(top, text="Open Preview", command=self.open_preview, state="disabled")
        self.preview_btn.grid(row=0, column=5, padx=(8, 0))

        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        status = ttk.Frame(shell, padding=(12, 12, 12, 0), style="Card.TFrame")
        status.pack(fill="x", pady=(12, 0))
        self.stage_var = tk.StringVar(value="Idle")
        ttk.Label(status, textvariable=self.stage_var).pack(anchor="w")
        self.progress = ttk.Progressbar(status, maximum=100)
        self.progress.pack(fill="x", pady=(6, 10))

        middle = ttk.PanedWindow(shell, orient="horizontal")
        middle.pack(fill="both", expand=True, padx=12, pady=(12, 12))

        left = ttk.Frame(middle)
        right = ttk.Frame(middle)
        middle.add(left, weight=3)
        middle.add(right, weight=2)

        ttk.Label(left, text="Logs", style="Section.TLabel").pack(anchor="w")
        self.log_text = tk.Text(left, height=28, wrap="word")
        self.log_text.pack(fill="both", expand=True)

        ttk.Label(right, text="Result Summary", style="Section.TLabel").pack(anchor="w")
        self.summary_text = tk.Text(right, height=12, wrap="word")
        self.summary_text.pack(fill="x")

        ttk.Label(right, text="Markdown Preview", style="Section.TLabel").pack(anchor="w", pady=(12, 0))
        self.markdown_text = tk.Text(right, height=18, wrap="word")
        self.markdown_text.pack(fill="both", expand=True)

        self.publish_status_var = tk.StringVar(value="Publish status: not started")
        ttk.Label(shell, textvariable=self.publish_status_var, padding=(12, 0, 12, 12), style="Section.TLabel").pack(anchor="w")

    def append_log(self, message: str) -> None:
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")

    def update_progress(self, stage: str, percent: int, message: str) -> None:
        def _apply() -> None:
            self.stage_var.set(f"Stage: {stage} · {message}")
            self.progress["value"] = percent
            self.append_log(f"[{stage}] {message}")
        self.root.after(0, _apply)

    def start_generation(self) -> None:
        keyword = self.keyword_var.get().strip()
        if not keyword:
            messagebox.showerror("Missing keyword", "Please enter a keyword.")
            return
        self.start_btn.config(state="disabled")
        self.publish_btn.config(state="disabled")
        self.preview_btn.config(state="disabled")
        self.current_result = None
        self.summary_text.delete("1.0", "end")
        self.markdown_text.delete("1.0", "end")
        self.publish_status_var.set("Publish status: not started")
        thread = threading.Thread(target=self._run_generation_worker, daemon=True)
        thread.start()

    def _run_generation_worker(self) -> None:
        try:
            category_id = int(self.category_var.get()) if self.category_var.get().strip() else None
            keyword_id = int(self.keyword_id_var.get()) if self.keyword_id_var.get().strip() else None
            result = self.controller.run_generation(
                self.keyword_var.get().strip(),
                category_id=category_id,
                keyword_id=keyword_id,
                progress=self.update_progress,
            )
            self.current_result = result
            markdown = result.markdown_path.read_text(encoding="utf-8")
            def _apply() -> None:
                self.summary_text.insert("end", f"Title: {result.title}\n")
                self.summary_text.insert("end", f"Description: {result.description}\n")
                self.summary_text.insert("end", f"Markdown: {result.markdown_path}\n")
                self.summary_text.insert("end", f"Preview: {result.preview_path}\n")
                self.markdown_text.insert("end", markdown)
                self.preview_btn.config(state="normal")
                self.publish_btn.config(state="normal")
                self.start_btn.config(state="normal")
            self.root.after(0, _apply)
        except Exception as error:
            def _fail() -> None:
                self.append_log(f"[Failed] {error}")
                self.stage_var.set("Stage: Failed")
                self.start_btn.config(state="normal")
            self.root.after(0, _fail)

    def open_preview(self) -> None:
        if not self.current_result:
            return
        webbrowser.open(self.current_result.preview_path.as_uri())

    def publish_to_cms(self) -> None:
        if not self.current_result:
            messagebox.showerror("Nothing to publish", "Generate an article first.")
            return
        self.publish_btn.config(state="disabled")
        thread = threading.Thread(target=self._publish_worker, daemon=True)
        thread.start()

    def _publish_worker(self) -> None:
        assert self.current_result is not None
        result = self.controller.publish_existing(self.current_result.markdown_path, progress=self.update_progress)
        def _apply() -> None:
            self.publish_status_var.set(
                f"Publish status: ok={result.get('ok')} · HTTP={result.get('http_status')} · API={result.get('api_code')} · ID={result.get('remote_id')} · {result.get('message')}"
            )
            self.publish_btn.config(state="normal")
        self.root.after(0, _apply)


def main() -> None:
    root = tk.Tk()
    app = LocalPipelineUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
