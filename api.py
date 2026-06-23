"""Python API exposed to the pywebview JS frontend."""
from __future__ import annotations
import threading
import subprocess
import tempfile
import shutil
import json
from pathlib import Path

import config
import version
import sent_log
import db
import worklist as wl_module
import pdf_extractor
import word_builder
import emailer
import email_templates

# Store generated paths in memory for the current session
_session: dict = {}


class API:
    # ── Worklist ────────────────────────────────────────────────────────────────

    def get_worklist(self, days: int) -> list[dict]:
        return wl_module.build_worklist(int(days))

    def get_last_run(self) -> str | None:
        lr = sent_log.get_last_run()
        return lr.isoformat() if lr else None

    # ── Patient attachments ─────────────────────────────────────────────────────

    def get_patient_attachments(self, patient_id: str) -> list[dict]:
        return wl_module.get_all_attachments_for_patient(patient_id)

    # ── PDF extraction ──────────────────────────────────────────────────────────

    def extract_pdf(self, download_url: str) -> dict:
        try:
            import cliniko
            data = cliniko.download_attachment_bytes(download_url)
            text = pdf_extractor.extract_text(data)
            fields = pdf_extractor.parse_fields(text)
            _session["last_pdf_bytes"] = data
            return fields
        except Exception as e:
            err = str(e)
            if "502" in err or "Bad Gateway" in err:
                raise Exception("Cliniko is temporarily unavailable (502). Please wait a moment and click Read & Extract again.")
            if "503" in err or "504" in err:
                raise Exception("Cliniko is temporarily unavailable. Please wait a moment and try again.")
            if "APIConnectionError" in err or "Connection error" in err:
                raise Exception("Cannot reach the AI service (Anthropic). Check that ANTHROPIC_API_KEY is set in your .env file and that the internet connection is working.")
            raise

    def preview_source_pdf(self, download_url: str, filename: str = "") -> dict:
        try:
            import cliniko
            suffix = Path(filename).suffix if filename else ".pdf"
            if not suffix:
                suffix = ".pdf"
            data = cliniko.download_attachment_bytes(download_url)
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(data)
                tmp = f.name
            subprocess.Popen(["open", tmp])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Document generation ──────────────────────────────────────────────────────

    def get_template_status(self) -> dict:
        status = {}
        for key in config.WORKFLOW_KEYS:
            path = word_builder.get_template_path(key)
            status[key] = {
                "exists": path is not None,
                "filename": path.name if path else None,
            }
        return status

    def open_template(self, workflow_key: str) -> dict:
        path = word_builder.get_template_path(workflow_key)
        if not path:
            return {"ok": False, "error": "No template uploaded"}
        # Reveal the file in Finder so the user can open it with the right app
        subprocess.run(["open", "-R", str(path)])
        return {"ok": True}

    def upload_template(self, workflow_key: str) -> dict:
        import webview
        windows = webview.windows
        if not windows:
            return {"ok": False, "error": "No window"}
        result = windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("Word Documents (*.docx)",),
        )
        if result:
            dest = config.TEMPLATES_DIR / f"{workflow_key}.docx"
            shutil.copy2(result[0], dest)
            return {"ok": True, "filename": Path(result[0]).name}
        return {"ok": False, "error": "cancelled"}

    def generate_document(self, workflow_key: str, fields: dict) -> dict:
        try:
            template_path = word_builder.get_template_path(workflow_key)
            if not template_path:
                return {"ok": False, "error": f"No template uploaded for {config.WORKFLOW_LABELS.get(workflow_key, workflow_key)}. Go to Settings to upload one."}
            name = fields.get("patient_name", "Patient")
            out_name = word_builder.build_output_filename(name, workflow_key)
            config.OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
            docx_path = config.OUTPUT_PATH / f"{out_name}.docx"
            word_builder.populate_template(template_path, fields, docx_path)
            pdf_path = word_builder.convert_to_pdf(docx_path)
            _session["generated_pdf"] = str(pdf_path)
            _session["generated_docx"] = str(docx_path)
            return {"ok": True, "pdf_path": str(pdf_path), "filename": pdf_path.name}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_generated_pdf(self) -> dict:
        pdf_path = _session.get("generated_pdf")
        if not pdf_path or not Path(pdf_path).exists():
            # Try the .docx fallback
            if pdf_path:
                docx_path = Path(pdf_path).with_suffix(".docx")
                if docx_path.exists():
                    subprocess.run(["open", str(docx_path)])
                    return {"ok": True}
            return {"ok": False, "error": "Generated document not found"}
        subprocess.run(["open", pdf_path])
        return {"ok": True}

    # ── Email ────────────────────────────────────────────────────────────────────

    def get_email_template(self, workflow_key: str) -> dict:
        return email_templates.get(workflow_key)

    def save_email_template(self, workflow_key: str, subject: str, body: str, cc: str = "") -> dict:
        try:
            email_templates.save(workflow_key, subject, body, cc)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def render_email(self, workflow_key: str, fields: dict) -> dict:
        tmpl = email_templates.get(workflow_key)
        fields = {**fields, "sender_name": "Mr Steven Girgis\nPhysiotherapist"}
        return {
            "subject": email_templates.render(tmpl["subject"], fields),
            "body": email_templates.render(tmpl["body"], fields),
            "cc": tmpl.get("cc", ""),
        }

    def send_email(self, to: str, workflow_key: str, fields: dict) -> dict:
        try:
            pdf_path = _session.get("generated_pdf")
            if not pdf_path:
                return {"ok": False, "error": "No generated PDF found"}
            fields = {**fields, "sender_name": "Mr Steven Girgis\nPhysiotherapist"}
            tmpl = email_templates.get(workflow_key)
            subject = email_templates.render(tmpl["subject"], fields)
            body = email_templates.render(tmpl["body"], fields)
            cc = tmpl.get("cc") or None
            # Use the docx if no pdf was generated
            doc_path = Path(pdf_path)
            if not doc_path.exists():
                doc_path = doc_path.with_suffix(".docx")
            emailer.send_email(to=to, subject=subject, body=body,
                               pdf_path=doc_path, cc=cc)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Sent log ─────────────────────────────────────────────────────────────────

    def mark_sent(self, patient_id: str, file_name: str, appointment_date: str) -> dict:
        sent_log.mark_sent(patient_id, file_name, appointment_date)
        return {"ok": True}

    def update_last_run(self) -> dict:
        sent_log.update_last_run()
        return {"ok": True}

    # ── Patient database ─────────────────────────────────────────────────────────

    def save_patient(self, patient_id: str, patient_name: str, first_name: str,
                     medicare_number: str, irn: str, dob: str, workflow: str) -> dict:
        db.upsert_patient(patient_id, patient_name, first_name,
                          medicare_number, irn, dob, workflow)
        return {"ok": True}

    def search_patients(self, query: str = "") -> list[dict]:
        return db.search_patients(query)

    # ── Settings ─────────────────────────────────────────────────────────────────

    def get_scan_settings(self) -> dict:
        return {
            "scan_days": config.SCAN_DAYS,
            "worklist_keywords": ", ".join(config.WORKLIST_KEYWORDS),
            "preferred_keywords": ", ".join(config.PREFERRED_KEYWORDS),
        }

    def save_scan_settings(self, days: int, wl_keywords: str, pref_keywords: str) -> dict:
        try:
            env_path = config.APP_DIR / ".env"
            lines = env_path.read_text().splitlines() if env_path.exists() else []

            def _set(key, val):
                for i, l in enumerate(lines):
                    if l.startswith(f"{key}="):
                        lines[i] = f"{key}={val}"
                        return
                lines.append(f"{key}={val}")

            _set("SCAN_DAYS", str(days))
            _set("WORKLIST_FILE_KEYWORDS", wl_keywords.replace(" ", ""))
            _set("PREFERRED_FILE_KEYWORDS", pref_keywords.replace(" ", ""))
            env_path.write_text("\n".join(lines))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_workflow_labels(self) -> dict:
        return config.WORKFLOW_LABELS

    def get_version(self) -> str:
        return version.VERSION
