#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local Tkinter UI for keyword-driven preview and CMS import.

This version intentionally uses plain tkinter widgets instead of ttk-heavy
styling. On some macOS/Tk combinations, themed ttk frames can open a normal
window title bar but render a blank content area. Plain tk widgets are more
predictable for this local utility.
"""

from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox
import traceback
import webbrowser

from editorial_pipeline_controller import EditorialPipelineController, PipelineResult


WORKSPACE_ROOT = Path("/Users/hjg/Documents/anqicms-writer")


class LocalPipelineUI:
    """Minimal GUI for local generation, preview, and CMS import."""

    BG = "#f3f4f6"
    CARD = "#ffffff"
    TEXT = "#111827"
    MUTED = "#6b7280"
    BORDER = "#d1d5db"
    BUTTON = "#111827"
    BUTTON_TEXT = "#ffffff"
    DISABLED = "#9ca3af"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AnQiCMS Local Generator")
        self.root.geometry("1180x760")
        self.root.minsize(980, 680)
        self.root.configure(bg=self.BG)
        self.controller = EditorialPipelineController(WORKSPACE_ROOT)
        self.current_result: PipelineResult | None = None
        self.stage_var = tk.StringVar(value="Stage: Idle")
        self.publish_status_var = tk.StringVar(value="Publish status: not started")
        self.keyword_var = tk.StringVar()
        self.category_var = tk.StringVar(value="1")
        self.keyword_id_var = tk.StringVar()
        self._build()
        self.root.after(100, lambda: self.append_log("UI loaded. Enter a keyword, then click Start generation."))

    def _label(self, parent: tk.Widget, text: str, size: int = 12, bold: bool = False, color: str | None = None) -> tk.Label:
        font = ("Arial", size, "bold" if bold else "normal")
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color or self.TEXT, font=font, anchor="w")

    def _entry(self, parent: tk.Widget, var: tk.StringVar, width: int = 20) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=var,
            width=width,
            bg="#ffffff",
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=self.BORDER,
        )

    def _button(self, parent: tk.Widget, text: str, command, disabled: bool = False) -> tk.Button:
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=self.BUTTON if not disabled else self.DISABLED,
            fg=self.BUTTON_TEXT,
            activebackground="#374151",
            activeforeground=self.BUTTON_TEXT,
            relief="flat",
            padx=14,
            pady=7,
            cursor="hand2",
            state="disabled" if disabled else "normal",
        )
        return btn

    def _set_button_state(self, btn: tk.Button, enabled: bool) -> None:
        btn.config(
            state="normal" if enabled else "disabled",
            bg=self.BUTTON if enabled else self.DISABLED,
        )

    def _build(self) -> None:
        shell = tk.Frame(self.root, bg=self.BG, padx=16, pady=16)
        shell.pack(fill="both", expand=True)

        header = tk.Frame(shell, bg=self.BG)
        header.pack(fill="x", pady=(0, 12))
        self._label(header, "AnQiCMS Local Generator", size=18, bold=True).pack(anchor="w")
        self._label(
            header,
            "Editorial segmented generation · expert-process style · local markdown preview · CMS import",
            size=11,
            color=self.MUTED,
        ).pack(anchor="w", pady=(3, 0))

        top = tk.Frame(shell, bg=self.CARD, padx=14, pady=14, highlightthickness=1, highlightbackground=self.BORDER)
        top.pack(fill="x")

        self._label(top, "Keyword", bold=True).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._entry(top, self.keyword_var, width=58).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(0, 10))

        self.start_btn = self._button(top, "Start generation", self.start_generation)
        self.start_btn.grid(row=0, column=4, sticky="ew", padx=(8, 0))

        self.preview_btn = self._button(top, "Open Preview", self.open_preview, disabled=True)
        self.preview_btn.grid(row=0, column=5, sticky="ew", padx=(8, 0))

        self._label(top, "Category ID").grid(row=1, column=0, sticky="w", pady=(10, 0), padx=(0, 8))
        self._entry(top, self.category_var, width=18).grid(row=1, column=1, sticky="w", pady=(10, 0), padx=(0, 10))

        self._label(top, "Keyword ID").grid(row=1, column=2, sticky="w", pady=(10, 0), padx=(0, 8))
        self._entry(top, self.keyword_id_var, width=18).grid(row=1, column=3, sticky="w", pady=(10, 0), padx=(0, 10))

        self.publish_btn = self._button(top, "Import to CMS", self.publish_to_cms, disabled=True)
        self.publish_btn.grid(row=1, column=4, columnspan=2, sticky="ew", pady=(10, 0), padx=(8, 0))

        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        status = tk.Frame(shell, bg=self.CARD, padx=14, pady=10, highlightthickness=1, highlightbackground=self.BORDER)
        status.pack(fill="x", pady=(12, 0))
        self._label(status, "Status", bold=True).pack(anchor="w")
        self.stage_label = tk.Label(status, textvariable=self.stage_var, bg=self.CARD, fg=self.TEXT, anchor="w")
        self.stage_label.pack(fill="x", pady=(4, 6))
        self.progress_canvas = tk.Canvas(status, height=12, bg="#e5e7eb", highlightthickness=0)
        self.progress_canvas.pack(fill="x")
        self._progress_percent = 0
        self.root.bind("<Configure>", lambda _event: self._draw_progress(self._progress_percent))

        middle = tk.Frame(shell, bg=self.BG)
        middle.pack(fill="both", expand=True, pady=(12, 12))
        middle.columnconfigure(0, weight=3)
        middle.columnconfigure(1, weight=2)
        middle.rowconfigure(0, weight=1)

        left_card = tk.Frame(middle, bg=self.CARD, padx=12, pady=12, highlightthickness=1, highlightbackground=self.BORDER)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._label(left_card, "Logs", bold=True).pack(anchor="w")
        self.log_text = tk.Text(left_card, height=28, wrap="word", bg="#ffffff", fg=self.TEXT, relief="solid", bd=1)
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))

        right_card = tk.Frame(middle, bg=self.CARD, padx=12, pady=12, highlightthickness=1, highlightbackground=self.BORDER)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._label(right_card, "Result Summary", bold=True).pack(anchor="w")
        self.summary_text = tk.Text(right_card, height=9, wrap="word", bg="#ffffff", fg=self.TEXT, relief="solid", bd=1)
        self.summary_text.pack(fill="x", pady=(8, 12))

        self._label(right_card, "Markdown Preview", bold=True).pack(anchor="w")
        self.markdown_text = tk.Text(right_card, height=18, wrap="word", bg="#ffffff", fg=self.TEXT, relief="solid", bd=1)
        self.markdown_text.pack(fill="both", expand=True, pady=(8, 0))

        footer = tk.Frame(shell, bg=self.BG)
        footer.pack(fill="x")
        tk.Label(footer, textvariable=self.publish_status_var, bg=self.BG, fg=self.TEXT, anchor="w", font=("Arial", 11, "bold")).pack(anchor="w")

    def _draw_progress(self, percent: int) -> None:
        self._progress_percent = max(0, min(100, int(percent)))
        if not hasattr(self, "progress_canvas"):
            return
        self.progress_canvas.delete("all")
        width = max(1, self.progress_canvas.winfo_width())
        height = max(1, self.progress_canvas.winfo_height())
        fill_width = int(width * self._progress_percent / 100)
        self.progress_canvas.create_rectangle(0, 0, width, height, fill="#e5e7eb", outline="")
        self.progress_canvas.create_rectangle(0, 0, fill_width, height, fill="#111827", outline="")

    def append_log(self, message: str) -> None:
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")

    def update_progress(self, stage: str, percent: int, message: str) -> None:
        def _apply() -> None:
            self.stage_var.set(f"Stage: {stage} · {message}")
            self._draw_progress(percent)
            self.append_log(f"[{stage}] {message}")
        self.root.after(0, _apply)

    def start_generation(self) -> None:
        keyword = self.keyword_var.get().strip()
        if not keyword:
            messagebox.showerror("Missing keyword", "Please enter a keyword.")
            return
        self._set_button_state(self.start_btn, False)
        self._set_button_state(self.publish_btn, False)
        self._set_button_state(self.preview_btn, False)
        self.current_result = None
        self.summary_text.delete("1.0", "end")
        self.markdown_text.delete("1.0", "end")
        self.publish_status_var.set("Publish status: not started")
        self.update_progress("Queued", 5, "Starting generation worker")
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
                self._set_button_state(self.preview_btn, True)
                self._set_button_state(self.publish_btn, True)
                self._set_button_state(self.start_btn, True)
                self.update_progress("Done", 100, "Generation completed")
            self.root.after(0, _apply)
        except Exception as error:
            tb = traceback.format_exc()

            def _fail() -> None:
                self.append_log(f"[Failed] {error}")
                self.append_log(tb)
                self.stage_var.set("Stage: Failed")
                self._draw_progress(0)
                self._set_button_state(self.start_btn, True)
            self.root.after(0, _fail)

    def open_preview(self) -> None:
        if not self.current_result:
            return
        webbrowser.open(self.current_result.preview_path.as_uri())

    def publish_to_cms(self) -> None:
        if not self.current_result:
            messagebox.showerror("Nothing to publish", "Generate an article first.")
            return
        self._set_button_state(self.publish_btn, False)
        thread = threading.Thread(target=self._publish_worker, daemon=True)
        thread.start()

    def _publish_worker(self) -> None:
        try:
            assert self.current_result is not None
            result = self.controller.publish_existing(self.current_result.markdown_path, progress=self.update_progress)

            def _apply() -> None:
                self.publish_status_var.set(
                    f"Publish status: ok={result.get('ok')} · HTTP={result.get('http_status')} · API={result.get('api_code')} · ID={result.get('remote_id')} · {result.get('message')}"
                )
                self._set_button_state(self.publish_btn, True)
            self.root.after(0, _apply)
        except Exception as error:
            tb = traceback.format_exc()

            def _fail() -> None:
                self.publish_status_var.set(f"Publish failed: {error}")
                self.append_log(tb)
                self._set_button_state(self.publish_btn, True)
            self.root.after(0, _fail)


def main() -> None:
    root = tk.Tk()
    app = LocalPipelineUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
