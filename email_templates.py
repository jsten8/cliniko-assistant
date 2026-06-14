"""Load and persist per-workflow email templates from a JSON file."""
from __future__ import annotations
import json
import config

_DEFAULTS = {
    "epc_new": {
        "subject": "EPC Referral — {{patient_name}} (DOB {{patient_dob}})",
        "body": "Dear {{doctor_name}},\n\nPlease find attached an EPC referral for {{patient_name}} (DOB: {{patient_dob}}, Medicare: {{medicare_number}} — IRN {{irn}}).\n\nThe referral is for physiotherapy services under the Enhanced Primary Care program for {{condition}}.\n\nPlease do not hesitate to contact our practice if you have any questions.\n\nKind regards,\n{{sender_name}}",
        "cc": "",
    },
    "epc_final": {
        "subject": "EPC Final Consult — {{patient_name}} (DOB {{patient_dob}})",
        "body": "Dear {{doctor_name}},\n\nPlease find attached the final consult report for {{patient_name}} (DOB: {{patient_dob}}, Medicare: {{medicare_number}} — IRN {{irn}}).\n\nKind regards,\n{{sender_name}}",
        "cc": "",
    },
    "dva_new": {
        "subject": "DVA Referral — {{patient_name}} (DOB {{patient_dob}})",
        "body": "Dear {{doctor_name}},\n\nPlease find attached a DVA referral for {{patient_name}} (DOB: {{patient_dob}}).\n\nKind regards,\n{{sender_name}}",
        "cc": "",
    },
    "dva_final": {
        "subject": "DVA Final Consult — {{patient_name}} (DOB {{patient_dob}})",
        "body": "Dear {{doctor_name}},\n\nPlease find attached the DVA final consult report for {{patient_name}} (DOB: {{patient_dob}}).\n\nKind regards,\n{{sender_name}}",
        "cc": "",
    },
    "wc_new": {
        "subject": "Workcover Referral — {{patient_name}} (DOB {{patient_dob}})",
        "body": "Dear {{doctor_name}},\n\nPlease find attached a Workcover referral for {{patient_name}} (DOB: {{patient_dob}}).\n\nKind regards,\n{{sender_name}}",
        "cc": "",
    },
    "wc_final_crm": {
        "subject": "Workcover Final Consult — {{patient_name}} (DOB {{patient_dob}})",
        "body": "Dear {{crm_name}},\n\nPlease find attached the Workcover final consult letter for {{patient_name}} (DOB: {{patient_dob}}).\n\nKind regards,\n{{sender_name}}",
        "cc": "",
    },
}


def _load() -> dict:
    if config.EMAIL_TEMPLATES_PATH.exists():
        try:
            return json.loads(config.EMAIL_TEMPLATES_PATH.read_text())
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    config.EMAIL_TEMPLATES_PATH.write_text(json.dumps(data, indent=2))


def get(workflow_key: str) -> dict:
    data = _load()
    return data.get(workflow_key, _DEFAULTS.get(workflow_key, {"subject": "", "body": "", "cc": ""}))


def save(workflow_key: str, subject: str, body: str, cc: str = "") -> None:
    data = _load()
    data[workflow_key] = {"subject": subject, "body": body, "cc": cc}
    _save(data)


def render(template_str: str, fields: dict[str, str]) -> str:
    """Replace {{key}} placeholders in a template string."""
    result = template_str
    for key, val in fields.items():
        result = result.replace(f"{{{{{key}}}}}", val or "")
    return result
