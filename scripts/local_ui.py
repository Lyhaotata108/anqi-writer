#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local Tkinter UI for keyword-driven preview and CMS import.

This UI uses direct fixed-position tkinter placement instead of nested ttk,
pack, grid, or paned layouts. Some macOS system Tk builds can show a normal
window but fail to lay out nested themed widgets correctly. Fixed placement is
less elegant, but it is the most predictable for this local utility.
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
        self.root.option_add("*Font", "Arial 12")

        self.controller = EditorialPipelineController(WORKSPACE_ROOT)
        self.current_result: PipelineResult | None = None

        self.keyword_var = tk.StringVar()
        self.category_var = tk.StringVar(value="1")
        self.keyword_id_var = tk.StringVar()
        self.stage_var = tk.StringVar(value="Stage: Idle")
        self.publish_status_var = tk.StringVar(value="Publish status: not started")
        self._progress_percent = 0

        self._build_fixed_ui()
        self.root.after(100, lambda: self.append_log("UI loaded. Enter a keyword, then click Start generation."))

    def _make_label(self, text: str, x: int, y: int, w: int, h: int = 24, size: int = 12, bold: bool = False, color: str | None = None) -> tk.Label:
        label = tk.Label(
            self.root,
            text=text,
            bg=self.BG,
            fg=color or self.TEXT,
            anchor="w",
            font=("Arial", size, "bold" if bold else "normal"),
        )
        label.place(x=x, y=y, width=w, height=h)
        return label

    def _make_entry(self, var: tk.StringVar, x: int, y: int, w: int, h: int = 30) -> tk.Entry:
        entry = tk.Entry(
            self.root,
            textvariable=var,
            bg="#ffffff",
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=self.BORDER,
            highlightcolor="#111827",
        )
        entry.place(x=x, y=y, width=w, height=h)
        return entry

    def _make_button(self, text: str, command, x: int, y: int, w: int, h: int = 32, disabled: bool = False) -> tk.Button:
        btn = tk.Button(
            self.root,
            text=text,
            command=command,
            bg=self.BUTTON if not disabled else self.DISABLED,
            fg=self.BUTTON_TEXT,
            activebackground="#374151",
            activeforeground=self.BUTTON_TEXT,
            relief="flat",
            cursor="hand2",
            state="disabled" if disabled else "normal",
        )
        btn.place(x=x, y=y, width=w, height=h)
        return btn

    def _make_text(self, x: int, y: int, w: int, h: int) -> tk.Text:
        text = tk.Text(
            self.root,
            wrap="word",
            bg="#ffffff",
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=self.BORDER,
        )
        text.place(x=x, y=y, width=w, height=h)
        return text

    def _build_fixed_ui(self) -> None:
        # Header
        self._make_label("AnQiCMS Local Generator", 24, 18, 500, 28, size=18, bold=True)
        self._make_label(
            "Editorial segmented generation · expert-process style · local markdown preview · CMS import",
            24,
            48,
            720,
            22,
            size=11,
            color=self.MUTED,
        )

        # Input row
        self._make_label("Keyword", 24, 92, 90, 24, bold=True)
        self.keyword_entry = self._make_entry(self.keyword_var, 110, 88, 520, 32)

        self._make_label("Category ID", 650, 92, 100, 24, bold=True)
        self.category_entry = self._make_entry(self.category_var, 748, 88, 80, 32)

        self._make_label("Keyword ID", 848, 92, 92, 24, bold=True)
        self.keyword_id_entry = self._make_entry(self.keyword_id_var, 940, 88, 80, 32)

        self.start_btn = self._make_button("Start generation", self.start_generation, 1038, 86, 128, 34)

        # Secondary buttons
        self.preview_btn = self._make_button("Open Preview", self.open_preview, 1038, 128, 128, 34, disabled=True)
        self.publish_btn = self._make_button("Import to CMS", self.publish_to_cms, 890, 128, 138, 34, disabled=True)

        # Status
        self.stage_label = tk.Label(self.root, textvariable=self.stage_var, bg=self.BG, fg=self.TEXT, anchor="w", font=("Arial", 12, "bold"))
        self.stage_label.place(x=24, y=140, width=760, height=24)
        self.progress_canvas = tk.Canvas(self.root, bg="#e5e7eb", highlightthickness=0)
        self.progress_canvas.place(x=24, y=168, width=760, height=14)
        self._draw_progress(0)

        # Main panels
        self._make_label("Logs", 24, 205, 220, 24, bold=True)
        self.log_text = self._make_text(24, 232, 540, 430)

        self._make_label("Result Summary", 590, 205, 220, 24, bold=True)
        self.summary_text = self._make_text(590, 232, 560, 145)

        self._make_label("Markdown Preview", 590, 398, 220, 24, bold=True)
        self.markdown_text = self._make_text(590, 425, 560, 237)

        self.publish_label = tk.Label(
            self.root,
            textvariable=self.publish_status_var,
            bg=self.BG,
            fg=self.TEXT,
            anchor="w",
            font=("Arial", 12, "bold"),
        )
        self.publish_label.place(x=24, y=690, width=1120, height=28)

    def _draw_progress(self, percent: int) -> None:
        self._progress_percent = max(0, min(100, int(percent)))
        if not hasattr(self, "progress_canvas"):
            return
        self.progress_canvas.delete("all")
        width = max(1, self.progress_canvas.winfo_width() or 760)
        height = max(1, self.progress_canvas.winfo_height() or 14)
        fill_width = int(width * self._progress_percent / 100)
        self.progress_canvas.create_rectangle(0, 0, width, height, fill="#e5e7eb", outline="")
        self.progress_canvas.create_rectangle(0, 0, fill_width, height, fill="#111827", outline="")

    def _set_button_state(self, btn: tk.Button, enabled: bool) -> None:
        btn.config(
            state="normal" if enabled else "disabled",
            bg=self.BUTTON if enabled else self.DISABLED,
        )

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
        threading.Thread(target=self._run_generation_worker, daemon=True).start()

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
        threading.Thread(target=self._publish_worker, daemon=True).start()

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
    LocalPipelineUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
