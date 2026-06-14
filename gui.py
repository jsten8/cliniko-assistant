"""Main GUI — all screens and state management using customtkinter."""
from __future__ import annotations
import threading
import tempfile
import subprocess
import shutil
import os
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from datetime import date, datetime
import customtkinter as ctk

import config
import sent_log
import db
import worklist as wl_module
import pdf_extractor
import word_builder
import emailer
import email_templates

# ── Theme ──────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

TEAL = "#0F7B6C"
TEAL_LIGHT = "#E6F4F1"
TEAL_DARK = "#0A6357"
AMBER = "#C4770A"
AMBER_LIGHT = "#FEF3E2"
BG = "#F2F0EB"
SURFACE = "#FFFFFF"
SURFACE2 = "#F7F6F2"
BORDER = "#E4E1D8"
TEXT = "#1A1916"
TEXT2 = "#6B6860"
TEXT_MUTED = "#A8A49C"
SENT_BG = "#F7F6F2"
SENT_TEXT = "#B0ADA6"

WORKFLOW_OPTIONS = [
    ("1 — EPC · New Patient", "epc_new"),
    ("2 — EPC · Final Consult", "epc_final"),
    ("3 — DVA · New Patient", "dva_new"),
    ("4 — DVA · Final Consult", "dva_final"),
    ("5 — Workcover · New Patient", "wc_new"),
    ("6 — Workcover · Final Consult  ★ 2 templates", "wc_final_form032"),
]

WORKFLOW_HINTS = {
    "epc_new": 'Matched "EPC" in filename · 1 template · Email to doctor',
    "epc_final": 'Matched "EPC" + "final" · 1 template · Email to doctor',
    "dva_new": 'Matched "DVA" in filename · 1 template · Email to doctor',
    "dva_final": 'Matched "DVA" + "final" · 1 template · Email to doctor',
    "wc_new": 'Matched "Workcover" in filename · 1 template · Email to doctor',
    "wc_final_form032": '2 templates · Stage 1: Form 032 → Workcover portal · Stage 2: CRM letter → email',
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _label(parent, text, size=13, weight="normal", color=TEXT, **kw):
    return ctk.CTkLabel(parent, text=text, font=("DM Sans", size, weight), text_color=color, **kw)


def _btn(parent, text, command, fg=TEAL, text_color="white", width=120, **kw):
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color=fg, hover_color=TEAL_DARK if fg == TEAL else None,
        text_color=text_color, font=("DM Sans", 13, "normal"),
        width=width, corner_radius=6, **kw
    )


def _ghost_btn(parent, text, command, **kw):
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color="transparent", hover_color=SURFACE2,
        text_color=TEXT2, font=("DM Sans", 12, "normal"),
        border_width=0, width=80, **kw
    )


def _entry(parent, width=300, **kw):
    return ctk.CTkEntry(
        parent, width=width, font=("DM Sans", 13),
        fg_color=SURFACE, border_color=BORDER, text_color=TEXT,
        corner_radius=6, **kw
    )


def _card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=SURFACE, border_color=BORDER, border_width=1, corner_radius=10, **kw)


def _divider(parent):
    return ctk.CTkFrame(parent, height=1, fg_color=BORDER)


def _badge(parent, text, color=TEAL):
    f = ctk.CTkFrame(parent, fg_color=color, corner_radius=20)
    ctk.CTkLabel(f, text=text, font=("DM Mono", 11, "bold"), text_color="white").pack(padx=8, pady=2)
    return f


def _status_badge(parent, sent: bool):
    if sent:
        f = ctk.CTkFrame(parent, fg_color=SENT_BG, corner_radius=20, border_width=1, border_color=BORDER)
        ctk.CTkLabel(f, text="✓ Sent", font=("DM Sans", 11, "bold"), text_color=SENT_TEXT).pack(padx=8, pady=3)
    else:
        f = ctk.CTkFrame(parent, fg_color=AMBER_LIGHT, corner_radius=20, border_width=1, border_color="#F0D0A0")
        ctk.CTkLabel(f, text="● Action Required", font=("DM Sans", 11, "bold"), text_color=AMBER).pack(padx=8, pady=3)
    return f


# ── Main App ───────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Cliniko Assistant")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.configure(fg_color=BG)

        db.init_db()

        # Shared state
        self.worklist: list[dict] = []
        self.selected_entry: dict = {}
        self.selected_attachment: dict = {}
        self.selected_workflow: str = ""
        self.extracted_fields: dict[str, str] = {}
        self.generated_docx: Path | None = None
        self.generated_pdf: Path | None = None
        self.scan_days = tk.IntVar(value=config.SCAN_DAYS)

        self._build_ui()
        self.show_screen("worklist")
        self._start_scan()

    # ── Screen routing ─────────────────────────────────────────────────────────

    def _build_ui(self):
        self.frames: dict[str, ctk.CTkFrame] = {}
        container = ctk.CTkFrame(self, fg_color=BG)
        container.pack(fill="both", expand=True)
        self._container = container

        for Screen in [
            WorklistScreen, FileSelectorScreen, ReviewFieldsScreen,
            PreviewScreen, SendScreen, ProdaScreen,
            PatientsScreen, HowItWorksScreen, SettingsScreen,
        ]:
            frame = Screen(container, self)
            self.frames[Screen.screen_id] = frame
            # Don't place yet — show_screen handles placement

    def show_screen(self, screen_id: str):
        frame = self.frames.get(screen_id)
        if not frame:
            return
        # Hide all other screens, show only the active one
        for sid, f in self.frames.items():
            if sid == screen_id:
                f.place(relx=0, rely=0, relwidth=1, relheight=1)
                f.lift()
            else:
                f.place_forget()
        frame.on_show()

    # ── Background scan ────────────────────────────────────────────────────────

    def _start_scan(self):
        worklist_screen = self.frames["worklist"]
        worklist_screen.set_loading(True, "Scanning Cliniko...")

        def run():
            try:
                entries = wl_module.build_worklist(
                    self.scan_days.get(),
                    progress_callback=lambda msg: self.after(0, worklist_screen.set_status, msg),
                )
                self.worklist = entries
                self.after(0, worklist_screen.populate, entries)
            except Exception as e:
                self.after(0, worklist_screen.set_error, str(e))

        threading.Thread(target=run, daemon=True).start()

    def refresh_scan(self):
        self._start_scan()


# ── Base Screen ────────────────────────────────────────────────────────────────

class BaseScreen(ctk.CTkFrame):
    screen_id = "base"

    def __init__(self, parent, app: App):
        super().__init__(parent, fg_color=BG)
        self.app = app

    def on_show(self):
        pass

    def _titlebar(self, active_tab: str | None = None):
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, border_width=0)
        bar.pack(fill="x")
        ctk.CTkFrame(bar, height=1, fg_color=BORDER).pack(fill="x", side="bottom")

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", padx=16, pady=0)

        dot = ctk.CTkFrame(left, width=8, height=8, fg_color=TEAL, corner_radius=4)
        dot.pack(side="left", padx=(0, 8), pady=14)
        ctk.CTkLabel(left, text="Cliniko Assistant", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.pack(side="right", padx=16, pady=8)

        tabs = [
            ("☰ Worklist", "worklist"),
            ("Patients & PRODA", "patients"),
            ("How This App Works", "how"),
            ("⚙ Settings", "settings"),
        ]
        for i, (label, sid) in enumerate(tabs):
            is_active = (sid == active_tab)
            radius_left = 6 if i == 0 else 0
            radius_right = 6 if i == len(tabs) - 1 else 0

            btn = tk.Button(
                right, text=label,
                font=("DM Sans", 12, "bold" if is_active else "normal"),
                bg=TEAL_LIGHT if is_active else SURFACE,
                fg=TEAL if is_active else TEXT2,
                relief="flat", bd=0,
                padx=12, pady=5,
                cursor="hand2",
                command=lambda s=sid: self.app.show_screen(s),
            )
            btn.pack(side="left")

        return bar

    def _breadcrumb(self, titlebar_frame, crumbs: list[tuple[str, str | None]]):
        bc = ctk.CTkFrame(titlebar_frame, fg_color="transparent")
        bc.pack(side="right", padx=16)
        for i, (label, sid) in enumerate(crumbs):
            if i > 0:
                ctk.CTkLabel(bc, text="›", font=("DM Sans", 12), text_color=TEXT_MUTED).pack(side="left", padx=2)
            if sid:
                btn = tk.Button(bc, text=label, font=("DM Sans", 12), fg=TEXT2, bg=SURFACE,
                                relief="flat", bd=0, cursor="hand2",
                                command=lambda s=sid: self.app.show_screen(s))
                btn.pack(side="left")
            else:
                ctk.CTkLabel(bc, text=label, font=("DM Sans", 12, "bold"), text_color=TEXT).pack(side="left")

    def _step_bar(self, current: int):
        """Steps 1-5 progress bar for the workflow screens."""
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=40)
        bar.pack(fill="x")
        ctk.CTkFrame(bar, height=1, fg_color=BORDER).pack(fill="x", side="bottom")

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(side="left", padx=16, pady=0)

        steps = ["Select File", "Review Fields", "Preview", "Send", "PRODA"]
        for i, label in enumerate(steps, 1):
            step_frame = ctk.CTkFrame(inner, fg_color="transparent")
            step_frame.pack(side="left", padx=4)

            if i < current:
                num_bg, num_fg = TEAL_LIGHT, TEAL
                num_text = "✓"
                label_color = TEXT2
            elif i == current:
                num_bg, num_fg = TEAL, "white"
                num_text = str(i)
                label_color = TEAL
            else:
                num_bg, num_fg = BORDER, TEXT_MUTED
                num_text = str(i)
                label_color = TEXT_MUTED

            circle = ctk.CTkFrame(step_frame, width=20, height=20, fg_color=num_bg, corner_radius=10)
            circle.pack(side="left")
            circle.pack_propagate(False)
            ctk.CTkLabel(circle, text=num_text, font=("DM Sans", 10, "bold"), text_color=num_fg).place(relx=0.5, rely=0.5, anchor="center")
            ctk.CTkLabel(step_frame, text=f" {label}", font=("DM Sans", 11, "normal"), text_color=label_color).pack(side="left")

            if i < len(steps):
                ctk.CTkLabel(inner, text=" › ", font=("DM Sans", 11), text_color=BORDER).pack(side="left")


# ── Screen 1: Worklist ─────────────────────────────────────────────────────────

class WorklistScreen(BaseScreen):
    screen_id = "worklist"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        self._titlebar("worklist")

        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=24, pady=(16, 0))

        left = ctk.CTkFrame(toolbar, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text="Worklist", font=("DM Sans", 20, "bold"), text_color=TEXT).pack(side="left")
        self._count_badge = _badge(left, "0 action required")
        self._count_badge.pack(side="left", padx=8)

        right = ctk.CTkFrame(toolbar, fg_color="transparent")
        right.pack(side="right")
        self._last_run_label = ctk.CTkLabel(right, text="", font=("DM Mono", 11), text_color=TEXT_MUTED)
        self._last_run_label.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(right, text="Last", font=("DM Sans", 12), text_color=TEXT2).pack(side="left")
        days_entry = ctk.CTkEntry(right, width=40, textvariable=self.app.scan_days, font=("DM Mono", 13))
        days_entry.pack(side="left", padx=4)
        ctk.CTkLabel(right, text="days", font=("DM Sans", 12), text_color=TEXT2).pack(side="left", padx=(0, 8))
        _btn(right, "↻ Refresh", self.app.refresh_scan, width=90).pack(side="left")

        # Last run
        lr = sent_log.get_last_run()
        if lr:
            delta = (datetime.now() - lr).days
            self._last_run_label.configure(text=f"Last run: {delta} days ago  ({lr.strftime('%d %b %Y')})")

        # Status label
        self._status_label = ctk.CTkLabel(self, text="", font=("DM Sans", 12), text_color=TEXT_MUTED)
        self._status_label.pack(pady=4)

        # Table card
        self._card_frame = _card(self)
        self._card_frame.pack(fill="both", expand=True, padx=24, pady=(8, 24))

        # Header row
        header = ctk.CTkFrame(self._card_frame, fg_color=SURFACE2, corner_radius=0)
        header.pack(fill="x")
        _divider(self._card_frame).pack(fill="x")
        for col, w in [("Status", 130), ("Patient", 200), ("File", 0), ("Appointment", 120), ("", 80)]:
            ctk.CTkLabel(
                header, text=col.upper(), font=("DM Sans", 11, "bold"),
                text_color=TEXT_MUTED, width=w if w else 1, anchor="w"
            ).pack(side="left", padx=16, pady=10)

        # Scrollable rows area
        self._scroll = ctk.CTkScrollableFrame(self._card_frame, fg_color=SURFACE, corner_radius=0)
        self._scroll.pack(fill="both", expand=True)

        self._empty_label = ctk.CTkLabel(self._scroll, text="No EPC, DVA, or Workcover files found in the selected date range.",
                                          font=("DM Sans", 13), text_color=TEXT_MUTED)
        self._error_label = ctk.CTkLabel(self._scroll, text="", font=("DM Sans", 13), text_color="#C0392B")
        self._retry_btn = _btn(self._scroll, "Retry", self.app.refresh_scan, width=80)

    def on_show(self):
        lr = sent_log.get_last_run()
        if lr:
            delta = (datetime.now() - lr).days
            self._last_run_label.configure(text=f"Last run: {delta} days ago  ({lr.strftime('%d %b %Y')})")

    def set_loading(self, loading: bool, msg: str = ""):
        self._status_label.configure(text=msg if loading else "")
        self._error_label.pack_forget()
        self._retry_btn.pack_forget()

    def set_status(self, msg: str):
        self._status_label.configure(text=msg)

    def set_error(self, msg: str):
        self._status_label.configure(text="")
        self._clear_rows()
        self._error_label.configure(text=f"Could not connect to Cliniko — {msg}")
        self._error_label.pack(pady=20)
        self._retry_btn.pack(pady=8)

    def _clear_rows(self):
        for w in self._scroll.winfo_children():
            w.pack_forget()

    def populate(self, entries: list[dict]):
        self._status_label.configure(text="")
        self._clear_rows()

        pending = [e for e in entries if not e["sent"]]
        sent = [e for e in entries if e["sent"]]

        # Update badge
        for w in self._count_badge.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self._count_badge, text=f"{len(pending)} action required",
            font=("DM Mono", 11, "bold"), text_color="white"
        ).pack(padx=8, pady=2)

        if not entries:
            self._empty_label.pack(pady=20)
            return

        for entry in pending + sent:
            self._add_row(entry)

    def _add_row(self, entry: dict):
        is_sent = entry["sent"]
        row = ctk.CTkFrame(self._scroll, fg_color=SENT_BG if is_sent else SURFACE, corner_radius=0)
        row.pack(fill="x")
        _divider(self._scroll).pack(fill="x")

        # Status
        status_cell = ctk.CTkFrame(row, fg_color="transparent", width=130)
        status_cell.pack(side="left", padx=16, pady=12)
        status_cell.pack_propagate(False)
        _status_badge(status_cell, is_sent).pack(anchor="w")

        # Patient name
        ctk.CTkLabel(row, text=entry["patient_name"], font=("DM Sans", 13, "bold"),
                     text_color=SENT_TEXT if is_sent else TEXT, width=200, anchor="w").pack(side="left", padx=8)

        # File tag + name
        file_cell = ctk.CTkFrame(row, fg_color="transparent")
        file_cell.pack(side="left", fill="x", expand=True)
        fname = entry["file_name"]
        tag_type = "EPC" if "epc" in fname.lower() else ("DVA" if "dva" in fname.lower() else "WC")
        tag_color = TEAL if tag_type == "EPC" else (AMBER if tag_type == "DVA" else "#3949AB")
        tag_bg = TEAL_LIGHT if tag_type == "EPC" else (AMBER_LIGHT if tag_type == "DVA" else "#EEF0F8")
        tag_f = ctk.CTkFrame(file_cell, fg_color=tag_bg, corner_radius=4)
        tag_f.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(tag_f, text=tag_type, font=("DM Mono", 10, "bold"), text_color=tag_color).pack(padx=6, pady=2)
        ctk.CTkLabel(file_cell, text=fname, font=("DM Sans", 12), text_color=SENT_TEXT if is_sent else TEXT2,
                     anchor="w").pack(side="left")

        # Date
        ctk.CTkLabel(row, text=entry["appointment_date"], font=("DM Mono", 12),
                     text_color=SENT_TEXT if is_sent else TEXT2, width=120).pack(side="left", padx=8)

        # Action button
        btn_cell = ctk.CTkFrame(row, fg_color="transparent", width=80)
        btn_cell.pack(side="right", padx=16)
        btn_cell.pack_propagate(False)
        if not is_sent:
            _btn(btn_cell, "Action →", lambda e=entry: self._action(e), width=80).pack(anchor="e")

        if not is_sent:
            row.bind("<Button-1>", lambda ev, e=entry: self._action(e))
            row.configure(cursor="")

    def _action(self, entry: dict):
        self.app.selected_entry = entry
        self.app.show_screen("file_selector")


# ── Screen 2: File Selector ────────────────────────────────────────────────────

class FileSelectorScreen(BaseScreen):
    screen_id = "file_selector"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        self._titlebar_frame = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        self._titlebar_frame.pack(fill="x")
        ctk.CTkFrame(self._titlebar_frame, height=1, fg_color=BORDER).pack(fill="x", side="bottom")
        left = ctk.CTkFrame(self._titlebar_frame, fg_color="transparent")
        left.pack(side="left", padx=16, pady=8)
        dot = ctk.CTkFrame(left, width=8, height=8, fg_color=TEAL, corner_radius=4)
        dot.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(left, text="Cliniko Assistant", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")

        self._step_bar(1)

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True)

        top = ctk.CTkFrame(scroll, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(16, 0))
        _ghost_btn(top, "← Back", lambda: self.app.show_screen("worklist")).pack(side="left")
        self._patient_label = ctk.CTkLabel(top, text="", font=("DM Sans", 20, "bold"), text_color=TEXT)
        self._patient_label.pack(side="left", padx=8)

        card = _card(scroll)
        card.pack(padx=24, pady=16, anchor="nw")
        card.configure(width=560)

        # Card header
        ch = ctk.CTkFrame(card, fg_color="transparent")
        ch.pack(fill="x", padx=20, pady=(14, 0))
        ctk.CTkLabel(ch, text="Select PDF to process", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")
        self._file_count_label = ctk.CTkLabel(ch, text="", font=("DM Sans", 12), text_color=TEXT_MUTED)
        self._file_count_label.pack(side="right")
        _divider(card).pack(fill="x", padx=0, pady=(10, 0))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(body, text="ATTACHMENT", font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self._file_var = tk.StringVar()
        self._file_menu = ctk.CTkOptionMenu(body, variable=self._file_var, width=480,
                                             font=("DM Sans", 12), fg_color=SURFACE,
                                             button_color=BORDER, button_hover_color=TEAL_LIGHT,
                                             dropdown_fg_color=SURFACE, text_color=TEXT,
                                             command=self._on_file_change)
        self._file_menu.pack(fill="x", pady=(4, 0))
        self._rec_label = ctk.CTkLabel(body, text="", font=("DM Sans", 11), text_color=AMBER)
        self._rec_label.pack(anchor="w", pady=(4, 0))

        _divider(body).pack(fill="x", pady=12)

        ctk.CTkLabel(body, text="WORKFLOW", font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self._workflow_var = tk.StringVar()
        wf_labels = [o[0] for o in WORKFLOW_OPTIONS]
        self._workflow_menu = ctk.CTkOptionMenu(body, values=wf_labels, variable=self._workflow_var,
                                                 width=480, font=("DM Sans", 12), fg_color=SURFACE,
                                                 button_color=BORDER, button_hover_color=TEAL_LIGHT,
                                                 dropdown_fg_color=SURFACE, text_color=TEXT,
                                                 command=self._on_workflow_change)
        self._workflow_menu.pack(fill="x", pady=(4, 0))
        self._workflow_hint = ctk.CTkLabel(body, text="", font=("DM Sans", 11), text_color=AMBER)
        self._workflow_hint.pack(anchor="w", pady=(4, 0))

        _divider(body).pack(fill="x", pady=12)

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x")
        _btn(btns, "Preview Source PDF ↗", self._preview_pdf,
             fg=SURFACE, text_color=TEXT, width=180).pack(side="left")
        self._extract_btn = _btn(btns, "Read & Extract →", self._extract, width=140)
        self._extract_btn.pack(side="right")
        self._extract_status = ctk.CTkLabel(body, text="", font=("DM Sans", 12), text_color=TEXT_MUTED)
        self._extract_status.pack(pady=4)

        self._attachments: list[dict] = []

    def on_show(self):
        entry = self.app.selected_entry
        self._patient_label.configure(text=entry.get("patient_name", ""))
        self._breadcrumb(self._titlebar_frame, [("Worklist", "worklist"), (entry.get("patient_name", ""), None)])

        self._attachments = []
        self._extract_status.configure(text="")

        def load():
            try:
                atts = wl_module.get_all_attachments_for_patient(entry["patient_id"])
                self.app.after(0, self._populate_files, atts)
            except Exception as e:
                self.app.after(0, self._extract_status.configure, {"text": f"Error loading files: {e}"})

        threading.Thread(target=load, daemon=True).start()

    def _populate_files(self, attachments: list[dict]):
        self._attachments = attachments
        self._file_count_label.configure(text=f"{len(attachments)} files found")

        options = []
        rec_label = None
        for a in attachments:
            label = a.get("filename", "")
            if a.get("recommended"):
                label = f"⭐  {label}"
                rec_label = f'⭐ Recommended — matched keyword in filename'
            options.append(label)

        if options:
            self._file_menu.configure(values=options)
            self._file_var.set(options[0])
            self._rec_label.configure(text=rec_label or "")
            self.app.selected_attachment = attachments[0]

        # Auto-detect workflow
        wf = self.app.selected_entry.get("workflow", "epc_new")
        wf_label = next((o[0] for o in WORKFLOW_OPTIONS if o[1] == wf), WORKFLOW_OPTIONS[0][0])
        self._workflow_var.set(wf_label)
        self.app.selected_workflow = wf
        self._workflow_hint.configure(text=f"⭐ Auto-detected  {WORKFLOW_HINTS.get(wf, '')}")

    def _on_file_change(self, label: str):
        for i, a in enumerate(self._attachments):
            fname = a.get("filename", "")
            if fname in label or label.endswith(fname):
                self.app.selected_attachment = a
                self._rec_label.configure(text="⭐ Recommended — matched keyword in filename" if a.get("recommended") else "")
                break

    def _on_workflow_change(self, label: str):
        wf = next((o[1] for o in WORKFLOW_OPTIONS if o[0] == label), "epc_new")
        self.app.selected_workflow = wf
        self._workflow_hint.configure(text=WORKFLOW_HINTS.get(wf, ""))

    def _preview_pdf(self):
        att = self.app.selected_attachment
        if not att:
            return
        self._extract_status.configure(text="Loading PDF preview...")

        def run():
            try:
                import cliniko as cl
                data = cl.download_attachment_bytes(att["download_url"])
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(data)
                    tmp = f.name
                subprocess.Popen(["open", tmp])
                self.app.after(0, self._extract_status.configure, {"text": ""})
            except Exception as e:
                self.app.after(0, self._extract_status.configure, {"text": f"Preview failed: {e}"})

        threading.Thread(target=run, daemon=True).start()

    def _extract(self):
        att = self.app.selected_attachment
        if not att:
            messagebox.showwarning("No file selected", "Please select a PDF to extract.")
            return
        self._extract_status.configure(text="Reading PDF...")
        self._extract_btn.configure(state="disabled")

        def run():
            try:
                import cliniko as cl
                data = cl.download_attachment_bytes(att["download_url"])
                text = pdf_extractor.extract_text(data)
                fields = pdf_extractor.parse_fields(text)
                # Pre-fill name/dob from Cliniko if PDF extraction missed it
                entry = self.app.selected_entry
                if not fields.get("patient_name"):
                    fields["patient_name"] = entry.get("patient_name", "")
                if not fields.get("patient_dob"):
                    fields["patient_dob"] = entry.get("patient_dob", "")
                self.app.extracted_fields = fields
                self.app.after(0, self._on_extracted)
            except Exception as e:
                self.app.after(0, self._on_extract_error, str(e))

        threading.Thread(target=run, daemon=True).start()

    def _on_extracted(self):
        self._extract_status.configure(text="")
        self._extract_btn.configure(state="normal")
        self.app.show_screen("review_fields")

    def _on_extract_error(self, msg: str):
        self._extract_status.configure(text=f"Extraction failed: {msg}")
        self._extract_btn.configure(state="normal")


# ── Screen 3: Review Fields ────────────────────────────────────────────────────

class ReviewFieldsScreen(BaseScreen):
    screen_id = "review_fields"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._entries: dict[str, ctk.CTkEntry] = {}
        self._build()

    def _build(self):
        self._tb = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        self._tb.pack(fill="x")
        ctk.CTkFrame(self._tb, height=1, fg_color=BORDER).pack(fill="x", side="bottom")
        left = ctk.CTkFrame(self._tb, fg_color="transparent")
        left.pack(side="left", padx=16, pady=8)
        dot = ctk.CTkFrame(left, width=8, height=8, fg_color=TEAL, corner_radius=4)
        dot.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(left, text="Cliniko Assistant", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")

        self._step_bar(2)

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True)

        top = ctk.CTkFrame(scroll, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(16, 0))
        _ghost_btn(top, "← Back", lambda: self.app.show_screen("file_selector")).pack(side="left")
        ctk.CTkLabel(top, text="Review Extracted Fields", font=("DM Sans", 17, "bold"), text_color=TEXT).pack(side="left", padx=8)

        card = _card(scroll)
        card.pack(fill="x", padx=24, pady=16)

        ch = ctk.CTkFrame(card, fg_color="transparent")
        ch.pack(fill="x", padx=20, pady=(14, 0))
        self._card_title = ctk.CTkLabel(ch, text="Fields extracted from PDF", font=("DM Sans", 13, "bold"), text_color=TEXT)
        self._card_title.pack(side="left")
        self._field_count = ctk.CTkLabel(ch, text="", font=("DM Sans", 12), text_color=TEAL)
        self._field_count.pack(side="right")
        _divider(card).pack(fill="x", padx=0, pady=(10, 0))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(body, text="PATIENT DETAILS", font=("DM Sans", 11, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 8))

        patient_fields = [
            ("patient_name", "Patient Full Name"),
            ("patient_dob", "Date of Birth"),
            ("medicare_number", "Medicare Number"),
            ("irn", "Individual Reference No. (IRN)"),
            ("condition", "Condition / Diagnosis"),
            ("referral_date", "Referral Date"),
        ]
        for key, label in patient_fields:
            self._field_row(body, key, label)

        _divider(body).pack(fill="x", pady=12)
        ctk.CTkLabel(body, text="DOCTOR DETAILS", font=("DM Sans", 11, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 8))

        doctor_fields = [
            ("doctor_name", "Doctor's Name"),
            ("doctor_provider_no", "Doctor's Provider No."),
            ("doctor_email", "Doctor's Email"),
        ]
        for key, label in doctor_fields:
            self._field_row(body, key, label)

        _divider(body).pack(fill="x", pady=12)
        footer = ctk.CTkFrame(body, fg_color="transparent")
        footer.pack(fill="x")
        ctk.CTkLabel(footer, text="Edit any field above before generating", font=("DM Sans", 12), text_color=TEXT_MUTED).pack(side="left")
        _btn(footer, "Generate Document →", self._generate).pack(side="right")
        self._gen_status = ctk.CTkLabel(body, text="", font=("DM Sans", 12), text_color=TEXT_MUTED)
        self._gen_status.pack(pady=4)

    def _field_row(self, parent, key: str, label: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text=label.upper(), font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED, anchor="w").pack(anchor="w")
        e = _entry(row, width=600)
        e.pack(fill="x")
        self._entries[key] = e

    def on_show(self):
        entry = self.app.selected_entry
        self._breadcrumb(self._tb, [
            ("Worklist", "worklist"),
            (entry.get("patient_name", ""), "file_selector"),
            ("Review Fields", None),
        ])
        fname = self.app.selected_attachment.get("filename", "PDF")
        self._card_title.configure(text=f"Fields extracted from {fname}")

        fields = self.app.extracted_fields
        for key, e in self._entries.items():
            e.delete(0, "end")
            e.insert(0, fields.get(key, ""))

        filled = sum(1 for v in fields.values() if v.strip())
        self._field_count.configure(text=f"✓ {filled} fields extracted")

    def _get_fields(self) -> dict[str, str]:
        return {k: e.get() for k, e in self._entries.items()}

    def _generate(self):
        wf = self.app.selected_workflow
        template_path = word_builder.get_template_path(wf)
        if not template_path:
            messagebox.showerror("No Template", f"No Word template uploaded for this workflow.\n\nGo to Settings → upload a .docx template for '{config.WORKFLOW_LABELS.get(wf, wf)}'.")
            return

        self._gen_status.configure(text="Generating document...")
        fields = self._get_fields()
        self.app.extracted_fields = fields

        def run():
            try:
                name = fields.get("patient_name", "Patient")
                out_name = word_builder.build_output_filename(name, wf)
                docx_path = config.OUTPUT_PATH / f"{out_name}.docx"
                config.OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
                word_builder.populate_template(template_path, fields, docx_path)
                pdf_path = word_builder.convert_to_pdf(docx_path)
                self.app.generated_docx = docx_path
                self.app.generated_pdf = pdf_path
                self.app.after(0, self._on_generated)
            except Exception as e:
                self.app.after(0, self._on_gen_error, str(e))

        threading.Thread(target=run, daemon=True).start()

    def _on_generated(self):
        self._gen_status.configure(text="")
        self.app.show_screen("preview")

    def _on_gen_error(self, msg: str):
        self._gen_status.configure(text=f"Generation failed: {msg}")


# ── Screen 4: Preview & Approve ───────────────────────────────────────────────

class PreviewScreen(BaseScreen):
    screen_id = "preview"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        self._tb = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        self._tb.pack(fill="x")
        ctk.CTkFrame(self._tb, height=1, fg_color=BORDER).pack(fill="x", side="bottom")
        left = ctk.CTkFrame(self._tb, fg_color="transparent")
        left.pack(side="left", padx=16, pady=8)
        dot = ctk.CTkFrame(left, width=8, height=8, fg_color=TEAL, corner_radius=4)
        dot.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(left, text="Cliniko Assistant", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")

        self._step_bar(3)

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True)

        top = ctk.CTkFrame(scroll, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(16, 0))
        _ghost_btn(top, "← Back", lambda: self.app.show_screen("review_fields")).pack(side="left")
        ctk.CTkLabel(top, text="Preview Document", font=("DM Sans", 17, "bold"), text_color=TEXT).pack(side="left", padx=8)

        card = _card(scroll)
        card.pack(fill="x", padx=24, pady=16)

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=20, pady=16)

        file_row = ctk.CTkFrame(body, fg_color="transparent")
        file_row.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(file_row, text="📄", font=("DM Sans", 22)).pack(side="left")
        info = ctk.CTkFrame(file_row, fg_color="transparent")
        info.pack(side="left", padx=8)
        self._fname_label = ctk.CTkLabel(info, text="", font=("DM Sans", 13, "bold"), text_color=TEXT)
        self._fname_label.pack(anchor="w")
        self._gen_status = ctk.CTkLabel(info, text="✓ Generated successfully from template", font=("DM Sans", 11), text_color=TEAL)
        self._gen_status.pack(anchor="w")

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x")
        _btn(btns, "Open in Preview ↗", self._open_preview, fg=SURFACE, text_color=TEXT, width=160).pack(side="left")
        edit_btn = _ghost_btn(btns, "← Edit fields", lambda: self.app.show_screen("review_fields"))
        edit_btn.pack(side="right", padx=8)
        _btn(btns, "Approve & Continue →", lambda: self.app.show_screen("send")).pack(side="right")

        self._regen_status = ctk.CTkLabel(body, text="", font=("DM Sans", 12), text_color=TEXT_MUTED)
        self._regen_status.pack(pady=4)

    def on_show(self):
        entry = self.app.selected_entry
        self._breadcrumb(self._tb, [
            ("Worklist", "worklist"),
            (entry.get("patient_name", ""), "file_selector"),
            ("Preview", None),
        ])
        pdf = self.app.generated_pdf
        if pdf:
            self._fname_label.configure(text=pdf.name)

    def _open_preview(self):
        pdf = self.app.generated_pdf
        if not pdf or not pdf.exists():
            messagebox.showerror("Error", "Generated PDF not found. Please regenerate.")
            return
        subprocess.run(["open", str(pdf)])


# ── Screen 5: Email & Send ────────────────────────────────────────────────────

class SendScreen(BaseScreen):
    screen_id = "send"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        self._tb = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        self._tb.pack(fill="x")
        ctk.CTkFrame(self._tb, height=1, fg_color=BORDER).pack(fill="x", side="bottom")
        left = ctk.CTkFrame(self._tb, fg_color="transparent")
        left.pack(side="left", padx=16, pady=8)
        dot = ctk.CTkFrame(left, width=8, height=8, fg_color=TEAL, corner_radius=4)
        dot.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(left, text="Cliniko Assistant", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")

        self._step_bar(4)

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True)

        top = ctk.CTkFrame(scroll, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(16, 0))
        _ghost_btn(top, "← Back", lambda: self.app.show_screen("preview")).pack(side="left")
        ctk.CTkLabel(top, text="Send to Doctor", font=("DM Sans", 20, "bold"), text_color=TEXT).pack(side="left", padx=8)

        card = _card(scroll)
        card.pack(padx=24, pady=16, anchor="nw")
        card.configure(width=520)

        ch = ctk.CTkFrame(card, fg_color="transparent")
        ch.pack(fill="x", padx=20, pady=(14, 0))
        ctk.CTkLabel(ch, text="Email details", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")
        _divider(card).pack(fill="x", padx=0, pady=(10, 0))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(body, text="RECIPIENT", font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self._to_entry = _entry(body, width=460)
        self._to_entry.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(body, text="Pre-filled from extracted fields — edit if needed", font=("DM Sans", 11), text_color=TEXT_MUTED).pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(body, text="ATTACHMENT", font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        att_frame = ctk.CTkFrame(body, fg_color=SURFACE2, corner_radius=6, border_color=BORDER, border_width=1)
        att_frame.pack(fill="x", pady=(4, 12))
        att_inner = ctk.CTkFrame(att_frame, fg_color="transparent")
        att_inner.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(att_inner, text="📄", font=("DM Sans", 16)).pack(side="left")
        self._att_label = ctk.CTkLabel(att_inner, text="", font=("DM Sans", 13, "bold"), text_color=TEXT)
        self._att_label.pack(side="left", padx=8)

        _divider(body).pack(fill="x", pady=8)

        footer = ctk.CTkFrame(body, fg_color="transparent")
        footer.pack(fill="x")
        ctk.CTkLabel(footer, text="Sent via Microsoft Graph / Outlook", font=("DM Sans", 12), text_color=TEXT_MUTED).pack(side="left")
        _btn(footer, "Review & Send →", self._preview_email).pack(side="right")

        self._send_status = ctk.CTkLabel(body, text="", font=("DM Sans", 12), text_color=TEXT_MUTED)
        self._send_status.pack(pady=4)

    def on_show(self):
        entry = self.app.selected_entry
        self._breadcrumb(self._tb, [
            ("Worklist", "worklist"),
            (entry.get("patient_name", ""), "file_selector"),
            ("Send", None),
        ])
        self._to_entry.delete(0, "end")
        self._to_entry.insert(0, self.app.extracted_fields.get("doctor_email", ""))
        pdf = self.app.generated_pdf
        self._att_label.configure(text=pdf.name if pdf else "")

    def _preview_email(self):
        EmailPreviewDialog(self.app, self._to_entry.get(), self._on_sent)

    def _on_sent(self):
        entry = self.app.selected_entry
        sent_log.mark_sent(
            entry["patient_id"],
            entry["file_name"],
            entry.get("appointment_date", ""),
        )
        fields = self.app.extracted_fields
        db.upsert_patient(
            entry["patient_id"],
            entry.get("patient_name", ""),
            entry.get("patient_first_name", ""),
            fields.get("medicare_number", ""),
            fields.get("irn", ""),
            fields.get("patient_dob", ""),
            self.app.selected_workflow,
        )
        self.app.show_screen("proda")


class EmailPreviewDialog(ctk.CTkToplevel):
    def __init__(self, app: App, to_email: str, on_sent_callback):
        super().__init__(app)
        self.app = app
        self.to_email = to_email
        self.on_sent_callback = on_sent_callback
        self.title("New Message — Outlook")
        self.geometry("680x580")
        self.resizable(False, False)
        self.grab_set()
        self._build()

    def _build(self):
        # Outlook-style header
        top = ctk.CTkFrame(self, fg_color="#0F3D6E", corner_radius=0)
        top.pack(fill="x")
        hdr = ctk.CTkFrame(top, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=10)
        ctk.CTkLabel(hdr, text="New Message — Outlook", font=("DM Sans", 13, "bold"), text_color="white").pack(side="left")
        ctk.CTkButton(hdr, text="✕", width=28, height=28, corner_radius=4,
                      fg_color="#1A5590", hover_color="#2471A3",
                      text_color="white", command=self.destroy).pack(side="right")

        toolbar = ctk.CTkFrame(self, fg_color="#0A3260", corner_radius=0)
        toolbar.pack(fill="x")
        tb_inner = ctk.CTkFrame(toolbar, fg_color="transparent")
        tb_inner.pack(fill="x", padx=16, pady=6)
        ctk.CTkButton(tb_inner, text="Send", width=80, fg_color="#0078D4", hover_color="#005A9E",
                      text_color="white", font=("DM Sans", 13, "bold"),
                      command=self._send).pack(side="left")
        ctk.CTkLabel(tb_inner, text="Discard   Attach", font=("DM Sans", 12), text_color="#999999").pack(side="left", padx=12)

        # Email fields
        content = ctk.CTkScrollableFrame(self, fg_color=SURFACE)
        content.pack(fill="both", expand=True)

        fields = self.app.extracted_fields
        wf = self.app.selected_workflow
        tmpl = email_templates.get(wf)
        subject = email_templates.render(tmpl["subject"], fields)
        body = email_templates.render(tmpl["body"], fields)

        self._render_row(content, "To", self.to_email)
        self._render_row(content, "Cc", tmpl.get("cc", ""))
        self._render_row(content, "Subject", subject)

        # Attachment
        att_frame = ctk.CTkFrame(content, fg_color="transparent")
        att_frame.pack(fill="x", padx=16, pady=8)
        pdf = self.app.generated_pdf
        att_chip = ctk.CTkFrame(att_frame, fg_color="#F3F3F3", corner_radius=6)
        att_chip.pack(side="left")
        ctk.CTkFrame(att_chip, width=32, height=32, fg_color="#C0392B", corner_radius=4).pack(side="left", padx=8, pady=8)
        info = ctk.CTkFrame(att_chip, fg_color="transparent")
        info.pack(side="left", padx=(0, 12), pady=8)
        ctk.CTkLabel(info, text=pdf.name if pdf else "", font=("DM Sans", 12, "bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(info, text=f"{pdf.stat().st_size // 1024} kB" if pdf and pdf.exists() else "", font=("DM Sans", 11), text_color="#888").pack(anchor="w")

        _divider(content).pack(fill="x")

        # Body
        body_frame = ctk.CTkFrame(content, fg_color=SURFACE)
        body_frame.pack(fill="x", padx=16, pady=12)
        ctk.CTkLabel(body_frame, text=body, font=("DM Sans", 13), text_color=TEXT,
                     anchor="nw", justify="left", wraplength=560).pack(anchor="w")

        self._status_label = ctk.CTkLabel(content, text="", font=("DM Sans", 13), text_color=TEAL)
        self._status_label.pack(pady=8)

        # Footer
        footer = ctk.CTkFrame(self, fg_color=SURFACE2, corner_radius=0)
        footer.pack(fill="x")
        ctk.CTkFrame(footer, height=1, fg_color="#E8E8E8").pack(fill="x")
        f_inner = ctk.CTkFrame(footer, fg_color="transparent")
        f_inner.pack(fill="x", padx=16, pady=10)
        ctk.CTkLabel(f_inner, text="Review the email above then click Send, or close to go back and make changes",
                     font=("DM Sans", 11), text_color="#999").pack(side="left")
        _btn(f_inner, "← Go Back", self.destroy, fg=SURFACE, text_color=TEXT, width=100).pack(side="right", padx=(8, 0))
        self._send_btn = _btn(f_inner, "Send Now →", self._send, width=100)
        self._send_btn.pack(side="right")

        self._subject = subject
        self._body = body

    def _render_row(self, parent, label: str, value: str):
        row = ctk.CTkFrame(parent, fg_color=SURFACE)
        row.pack(fill="x")
        ctk.CTkFrame(row, height=1, fg_color="#E8E8E8").pack(fill="x", side="bottom")
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(inner, text=label, font=("DM Sans", 12), text_color="#666", width=50, anchor="w").pack(side="left")
        ctk.CTkLabel(inner, text=value, font=("DM Sans", 13), text_color=TEXT, anchor="w").pack(side="left", padx=8)

    def _send(self):
        self._send_btn.configure(state="disabled", text="Sending...")
        pdf = self.app.generated_pdf

        def run():
            try:
                emailer.send_email(
                    to=self.to_email,
                    subject=self._subject,
                    body=self._body,
                    pdf_path=pdf,
                )
                self.app.after(0, self._on_success)
            except Exception as e:
                self.app.after(0, self._on_error, str(e))

        threading.Thread(target=run, daemon=True).start()

    def _on_success(self):
        self._status_label.configure(text="✓ Email sent successfully")
        self.app.after(1400, self._finish)

    def _finish(self):
        self.destroy()
        self.on_sent_callback()

    def _on_error(self, msg: str):
        self._send_btn.configure(state="normal", text="Send Now →")
        messagebox.showerror("Email failed", f"Email authentication failed or send error:\n\n{msg}", parent=self)


# ── Screen 6: PRODA Panel ─────────────────────────────────────────────────────

class ProdaScreen(BaseScreen):
    screen_id = "proda"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        self._tb = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        self._tb.pack(fill="x")
        ctk.CTkFrame(self._tb, height=1, fg_color=BORDER).pack(fill="x", side="bottom")
        left = ctk.CTkFrame(self._tb, fg_color="transparent")
        left.pack(side="left", padx=16, pady=8)
        dot = ctk.CTkFrame(left, width=8, height=8, fg_color=TEAL, corner_radius=4)
        dot.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(left, text="Cliniko Assistant", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")

        self._step_bar(5)

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True)

        top = ctk.CTkFrame(scroll, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(16, 0))
        ctk.CTkLabel(top, text="PRODA Entry", font=("DM Sans", 20, "bold"), text_color=TEXT).pack(side="left")
        amb = ctk.CTkFrame(top, fg_color=AMBER, corner_radius=20)
        ctk.CTkLabel(amb, text="Manual entry required", font=("DM Mono", 11, "bold"), text_color="white").pack(padx=8, pady=2)
        amb.pack(side="left", padx=8)

        self._success_banner = ctk.CTkFrame(scroll, fg_color=TEAL_LIGHT, corner_radius=6,
                                             border_color="#B8DDD8", border_width=1)
        self._success_banner.pack(fill="x", padx=24, pady=8)
        self._success_label = ctk.CTkLabel(self._success_banner, text="", font=("DM Sans", 13), text_color=TEAL)
        self._success_label.pack(padx=16, pady=10)

        card = _card(scroll)
        card.pack(padx=24, pady=8, anchor="nw")
        card.configure(width=580)

        ch = ctk.CTkFrame(card, fg_color="transparent")
        ch.pack(fill="x", padx=20, pady=(14, 0))
        ctk.CTkLabel(ch, text="Copy fields into PRODA portal", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(ch, text="Click 📋 to copy each field", font=("DM Sans", 11), text_color=TEXT_MUTED).pack(side="right")
        _divider(card).pack(fill="x", padx=0, pady=(10, 0))

        self._proda_fields_frame = ctk.CTkFrame(card, fg_color="transparent")
        self._proda_fields_frame.pack(fill="x")

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=14)
        _divider(footer).pack(fill="x", pady=(0, 12))
        f_inner = ctk.CTkFrame(footer, fg_color="transparent")
        f_inner.pack(fill="x")
        self._sent_label = ctk.CTkLabel(f_inner, text="", font=("DM Sans", 12), text_color=TEXT_MUTED)
        self._sent_label.pack(side="left")
        _btn(f_inner, "← Back to Worklist", self._back_to_worklist, width=160).pack(side="right")

    def on_show(self):
        entry = self.app.selected_entry
        fields = self.app.extracted_fields
        self._breadcrumb(self._tb, [("Worklist", "worklist"), (f"PRODA — {entry.get('patient_name', '')}", None)])

        self._success_label.configure(text=f"✓ Email sent — copy the fields below into PRODA")
        self._sent_label.configure(text=f"{entry.get('patient_name', '')} marked as ✓ Sent")

        # Rebuild PRODA fields
        for w in self._proda_fields_frame.winfo_children():
            w.destroy()

        proda_data = [
            ("Medicare Number", fields.get("medicare_number", ""), "From PDF"),
            ("Individual Reference Number (IRN)", fields.get("irn", ""), "From PDF"),
            ("First Name", entry.get("patient_first_name", ""), "Cliniko record"),
            ("Date of Birth", fields.get("patient_dob", "") or entry.get("patient_dob", ""), "Cliniko record"),
        ]

        for label, value, source in proda_data:
            self._proda_row(self._proda_fields_frame, label, value, source)

    def _proda_row(self, parent, label: str, value: str, source: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        _divider(parent).pack(fill="x")

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", padx=20, pady=12, fill="x", expand=True)
        ctk.CTkLabel(left, text=label.upper(), font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED, anchor="w").pack(anchor="w")
        ctk.CTkLabel(left, text=value or "—", font=("DM Mono", 13, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(left, text=source, font=("DM Sans", 10), text_color=TEXT_MUTED, anchor="w").pack(anchor="w")

        copy_btn = ctk.CTkButton(row, text="📋 Copy", width=80, height=30,
                                  fg_color=SURFACE2, hover_color=TEAL_LIGHT,
                                  text_color=TEXT2, border_color=BORDER, border_width=1,
                                  font=("DM Sans", 12), corner_radius=4,
                                  command=lambda v=value, b=None: self._copy(v, copy_btn))
        copy_btn.pack(side="right", padx=16)
        # Fix late binding
        copy_btn.configure(command=lambda v=value: self._copy(v, copy_btn))

    def _copy(self, value: str, btn: ctk.CTkButton):
        self.clipboard_clear()
        self.clipboard_append(value)
        original_text = btn.cget("text")
        btn.configure(text="✓ Copied", fg_color=TEAL_LIGHT)
        self.app.after(1800, lambda: btn.configure(text=original_text, fg_color=SURFACE2))

    def _back_to_worklist(self):
        sent_log.update_last_run()
        self.app.show_screen("worklist")
        self.app.refresh_scan()


# ── Screen: Patients & PRODA ──────────────────────────────────────────────────

class PatientsScreen(BaseScreen):
    screen_id = "patients"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        self._titlebar("patients")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=24, pady=(16, 0))
        ctk.CTkLabel(toolbar, text="Patients & PRODA", font=("DM Sans", 20, "bold"), text_color=TEXT).pack(side="left")
        self._count_badge = _badge(toolbar, "0 patients")
        self._count_badge.pack(side="left", padx=8)

        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.pack(fill="x", padx=24, pady=8)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        ctk.CTkLabel(search_frame, text="🔍", font=("DM Sans", 14), text_color=TEXT_MUTED).pack(side="left", padx=(0, 4))
        _entry(search_frame, width=400, textvariable=self._search_var,
               placeholder_text="Search by name, Medicare number...").pack(side="left")

        card = _card(self)
        card.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        header = ctk.CTkFrame(card, fg_color=SURFACE2, corner_radius=0)
        header.pack(fill="x")
        _divider(card).pack(fill="x")
        for col in ["Patient", "Medicare No.", "IRN", "DOB", "Last Workflow", "Last Actioned", ""]:
            ctk.CTkLabel(header, text=col.upper(), font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED, anchor="w").pack(side="left", padx=12, pady=10)

        self._scroll = ctk.CTkScrollableFrame(card, fg_color=SURFACE, corner_radius=0)
        self._scroll.pack(fill="both", expand=True)
        self._all_rows: list[dict] = []

    def on_show(self):
        self._all_rows = db.search_patients()
        self._render(self._all_rows)

    def _filter(self):
        q = self._search_var.get().lower()
        rows = [r for r in self._all_rows if q in r.get("patient_name", "").lower() or q in r.get("medicare_number", "").lower()]
        self._render(rows)

    def _render(self, rows: list[dict]):
        for w in self._scroll.winfo_children():
            w.destroy()

        for w in self._count_badge.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._count_badge, text=f"{len(rows)} patients",
                     font=("DM Mono", 11, "bold"), text_color="white").pack(padx=8, pady=2)

        if not rows:
            ctk.CTkLabel(self._scroll, text="No patients found.", font=("DM Sans", 13), text_color=TEXT_MUTED).pack(pady=20)
            return

        for r in rows:
            row_frame = ctk.CTkFrame(self._scroll, fg_color=SURFACE, corner_radius=0)
            row_frame.pack(fill="x")
            _divider(self._scroll).pack(fill="x")

            for text, w in [
                (r.get("patient_name", ""), 160),
                (r.get("medicare_number", ""), 120),
                (r.get("irn", ""), 50),
                (r.get("dob", ""), 100),
                (config.WORKFLOW_LABELS.get(r.get("last_workflow", ""), r.get("last_workflow", "")), 160),
                ((r.get("last_actioned", "") or "")[:10], 100),
            ]:
                ctk.CTkLabel(row_frame, text=text, font=("DM Sans", 12 if w > 60 else 11),
                             text_color=TEXT, width=w, anchor="w").pack(side="left", padx=12, pady=12)

            proda_btn = _btn(row_frame, "📋 PRODA", lambda rec=r: self._open_proda(rec),
                             fg=SURFACE, text_color=TEXT2, width=80)
            proda_btn.pack(side="right", padx=12)
            row_frame.bind("<Button-1>", lambda ev, rec=r: self._open_proda(rec))

    def _open_proda(self, record: dict):
        ProdaQuickModal(self.app, record)


class ProdaQuickModal(ctk.CTkToplevel):
    def __init__(self, app: App, record: dict):
        super().__init__(app)
        self.title(f"PRODA Fields — {record.get('patient_name', '')}")
        self.geometry("520x380")
        self.resizable(False, False)
        self.grab_set()

        header = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkFrame(header, height=1, fg_color=BORDER).pack(fill="x", side="bottom")
        h_inner = ctk.CTkFrame(header, fg_color="transparent")
        h_inner.pack(fill="x", padx=16, pady=10)
        ctk.CTkLabel(h_inner, text=f"📋 PRODA Fields — {record.get('patient_name', '')}",
                     font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkButton(h_inner, text="✕", width=28, height=28, corner_radius=14,
                      fg_color=SURFACE2, hover_color=BORDER, text_color=TEXT2,
                      command=self.destroy).pack(side="right")

        fields = [
            ("Medicare Number", record.get("medicare_number", ""), "From PDF"),
            ("IRN", record.get("irn", ""), "From PDF"),
            ("First Name", record.get("first_name", ""), "Cliniko record"),
            ("Date of Birth", record.get("dob", ""), "Cliniko record"),
        ]
        for label, value, source in fields:
            row = ctk.CTkFrame(self, fg_color="transparent")
            row.pack(fill="x")
            _divider(self).pack(fill="x")
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", padx=20, pady=10, fill="x", expand=True)
            ctk.CTkLabel(left, text=label.upper(), font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED, anchor="w").pack(anchor="w")
            ctk.CTkLabel(left, text=value or "—", font=("DM Mono", 13), text_color=TEXT, anchor="w").pack(anchor="w")
            ctk.CTkLabel(left, text=source, font=("DM Sans", 10), text_color=TEXT_MUTED, anchor="w").pack(anchor="w")
            copy_btn = ctk.CTkButton(row, text="📋 Copy", width=80, height=30,
                                      fg_color=SURFACE2, hover_color=TEAL_LIGHT,
                                      text_color=TEXT2, border_color=BORDER, border_width=1,
                                      font=("DM Sans", 12), corner_radius=4,
                                      command=lambda v=value: self._copy(v))
            copy_btn.pack(side="right", padx=16)

        footer = ctk.CTkFrame(self, fg_color=SURFACE2)
        footer.pack(fill="x", side="bottom")
        _btn(footer, "Done", self.destroy, width=80).pack(side="right", padx=16, pady=12)

    def _copy(self, value: str):
        self.clipboard_clear()
        self.clipboard_append(value)


# ── Screen: How It Works ───────────────────────────────────────────────────────

class HowItWorksScreen(BaseScreen):
    screen_id = "how"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        self._titlebar("how")
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True)

        top = ctk.CTkFrame(scroll, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(16, 0))
        _ghost_btn(top, "← Back", lambda: self.app.show_screen("worklist")).pack(side="left")
        ctk.CTkLabel(top, text="How This App Works", font=("DM Sans", 20, "bold"), text_color=TEXT).pack(side="left", padx=8)

        steps = [
            ("1", "The app scans Cliniko automatically",
             "As soon as you open the app, it quietly checks your Cliniko account for any patients who had an appointment in the last few days and have an EPC, DVA, or Workcover file attached to their profile. You don't need to do anything — it just runs in the background."),
            ("2", "You see your worklist",
             "The app shows you a clean list of patients who need to be actioned — with their name, the file type (EPC, DVA, Workcover), and when their appointment was. Patients you've already dealt with are greyed out so you always know what's left to do."),
            ("3", "You click a patient to action them",
             "Click any patient row and the app takes you to their file. It recommends the most relevant PDF (based on the filename) and tries to guess which workflow type applies. You can always change either if it gets it wrong."),
            ("4", "The app reads the PDF and pulls out the key information",
             "The PDF never gets saved to your computer — the app reads it directly from Cliniko in memory. It extracts things like the patient's name, Medicare number, date of birth, the referring doctor's details, and the diagnosis."),
            ("5", "The app generates your letter automatically",
             "Using the Word template you've uploaded in Settings, the app fills in all the placeholders with the patient's information and produces a completed PDF letter. You can open it to check it looks right."),
            ("6", "The app sends the email for you",
             "Once you're happy with the letter, you hit Send. The app opens a preview of the email — already addressed to the right doctor, with the PDF attached — so you can do a final check before it goes."),
            ("7", "PRODA fields are ready to copy",
             "After the email is sent, the app shows you the four fields you need to enter into the PRODA government portal — Medicare number, IRN, first name, and date of birth — with a copy button next to each one."),
        ]

        card = _card(scroll)
        card.pack(fill="x", padx=24, pady=16)
        ctk.CTkLabel(card, text="What happens each time you open the app", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(anchor="w", padx=20, pady=(14, 4))
        _divider(card).pack(fill="x")

        for num, title, desc in steps:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=12)
            _divider(card).pack(fill="x")
            circle = ctk.CTkFrame(row, width=32, height=32, fg_color=TEAL, corner_radius=16)
            circle.pack(side="left", anchor="n")
            circle.pack_propagate(False)
            ctk.CTkLabel(circle, text=num, font=("DM Sans", 13, "bold"), text_color="white").place(relx=0.5, rely=0.5, anchor="center")
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", padx=12, fill="x", expand=True)
            ctk.CTkLabel(info, text=title, font=("DM Sans", 13, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
            ctk.CTkLabel(info, text=desc, font=("DM Sans", 12), text_color=TEXT2, anchor="w",
                         wraplength=700, justify="left").pack(anchor="w", pady=(4, 0))


# ── Screen: Settings ───────────────────────────────────────────────────────────

class SettingsScreen(BaseScreen):
    screen_id = "settings"

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        self._titlebar("settings")
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(scroll, text="Settings", font=("DM Sans", 20, "bold"), text_color=TEXT).pack(anchor="w", padx=24, pady=(16, 12))

        # Workflow templates card
        templates_card = _card(scroll)
        templates_card.pack(fill="x", padx=24, pady=(0, 16))
        ch = ctk.CTkFrame(templates_card, fg_color="transparent")
        ch.pack(fill="x", padx=20, pady=(14, 0))
        ctk.CTkLabel(ch, text="Workflow Templates", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")
        self._saved_badge = ctk.CTkLabel(ch, text="✓ Saved", font=("DM Sans", 11, "bold"), text_color=TEAL)
        self._saved_badge.pack(side="right")
        self._saved_badge.pack_forget()
        ctk.CTkLabel(templates_card, text="Each workflow has its own Word template and email template. Upload a .docx file for each.",
                     font=("DM Sans", 11), text_color=TEXT_MUTED).pack(anchor="w", padx=20, pady=(2, 0))
        _divider(templates_card).pack(fill="x", pady=(10, 0))

        # Table header
        hdr = ctk.CTkFrame(templates_card, fg_color=SURFACE2, corner_radius=0)
        hdr.pack(fill="x")
        for col, w in [("Workflow", 220), (".docx Template", 200), ("Email Template", 200)]:
            ctk.CTkLabel(hdr, text=col.upper(), font=("DM Sans", 10, "bold"), text_color=TEXT_MUTED,
                         width=w, anchor="w").pack(side="left", padx=16, pady=8)
        _divider(templates_card).pack(fill="x")

        workflows = [
            ("epc_new", "EPC · New Patient", "Workflow 1", TEAL_LIGHT, TEAL, "EPC"),
            ("epc_final", "EPC · Final Consult", "Workflow 2", TEAL_LIGHT, TEAL, "EPC"),
            ("dva_new", "DVA · New Patient", "Workflow 3", AMBER_LIGHT, AMBER, "DVA"),
            ("dva_final", "DVA · Final Consult", "Workflow 4", AMBER_LIGHT, AMBER, "DVA"),
            ("wc_new", "Workcover · New Patient", "Workflow 5", "#EEF0F8", "#3949AB", "WC"),
            ("wc_final_form032", "Workcover · Final (Form 032)", "Workflow 6a", "#EEF0F8", "#3949AB", "WC"),
            ("wc_final_crm", "Workcover · Final (CRM Letter)", "Workflow 6b", "#EEF0F8", "#3949AB", "WC"),
        ]

        for wf_key, wf_name, wf_sub, tag_bg, tag_fg, tag_text in workflows:
            self._template_row(templates_card, wf_key, wf_name, wf_sub, tag_bg, tag_fg, tag_text)

        # Scan settings card
        scan_card = _card(scroll)
        scan_card.pack(fill="x", padx=24, pady=(0, 24))
        ctk.CTkLabel(scan_card, text="Scan Settings", font=("DM Sans", 13, "bold"), text_color=TEXT).pack(anchor="w", padx=20, pady=(14, 0))
        ctk.CTkLabel(scan_card, text="Configure how the worklist scan works.",
                     font=("DM Sans", 11), text_color=TEXT_MUTED).pack(anchor="w", padx=20)
        _divider(scan_card).pack(fill="x", pady=(8, 0))

        body = ctk.CTkFrame(scan_card, fg_color="transparent")
        body.pack(fill="x", padx=20, pady=16)

        self._scan_days_var = tk.StringVar(value=str(config.SCAN_DAYS))
        self._wl_keywords_var = tk.StringVar(value=", ".join(config.WORKLIST_KEYWORDS))
        self._pref_keywords_var = tk.StringVar(value=", ".join(config.PREFERRED_KEYWORDS))

        for label, var, hint in [
            ("Default Day Range", self._scan_days_var, "Days to scan back on launch"),
            ("Worklist Keywords", self._wl_keywords_var, "Comma-separated filename keywords"),
            ("Recommended File Keywords", self._pref_keywords_var, "Used to auto-select the best file"),
        ]:
            f = ctk.CTkFrame(body, fg_color="transparent")
            f.pack(anchor="w", pady=6)
            ctk.CTkLabel(f, text=label.upper(), font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED, anchor="w").pack(anchor="w")
            _entry(f, width=300, textvariable=var).pack(anchor="w", pady=(2, 0))
            ctk.CTkLabel(f, text=hint, font=("DM Sans", 11), text_color=TEXT_MUTED, anchor="w").pack(anchor="w")

        _divider(body).pack(fill="x", pady=8)
        footer = ctk.CTkFrame(body, fg_color="transparent")
        footer.pack(fill="x")
        ctk.CTkLabel(footer, text="Requires app restart to take effect", font=("DM Sans", 12), text_color=TEXT_MUTED).pack(side="left")
        _btn(footer, "Save Settings", self._save_scan_settings, width=120).pack(side="right")

    def _template_row(self, parent, wf_key, wf_name, wf_sub, tag_bg, tag_fg, tag_text):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        _divider(parent).pack(fill="x")

        # Workflow name cell
        name_cell = ctk.CTkFrame(row, fg_color="transparent", width=220)
        name_cell.pack(side="left", padx=16, pady=12)
        name_cell.pack_propagate(False)
        tag_f = ctk.CTkFrame(name_cell, fg_color=tag_bg, corner_radius=4)
        tag_f.pack(side="left", anchor="n", pady=2)
        ctk.CTkLabel(tag_f, text=tag_text, font=("DM Mono", 10, "bold"), text_color=tag_fg).pack(padx=6, pady=2)
        info = ctk.CTkFrame(name_cell, fg_color="transparent")
        info.pack(side="left", padx=6)
        ctk.CTkLabel(info, text=wf_name, font=("DM Sans", 13, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text=wf_sub, font=("DM Sans", 11), text_color=TEXT_MUTED, anchor="w").pack(anchor="w")

        # Template cell
        tmpl_cell = ctk.CTkFrame(row, fg_color="transparent", width=220)
        tmpl_cell.pack(side="left", padx=8, pady=12)
        tmpl_cell.pack_propagate(False)
        tmpl_path = word_builder.get_template_path(wf_key)
        fname_label = ctk.CTkLabel(tmpl_cell,
                                    text=tmpl_path.name if tmpl_path else "No template uploaded",
                                    font=("DM Mono", 11),
                                    text_color=TEAL if tmpl_path else TEXT_MUTED)
        fname_label.pack(side="left", anchor="w")

        def upload(key=wf_key, lbl=fname_label):
            path = filedialog.askopenfilename(
                title=f"Upload template for {wf_name}",
                filetypes=[("Word Documents", "*.docx")],
            )
            if path:
                import shutil
                dest = config.TEMPLATES_DIR / f"{key}.docx"
                shutil.copy2(path, dest)
                lbl.configure(text=Path(path).name, text_color=TEAL)
                self._flash_saved()

        _btn(tmpl_cell, "Replace" if tmpl_path else "Upload", upload,
             fg=SURFACE, text_color=TEXT2, width=70).pack(side="right")

        # Email template cell
        email_cell = ctk.CTkFrame(row, fg_color="transparent", width=220)
        email_cell.pack(side="left", padx=8, pady=12)
        email_cell.pack_propagate(False)
        if wf_key != "wc_final_form032":
            ctk.CTkLabel(email_cell, text="Email template", font=("DM Sans", 11), text_color=TEXT2).pack(side="left")
            _btn(email_cell, "Edit", lambda key=wf_key: EmailTemplateEditor(self.app, key),
                 fg=SURFACE, text_color=TEXT2, width=60).pack(side="right")
        else:
            ctk.CTkLabel(email_cell, text="No email — portal upload only", font=("DM Sans", 11),
                         text_color=TEXT_MUTED, justify="left").pack(side="left")

    def _flash_saved(self):
        self._saved_badge.pack(side="right")
        self.app.after(2200, self._saved_badge.pack_forget)

    def _save_scan_settings(self):
        env_path = config.APP_DIR / ".env"
        lines = []
        if env_path.exists():
            lines = env_path.read_text().splitlines()

        def _set(key, val):
            for i, l in enumerate(lines):
                if l.startswith(f"{key}="):
                    lines[i] = f"{key}={val}"
                    return
            lines.append(f"{key}={val}")

        _set("SCAN_DAYS", self._scan_days_var.get())
        _set("WORKLIST_FILE_KEYWORDS", self._wl_keywords_var.get().replace(" ", ""))
        _set("PREFERRED_FILE_KEYWORDS", self._pref_keywords_var.get().replace(" ", ""))
        env_path.write_text("\n".join(lines))
        self._flash_saved()
        messagebox.showinfo("Saved", "Scan settings saved. Restart the app for them to take effect.")


class EmailTemplateEditor(ctk.CTkToplevel):
    def __init__(self, app: App, workflow_key: str):
        super().__init__(app)
        self.app = app
        self.workflow_key = workflow_key
        self.title(f"Edit Email — {config.WORKFLOW_LABELS.get(workflow_key, workflow_key)}")
        self.geometry("600x520")
        self.resizable(False, True)
        self.grab_set()
        self._build()

    def _build(self):
        header = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkFrame(header, height=1, fg_color=BORDER).pack(fill="x", side="bottom")
        h_inner = ctk.CTkFrame(header, fg_color="transparent")
        h_inner.pack(fill="x", padx=16, pady=10)
        ctk.CTkLabel(h_inner, text=f"Edit Email — {config.WORKFLOW_LABELS.get(self.workflow_key, '')}",
                     font=("DM Sans", 13, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(h_inner, text="Changes apply to all future sends for this workflow",
                     font=("DM Sans", 11), text_color=TEXT_MUTED).pack(side="left", padx=8)
        ctk.CTkButton(h_inner, text="✕", width=28, height=28, corner_radius=14,
                      fg_color=SURFACE2, hover_color=BORDER, text_color=TEXT2,
                      command=self.destroy).pack(side="right")

        body = ctk.CTkScrollableFrame(self, fg_color=SURFACE)
        body.pack(fill="both", expand=True)
        inner = ctk.CTkFrame(body, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=16)

        tmpl = email_templates.get(self.workflow_key)

        ctk.CTkLabel(inner, text="SUBJECT LINE", font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self._subject_entry = _entry(inner, width=540)
        self._subject_entry.insert(0, tmpl.get("subject", ""))
        self._subject_entry.pack(fill="x", pady=(4, 12))

        ctk.CTkLabel(inner, text="EMAIL BODY", font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self._body_text = ctk.CTkTextbox(inner, height=180, font=("DM Sans", 13),
                                          fg_color=SURFACE, border_color=BORDER, border_width=1,
                                          text_color=TEXT)
        self._body_text.pack(fill="x", pady=(4, 12))
        self._body_text.insert("1.0", tmpl.get("body", ""))

        ctk.CTkLabel(inner, text="CC (OPTIONAL)", font=("DM Sans", 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self._cc_entry = _entry(inner, width=540, placeholder_text="e.g. admin@noosaalliedhealth.com.au")
        self._cc_entry.insert(0, tmpl.get("cc", ""))
        self._cc_entry.pack(fill="x", pady=(4, 12))

        # Placeholder tags
        tag_frame = ctk.CTkFrame(inner, fg_color="transparent")
        tag_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(tag_frame, text="PLACEHOLDERS:", font=("DM Sans", 10, "bold"), text_color=TEXT_MUTED).pack(side="left", padx=(0, 6))
        for ph in ["{{patient_name}}", "{{patient_dob}}", "{{medicare_number}}", "{{condition}}", "{{doctor_name}}", "{{sender_name}}"]:
            btn = ctk.CTkButton(tag_frame, text=ph, width=10, font=("DM Mono", 10),
                                 fg_color=TEAL_LIGHT, hover_color="#B8DDD8",
                                 text_color=TEAL, border_color="#B8DDD8", border_width=1,
                                 corner_radius=4, command=lambda p=ph: self._insert(p))
            btn.pack(side="left", padx=2)

        footer = ctk.CTkFrame(self, fg_color=SURFACE2)
        footer.pack(fill="x", side="bottom")
        ctk.CTkFrame(footer, height=1, fg_color=BORDER).pack(fill="x")
        f_inner = ctk.CTkFrame(footer, fg_color="transparent")
        f_inner.pack(fill="x", padx=16, pady=10)
        _btn(f_inner, "Cancel", self.destroy, fg=SURFACE, text_color=TEXT2, width=80).pack(side="right", padx=(8, 0))
        _btn(f_inner, "Save Template", self._save, width=120).pack(side="right")

    def _insert(self, placeholder: str):
        self._body_text.insert("insert", placeholder)
        self._body_text.focus()

    def _save(self):
        email_templates.save(
            self.workflow_key,
            subject=self._subject_entry.get(),
            body=self._body_text.get("1.0", "end").strip(),
            cc=self._cc_entry.get(),
        )
        self.destroy()
