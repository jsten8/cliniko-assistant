# Release Checklist — Cliniko Assistant

Run every test below before bumping `version.py` and pushing. Check off each item.
Tests are ordered: fast/cheap first, slow/manual last.

---

## 0. Pre-push (on Jacob's machine)

- [ ] `version.py` bumped (e.g. 1.0.4 → 1.0.5)
- [ ] All changed files committed and pushed to `main`
- [ ] `git status` is clean

---

## 1. Auto-updater (CRITICAL — was broken)

This must be tested on **Steven's machine** every release.

### 1a. GitHub is reachable
Run in Terminal on Steven's Mac:
```
curl -s https://raw.githubusercontent.com/jsten8/cliniko-assistant/main/version.py
```
**Expected:** `VERSION = "x.x.x"` matching the version you just pushed.
If this fails — GitHub is unreachable or the repo went private. Stop here and fix.

### 1b. Version file is readable
Run on Steven's Mac:
```
cat ~/Documents/cliniko-assistant-main/version.py
```
**Expected:** shows the *previous* version (one behind what you just pushed).
If it already shows the new version, the update already ran — skip to 1d.

### 1c. Auto-update triggers on launch
Close the app completely. Reopen it. Wait 30 seconds.
**Expected:** App opens and version number in the nav bar matches the new version you pushed.
If not — check `~/Documents/cliniko-assistant-main/update.log` for the error.

### 1d. update.log shows success
```
cat ~/Documents/cliniko-assistant-main/update.log
```
**Expected:** Last lines should read something like:
```
Auto-update check: local=1.0.3
Auto-update check: remote=1.0.4
Update available: 1.0.3 → 1.0.4. Downloading...
Updated to v1.0.4. Restarting...
```
If it says `Auto-update failed:` — the error message will tell you exactly what went wrong.

### 1e. Preserved files survived the update
Check these were NOT wiped:
```
ls ~/Documents/cliniko-assistant-main/.env
ls ~/Documents/cliniko-assistant-main/patients.db
ls ~/Documents/cliniko-assistant-main/sent_log.json
ls ~/Documents/cliniko-assistant-main/templates/
```
All should exist. If any are missing, the PRESERVE list in `updater.py` has a bug.

---

## 2. App Launch

- [ ] App opens without error
- [ ] Version number appears in the nav bar (top right)
- [ ] No Python traceback shown in the window
- [ ] Window is sized correctly (not too small, not blank)

---

## 3. Home / Worklist

- [ ] "Scan last 7 days" loads patients without crashing
- [ ] At least one patient appears (if there are recent referrals in Cliniko)
- [ ] File upload date shown in the "File Uploaded" column (not appointment date)
- [ ] No 429 errors shown (rate limiting handled silently)
- [ ] No 502/503/504 errors shown on load (retry logic working)
- [ ] Patients with image files (`.jpg`, `.png`) are NOT shown

---

## 4. Select File (Step 1)

- [ ] Clicking a patient opens the Select File screen
- [ ] Correct attachments listed in the dropdown
- [ ] "Recommended" badge appears on the best-match file
- [ ] "Auto-detected" badge shows the correct workflow
- [ ] "Preview Source PDF" button opens the file correctly (not a generic `.tmp` file)
- [ ] "Read & Extract" button does NOT show a 502 error (the fix from v1.0.4)
  - If Cliniko returns a 502: wait 10s and try again — should now retry automatically

---

## 5. Review Fields (Step 2)

- [ ] Patient name populated
- [ ] Doctor name populated
- [ ] Referral date populated
- [ ] Condition populated
- [ ] Medicare Number / IRN / DOB populated (if on the referral)
- [ ] Fields are editable if AI got something wrong

---

## 6. Generate Document (Step 3 — Preview)

- [ ] "Generate Document" button works without error
- [ ] Output file appears on the Desktop (or configured OUTPUT_PATH)
- [ ] "Open in Preview" opens a PDF (not a Pages document, not "Could not open PDF")
- [ ] Template placeholders are all replaced — no `{{patient_name}}` left in the output
- [ ] Patient name in the document matches Cliniko

---

## 7. Send Email (Step 4)

- [ ] Email modal opens
- [ ] To, Subject, Body pre-filled correctly
- [ ] Sender name shows "Mr Steven Girgis / Physiotherapist"
- [ ] "Open in Outlook" opens Microsoft Outlook with a draft (not an error)
- [ ] PDF is attached to the draft email in Outlook
- [ ] CC field populated if the template has a CC address

---

## 8. PRODA (Step 5)

- [ ] PRODA modal shows exactly 4 fields: Medicare Number, IRN, First Name, DOB
- [ ] Values match what was extracted / entered in Step 2
- [ ] Copy buttons work (click copies to clipboard)

---

## 9. Settings

- [ ] Settings page opens
- [ ] All 7 workflow templates show status (uploaded / not uploaded)
- [ ] "Open" button reveals the template in Finder (not open in Pages)
- [ ] "Upload" button allows selecting a `.docx` and saves it
- [ ] After uploading, status changes to green tick
- [ ] Scan days and keyword settings save correctly and persist after restart

---

## 10. Patient Database

- [ ] After completing a workflow, patient appears in the Patients tab
- [ ] Medicare Number, IRN, DOB are stored
- [ ] Search by name filters results correctly

---

## Failure reference

| Symptom | Likely cause | File to check |
|---|---|---|
| Version not updating | updater.py timeout / network | `update.log` |
| 502 on Read & Extract | Cliniko server blip | `cliniko.py` retry logic |
| Image files in worklist | Filter bug | `worklist.py` _PDF_EXTENSIONS |
| Blank fields after extract | Claude OCR / bad PDF | `pdf_extractor.py` |
| "Could not open PDF" | docx2pdf / Word not found | `word_builder.py` fallback |
| Outlook doesn't open | AppleScript error | `emailer.py` |
| Template placeholders not replaced | Token mismatch | `word_builder.py` + template file |
