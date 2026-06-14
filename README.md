# Cliniko Assistant

macOS desktop app for Steven Girgis — automates the EPC/DVA/Workcover referral letter workflow.

## Setup

1. Install Python 3.11+ from python.org
2. Open Terminal and run:
   ```
   cd ~/Documents/cliniko-assistant
   pip install -r requirements.txt
   brew install tesseract
   ```
3. Copy `.env.example` to `.env` and fill in your credentials:
   ```
   cp .env.example .env
   ```
4. Open the app and go to **Settings** to upload your Word templates for each workflow.
5. Run:
   ```
   python main.py
   ```

## Desktop launcher

To get a one-click icon on the Desktop, run:
```
cd ~/Documents/cliniko-assistant
python create_launcher.py
```

## Word template placeholders

Your `.docx` templates must use `{{double_brace}}` syntax:

| Placeholder | Value |
|---|---|
| `{{patient_name}}` | Full patient name |
| `{{patient_dob}}` | Date of birth |
| `{{medicare_number}}` | Medicare number |
| `{{irn}}` | Individual Reference Number |
| `{{condition}}` | Diagnosis / condition |
| `{{referral_date}}` | Date of referral |
| `{{doctor_name}}` | Referring doctor's name |
| `{{doctor_provider_no}}` | Doctor's provider number |
| `{{clinic_name}}` | Clinic name (from .env) |
| `{{sender_name}}` | Sender name (from .env) |

## Azure AD setup (for email)

1. Register an app in Azure Active Directory
2. Grant `Mail.Send` application permission
3. Create a client secret
4. Add `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `SENDER_EMAIL` to `.env`

## Developer workflow

```
cd ~/Documents/cliniko-assistant
git pull          # get latest
# fix the bug
git push          # Steven gets it on next launch
```
