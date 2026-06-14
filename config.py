import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

def _list(val: str) -> list[str]:
    return [k.strip() for k in val.split(",") if k.strip()]

CLINIKO_API_KEY: str = os.getenv("CLINIKO_API_KEY", "")
MS_TENANT_ID: str = os.getenv("MS_TENANT_ID", "")
MS_CLIENT_ID: str = os.getenv("MS_CLIENT_ID", "")
MS_CLIENT_SECRET: str = os.getenv("MS_CLIENT_SECRET", "")
SENDER_EMAIL: str = os.getenv("SENDER_EMAIL", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OUTPUT_PATH: Path = Path(os.path.expanduser(os.getenv("OUTPUT_PATH", "~/Desktop/")))
WORKLIST_KEYWORDS: list[str] = _list(os.getenv("WORKLIST_FILE_KEYWORDS", "EPC,DVA,Workcover"))
PREFERRED_KEYWORDS: list[str] = _list(os.getenv("PREFERRED_FILE_KEYWORDS", "determination,ILC,NDIS"))
SCAN_DAYS: int = int(os.getenv("SCAN_DAYS", "7"))

BASE_URL: str = os.getenv("CLINIKO_BASE_URL", "https://api.au2.cliniko.com/v1").rstrip("/")
APP_DIR: Path = Path(__file__).parent
TEMPLATES_DIR: Path = APP_DIR / "templates"
SENT_LOG_PATH: Path = APP_DIR / "sent_log.json"
DB_PATH: Path = APP_DIR / "patients.db"
EMAIL_TEMPLATES_PATH: Path = APP_DIR / "email_templates.json"

TEMPLATES_DIR.mkdir(exist_ok=True)

WORKFLOW_KEYS = [
    "epc_new",
    "epc_final",
    "dva_new",
    "dva_final",
    "wc_new",
    "wc_final_form032",
    "wc_final_crm",
]

WORKFLOW_LABELS = {
    "epc_new": "EPC — New Patient",
    "epc_final": "EPC — Final Consult",
    "dva_new": "DVA — New Patient",
    "dva_final": "DVA — Final Consult",
    "wc_new": "Workcover — New Patient",
    "wc_final_form032": "Workcover — Final Consult (Form 032)",
    "wc_final_crm": "Workcover — Final Consult (CRM Letter)",
}
