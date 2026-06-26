/* ================================================================
   Cliniko Assistant — Frontend JS
   All Python calls go via window.pywebview.api.*
   ================================================================ */

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  currentScreen: 's1',
  worklist: [],
  currentEntry: null,       // selected worklist row
  currentFields: {},        // extracted fields from PDF
  currentWorkflow: null,
  generatedPdfName: null,
  patients: [],
};

// ── Navigation ─────────────────────────────────────────────────────────────
function goTo(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  state.currentScreen = id;

  if (id === 's_patients') loadPatients();
  if (id === 's7') loadSettings();
  if (id === 's_how') renderHowSteps();
}

// ── API helper ─────────────────────────────────────────────────────────────
function api() {
  // During dev in browser (no pywebview), return a stub
  if (!window.pywebview) return null;
  return window.pywebview.api;
}

// ── SCREEN 1: WORKLIST ────────────────────────────────────────────────────
async function refreshWorklist() {
  const days = parseInt(document.getElementById('scan-days').value) || 7;
  const tbody = document.getElementById('wl-tbody');
  const status = document.getElementById('wl-status');
  const badge = document.getElementById('wl-count-badge');

  tbody.innerHTML = `<tr><td colspan="5" style="padding:32px 16px;text-align:center;">
    <div style="display:flex;align-items:center;justify-content:center;gap:8px;color:var(--text-muted);font-size:13px;">
      <span class="spinner"></span> Scanning Cliniko for last ${days} days...
    </div></td></tr>`;
  badge.textContent = '…';
  status.textContent = '';

  const a = api();
  if (!a) { renderMockWorklist(); return; }

  const withTimeout = (promise, ms, label) =>
    Promise.race([promise, new Promise((_, rej) => setTimeout(() => rej(new Error(`Timed out after ${ms/1000}s (${label})`)), ms))]);

  try {
    // Update last-run display
    const lastRun = await withTimeout(a.get_last_run(), 10000, 'get_last_run');
    if (lastRun) {
      const d = new Date(lastRun);
      document.getElementById('last-run-label').textContent =
        `Last run: ${d.toLocaleDateString('en-AU', { day:'2-digit', month:'short' })} ${d.toLocaleTimeString('en-AU', { hour:'2-digit', minute:'2-digit' })}`;
    }

    const entries = await withTimeout(a.get_worklist(days), 15000, 'get_worklist');
    state.worklist = entries;
    renderWorklist(entries);
    badge.textContent = entries.filter(e => !e.sent).length + ' pending';

    await a.update_last_run();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="padding:24px 16px;">
      <div class="error-banner" style="margin:0">Error loading worklist: ${err}</div>
    </td></tr>`;
    badge.textContent = 'error';
  }
}

function renderWorklist(entries) {
  const tbody = document.getElementById('wl-tbody');
  if (!entries || !entries.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="padding:32px 16px;text-align:center;color:var(--text-muted);font-size:13px;">
      No EPC, DVA or Workcover files found in the last ${document.getElementById('scan-days').value || 7} days.<br>
      <span style="font-size:11px;margin-top:4px;display:block;">Try increasing the date range or upload a file in Cliniko first.</span></td></tr>`;
    return;
  }
  tbody.innerHTML = entries.map((e, i) => {
    const tag = fileTypeTag(e.file_name, e.workflow);
    const sentCls = e.sent ? 'sent' : '';
    const status = e.sent
      ? `<span class="status-badge sent-label">✓ Sent</span>`
      : `<span class="status-badge pending">● Pending</span>`;
    const apptDate = e.appointment_date
      ? new Date(e.appointment_date).toLocaleDateString('en-AU', { day:'2-digit', month:'short', year:'numeric' })
      : '—';
    const actionBtn = e.sent
      ? `<button class="btn btn-ghost btn-sm" onclick="selectEntry(${i})" style="opacity:0.6;">Re-process →</button>`
      : `<button class="btn btn-primary btn-sm" onclick="selectEntry(${i})">Process →</button>`;
    return `<tr class="worklist-row ${sentCls}" onclick="selectEntry(${i})">`
      <td>${status}</td>
      <td><span class="patient-name">${e.patient_name || '—'}</span></td>
      <td>${tag} <span style="font-size:12px;color:var(--text-secondary);margin-left:4px;">${e.file_name}</span></td>
      <td><span class="appt-date">${apptDate}</span></td>
      <td style="text-align:right;">${actionBtn}</td>
    </tr>`;
  }).join('');
}

function fileTypeTag(filename, workflow) {
  const n = (filename || '').toLowerCase();
  if (n.includes('epc') || (workflow || '').startsWith('epc'))
    return `<span class="file-tag epc">EPC</span>`;
  if (n.includes('dva') || (workflow || '').startsWith('dva'))
    return `<span class="file-tag dva">DVA</span>`;
  if (n.includes('workcover') || n.includes('wc') || (workflow || '').startsWith('wc'))
    return `<span class="file-tag wc">WC</span>`;
  return `<span class="file-tag">PDF</span>`;
}

// ── SCREEN 2: FILE SELECTION ───────────────────────────────────────────────
async function selectEntry(idx) {
  const entry = state.worklist[idx];
  state.currentEntry = entry;
  state.currentWorkflow = entry.workflow || 'epc_new';

  document.getElementById('s2-patient-bc').textContent = entry.patient_name;
  document.getElementById('s2-patient-name').textContent = entry.patient_name;
  document.getElementById('s2-wf-hint').textContent = workflowLabel(state.currentWorkflow);

  // Set workflow selector to auto-detected value
  const wfSel = document.getElementById('s2-workflow-select');
  wfSel.value = state.currentWorkflow;

  // Load available attachments
  const fileSel = document.getElementById('s2-file-select');
  fileSel.innerHTML = `<option>Loading...</option>`;
  document.getElementById('s2-status').textContent = '';
  goTo('s2');

  const a = api();
  if (!a) {
    fileSel.innerHTML = `<option value="${entry.download_url}">${entry.file_name}</option>`;
    document.getElementById('s2-file-count').textContent = '1 file';
    return;
  }

  try {
    const atts = await a.get_patient_attachments(entry.patient_id);
    // Merge the already-found worklist file if not in list
    let files = atts.length ? atts : [{ filename: entry.file_name, download_url: entry.download_url, recommended: true }];

    document.getElementById('s2-file-count').textContent = `${files.length} file${files.length !== 1 ? 's' : ''}`;

    fileSel.innerHTML = files.map(f => {
      const label = f.filename + (f.recommended ? ' ★' : '');
      return `<option value="${f.download_url}" data-rec="${f.recommended}" data-name="${f.filename}">${label}</option>`;
    }).join('');

    // Pre-select recommended or matching entry
    const recOpt = Array.from(fileSel.options).find(o => o.dataset.rec === 'true');
    const entryOpt = Array.from(fileSel.options).find(o => o.dataset.name === entry.file_name);
    if (entryOpt) fileSel.value = entryOpt.value;
    else if (recOpt) fileSel.value = recOpt.value;

    onFileChange();
  } catch (err) {
    fileSel.innerHTML = `<option value="${entry.download_url}">${entry.file_name}</option>`;
  }
}

function onFileChange() {
  const sel = document.getElementById('s2-file-select');
  const opt = sel.options[sel.selectedIndex];
  const isRec = opt && opt.dataset.rec === 'true';
  document.getElementById('s2-rec-tag').style.display = isRec ? 'inline-flex' : 'none';
  document.getElementById('s2-rec-hint').textContent = isRec ? 'Best match for this patient' : '';
}

function onWorkflowChange() {
  const sel = document.getElementById('s2-workflow-select');
  state.currentWorkflow = sel.value;
  document.getElementById('s2-wf-hint').textContent = workflowLabel(sel.value);
}

async function previewSourcePdf() {
  const sel = document.getElementById('s2-file-select');
  const url = sel.value;
  const filename = sel.options[sel.selectedIndex]?.dataset?.name || '';
  const a = api();
  if (!a) { alert('Preview only available when connected to Python backend.'); return; }
  document.getElementById('s2-status').textContent = 'Opening in Preview…';
  const r = await a.preview_source_pdf(url, filename);
  document.getElementById('s2-status').textContent = r.ok ? '' : 'Error: ' + r.error;
}

async function extractPdf() {
  const url = document.getElementById('s2-file-select').value;
  const btn = document.getElementById('s2-extract-btn');
  const status = document.getElementById('s2-status');

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Reading PDF…';
  status.textContent = '';

  const a = api();
  if (!a) {
    // Demo mode
    populateFields({ patient_name:'Demo Patient', patient_dob:'01/01/1980', medicare_number:'1234567890', irn:'1', condition:'Lower back pain', referral_date:'01/06/2026', doctor_name:'Dr Smith', doctor_provider_no:'1234567A', doctor_email:'dr.smith@example.com' });
    goTo('s3');
    btn.disabled = false;
    btn.innerHTML = 'Read &amp; Extract →';
    return;
  }

  try {
    const fields = await a.extract_pdf(url);
    state.currentFields = fields;
    populateFields(fields);
    goTo('s3');

    // Update breadcrumbs
    const name = state.currentEntry?.patient_name || '';
    document.getElementById('s3-patient-bc').textContent = name;
    document.getElementById('s4-patient-bc').textContent = name;
    document.getElementById('s5-patient-bc').textContent = name;

    const count = Object.values(fields).filter(v => v && v !== 'Unknown' && v !== '').length;
    document.getElementById('s3-field-count').textContent = `${count} fields found`;
    document.getElementById('s3-card-title').textContent = `Extracted fields — ${state.currentEntry?.file_name || ''}`;
  } catch (err) {
    status.textContent = 'Error reading PDF: ' + err;
  }

  btn.disabled = false;
  btn.innerHTML = 'Read &amp; Extract →';
}

// ── SCREEN 3: REVIEW FIELDS ────────────────────────────────────────────────
function populateFields(fields) {
  const map = {
    patient_name: 'f-patient_name',
    patient_dob: 'f-patient_dob',
    medicare_number: 'f-medicare_number',
    irn: 'f-irn',
    condition: 'f-condition',
    referral_date: 'f-referral_date',
    doctor_name: 'f-doctor_name',
    doctor_provider_no: 'f-doctor_provider_no',
    doctor_email: 'f-doctor_email',
  };
  for (const [k, id] of Object.entries(map)) {
    const el = document.getElementById(id);
    if (el) el.value = fields[k] || '';
  }
}

function collectFields() {
  return {
    patient_name: document.getElementById('f-patient_name').value,
    patient_dob: document.getElementById('f-patient_dob').value,
    medicare_number: document.getElementById('f-medicare_number').value,
    irn: document.getElementById('f-irn').value,
    condition: document.getElementById('f-condition').value,
    referral_date: document.getElementById('f-referral_date').value,
    doctor_name: document.getElementById('f-doctor_name').value,
    doctor_provider_no: document.getElementById('f-doctor_provider_no').value,
    doctor_email: document.getElementById('f-doctor_email').value,
    // Add patient info from current entry
    patient_first_name: state.currentEntry?.patient_first_name || '',
    patient_id: state.currentEntry?.patient_id || '',
    appointment_date: state.currentEntry?.appointment_date || '',
  };
}

function toggleSourcePanel() {
  const panel = document.getElementById('source-pdf-panel');
  const btn = document.getElementById('toggle-source-btn');
  const isOpen = panel.classList.contains('open');
  panel.classList.toggle('open', !isOpen);
  btn.textContent = isOpen ? 'Show Source PDF ↗' : 'Hide Source PDF';
}

async function generateDocument() {
  const fields = collectFields();
  state.currentFields = fields;
  const btn = document.getElementById('s3-gen-btn');
  const status = document.getElementById('s3-status');

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating…';
  status.textContent = '';

  const a = api();
  if (!a) {
    state.generatedPdfName = 'Demo_Letter.pdf';
    document.getElementById('s4-filename').textContent = 'Demo_Letter.pdf';
    goTo('s4');
    btn.disabled = false;
    btn.innerHTML = 'Generate Document →';
    return;
  }

  const result = await a.generate_document(state.currentWorkflow, fields);
  if (result.ok) {
    state.generatedPdfName = result.filename;
    document.getElementById('s4-filename').textContent = result.filename;
    document.getElementById('s5-pdf-name').textContent = result.filename;
    document.getElementById('s5-to').value = fields.doctor_email || '';
    // Pre-fill subject and body from email template
    if (a) {
      try {
        const rendered = await a.render_email(state.currentWorkflow, fields);
        document.getElementById('s5-subject').value = rendered.subject || '';
        document.getElementById('s5-body').value = rendered.body || '';
      } catch (_) {}
    }
    goTo('s4');
  } else {
    status.textContent = 'Error: ' + result.error;
  }

  btn.disabled = false;
  btn.innerHTML = 'Generate Document →';
}

// ── SCREEN 4: PREVIEW ─────────────────────────────────────────────────────
async function openGeneratedPdf() {
  const a = api();
  if (!a) { alert('Open in Preview requires the Python backend.'); return; }
  const r = await a.open_generated_pdf();
  if (!r.ok) alert('Could not open PDF: ' + r.error);
}

// ── SCREEN 5: EMAIL ────────────────────────────────────────────────────────
async function openOutlookPreview() {
  // Open Outlook directly with the edited subject/body from the send screen
  const a = api();
  const fields = collectFields();
  const to = document.getElementById('s5-to').value || fields.doctor_email || '';
  const subject = document.getElementById('s5-subject').value || '';
  const body = document.getElementById('s5-body').value || '';
  const sendBtn = document.getElementById('s5-send-btn');

  if (sendBtn) {
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span class="spinner"></span> Opening Outlook…';
  }

  let ok = false;
  if (a) {
    try {
      const result = await a.send_email_direct(to, subject, body, state.currentWorkflow, fields);
      ok = result.ok;
      if (!ok) {
        alert('Send failed: ' + result.error);
        if (sendBtn) { sendBtn.disabled = false; sendBtn.textContent = 'Review & Send →'; }
        return;
      }
    } catch (err) {
      alert('Send error: ' + err);
      if (sendBtn) { sendBtn.disabled = false; sendBtn.textContent = 'Review & Send →'; }
      return;
    }
  } else {
    ok = true;
  }

  if (ok) {
    if (sendBtn) { sendBtn.disabled = false; sendBtn.textContent = 'Review & Send →'; }
    if (a && state.currentEntry) {
      await a.mark_sent(
        state.currentEntry.patient_id,
        state.currentEntry.file_name,
        state.currentEntry.appointment_date
      );
      await a.save_patient(
        state.currentEntry.patient_id,
        fields.patient_name,
        state.currentEntry.patient_first_name || '',
        fields.medicare_number,
        fields.irn,
        fields.patient_dob,
        state.currentWorkflow
      );
    }
    showProdaScreen(to);
  }
}

async function confirmSend() {
  // Legacy — no longer used since modal was removed
}

function closeOutlookModal(e) {
  if (e.target === document.getElementById('outlookModal'))
    document.getElementById('outlookModal').classList.remove('open');
}

// ── SCREEN 6: PRODA ────────────────────────────────────────────────────────
function showProdaScreen(sentTo) {
  const fields = collectFields();
  const prodaFields = buildProdaFields(fields);
  document.getElementById('s6-proda-fields').innerHTML = prodaFields;
  document.getElementById('s6-sent-label').textContent = sentTo ? `Sent to ${sentTo}` : '';
  goTo('s6');
}

function buildProdaFields(fields) {
  const rows = [
    { label: 'Medicare Number', key: 'medicare_number', source: 'Referral PDF' },
    { label: 'Individual Reference Number (IRN)', key: 'irn', source: 'Referral PDF' },
    { label: 'First Name', key: 'patient_first_name', source: 'Cliniko record' },
    { label: 'Date of Birth', key: 'patient_dob', source: 'Referral PDF' },
  ];
  return rows.map(r => {
    const val = fields[r.key] || '—';
    return `<div class="proda-field">
      <div class="proda-field-left">
        <div class="proda-field-label">${r.label}</div>
        <div class="proda-field-value">${val}</div>
        <div class="proda-source">${r.source}</div>
      </div>
      <button class="btn-copy" onclick="copyField(this,'${val.replace(/'/g, "\\'")}')">📋 Copy</button>
    </div>`;
  }).join('');
}

function backToWorklist() {
  goTo('s1');
  refreshWorklist();
}

// ── PRODA MODAL ─────────────────────────────────────────────────────────────
function openProdaModal() {
  const fields = collectFields();
  document.getElementById('proda-modal-title').textContent = `📋 PRODA — ${fields.patient_name || 'Patient'}`;
  document.getElementById('proda-modal-fields').innerHTML = buildProdaFields(fields);
  document.getElementById('prodaModal').classList.add('open');
}

function closeProdaModal(e) {
  if (e.target === document.getElementById('prodaModal'))
    document.getElementById('prodaModal').classList.remove('open');
}

// ── PATIENTS SCREEN ─────────────────────────────────────────────────────────
async function loadPatients() {
  const a = api();
  if (!a) { renderPatients([]); return; }
  try {
    const rows = await a.search_patients('');
    state.patients = rows;
    renderPatients(rows);
    document.getElementById('patients-count-badge').textContent = rows.length + ' patients';
  } catch (_) {
    renderPatients([]);
  }
}

function filterPatients() {
  const q = document.getElementById('patient-search').value.toLowerCase();
  const filtered = state.patients.filter(p =>
    (p.patient_name || '').toLowerCase().includes(q) ||
    (p.medicare_number || '').includes(q)
  );
  renderPatients(filtered);
}

function renderPatients(rows) {
  const tbody = document.getElementById('patients-tbody');
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="padding:32px;text-align:center;color:var(--text-muted);font-size:13px;">No patients found.</td></tr>`;
    document.getElementById('patients-count-badge').textContent = '0 patients';
    return;
  }
  tbody.innerHTML = rows.map(p => {
    const actioned = p.last_actioned
      ? new Date(p.last_actioned).toLocaleDateString('en-AU', { day:'2-digit', month:'short', year:'numeric' })
      : '—';
    return `<tr class="worklist-row" onclick="openPatientProda('${p.patient_id}')">
      <td class="patient-name">${p.patient_name || '—'}</td>
      <td style="font-family:'DM Mono',monospace;font-size:12px;">${p.medicare_number || '—'}</td>
      <td style="font-family:'DM Mono',monospace;font-size:12px;">${p.irn || '—'}</td>
      <td style="font-size:12px;">${p.dob || '—'}</td>
      <td>${p.last_workflow ? workflowLabel(p.last_workflow) : '—'}</td>
      <td style="font-size:12px;">${actioned}</td>
      <td style="text-align:right;"><button class="btn btn-secondary btn-sm" onclick="event.stopPropagation();openPatientProda('${p.patient_id}')">📋 PRODA</button></td>
    </tr>`;
  }).join('');
}

function openPatientProda(patientId) {
  const p = state.patients.find(r => r.patient_id === patientId);
  if (!p) return;
  const fields = {
    patient_name: p.patient_name,
    patient_dob: p.dob,
    medicare_number: p.medicare_number,
    irn: p.irn,
    condition: '',
    referral_date: '',
    doctor_name: '',
    doctor_provider_no: '',
  };
  document.getElementById('proda-modal-title').textContent = `📋 PRODA — ${p.patient_name}`;
  document.getElementById('proda-modal-fields').innerHTML = buildProdaFields(fields);
  document.getElementById('prodaModal').classList.add('open');
}

// ── HOW SCREEN ─────────────────────────────────────────────────────────────
function renderHowSteps() {
  const steps = [
    { num:'1', title:'The app checks Cliniko for recent appointments', body:'It looks at patients who had appointments in the last 7 days (or however many days you set) and scans their files for anything that looks like an EPC, DVA, or Workcover referral.' },
    { num:'2', title:'A worklist is built for you', body:"Each patient with a relevant file appears in the worklist with their name, file type, and appointment date. Patients you've already processed are shown greyed out at the bottom so you don't accidentally double up." },
    { num:'3', title:'You select a patient and the app reads their PDF', body:"Click 'Process →' on any row. The app opens the referral PDF and uses text extraction to read the key fields: patient name, date of birth, Medicare number, IRN, diagnosis, doctor's details, and more." },
    { num:'4', title:'Fields are pre-filled for you to review', body:'All extracted information is shown in editable fields. You can correct anything before the document is generated — the app always gives you a chance to check first.' },
    { num:'5', title:'A referral letter is generated from your Word template', body:'The app takes your uploaded Word template (from Settings), fills in all the fields, and creates a ready-to-send PDF.' },
    { num:'6', title:'You review the email and click Send', body:"The email is pre-addressed to the doctor, with your letter attached. You can review the full message before anything is sent. Emails go through your Outlook / Microsoft 365 account." },
    { num:'7', title:'PRODA fields are shown for manual entry', body:"After sending, the app shows you a PRODA copy panel with all the fields you need to enter into the PRODA portal. Click the clipboard icon next to each one to copy it instantly." },
  ];
  document.getElementById('how-steps').innerHTML = steps.map(s => `
    <div style="display:flex;gap:16px;padding:16px 20px;border-bottom:1px solid var(--border);">
      <div style="flex-shrink:0;width:28px;height:28px;border-radius:50%;background:var(--teal);color:white;font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;margin-top:1px;">${s.num}</div>
      <div>
        <div style="font-size:13px;font-weight:600;margin-bottom:4px;">${s.title}</div>
        <div style="font-size:12px;color:var(--text-secondary);line-height:1.7;">${s.body}</div>
      </div>
    </div>`).join('');
}

// ── SETTINGS ────────────────────────────────────────────────────────────────
async function loadSettings() {
  const a = api();
  if (!a) { renderTemplateRows({}); return; }

  try {
    const [tmplStatus, scanSettings] = await Promise.all([
      a.get_template_status(),
      a.get_scan_settings(),
    ]);

    document.getElementById('cfg-days').value = scanSettings.scan_days || 7;
    document.getElementById('cfg-wl-keywords').value = scanSettings.worklist_keywords || '';
    document.getElementById('cfg-pref-keywords').value = scanSettings.preferred_keywords || '';

    renderTemplateRows(tmplStatus);
  } catch (err) {
    console.error('Settings load error', err);
  }
}

const WORKFLOW_KEYS = ['epc_new','epc_final','dva_new','dva_final','wc_new','wc_final_form032'];
const WORKFLOW_LABELS_MAP = {
  epc_new:'EPC — New Patient', epc_final:'EPC — Final Consult',
  dva_new:'DVA — New Patient', dva_final:'DVA — Final Consult',
  wc_new:'Workcover — New Patient', wc_final_form032:'Workcover — Final ★ 2 templates',
};

function workflowLabel(key) {
  return WORKFLOW_LABELS_MAP[key] || key;
}

let _emailEditorWorkflow = null;

function renderTemplateRows(tmplStatus) {
  const container = document.getElementById('tmpl-rows');
  container.innerHTML = WORKFLOW_KEYS.map((key, i) => {
    const st = (tmplStatus || {})[key] || {};
    const exists = st.exists;
    const fname = st.filename;
    const borderTop = i > 0 ? 'border-top:1px solid var(--border);' : '';
    return `<div class="tmpl-grid" style="${borderTop}">
      <div class="tmpl-cell">
        <span style="font-size:13px;font-weight:500;">${workflowLabel(key)}</span>
      </div>
      <div class="tmpl-cell">
        ${exists
          ? `<span style="font-size:11px;font-weight:600;color:var(--teal);">✓</span>
             <span style="font-size:12px;font-family:'DM Mono',monospace;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;max-width:120px;">${fname}</span>
             <button class="btn btn-secondary btn-sm" style="margin-left:auto;" onclick="openTemplate('${key}')">Open ↗</button>
             <button class="btn btn-ghost btn-sm" onclick="uploadTemplate('${key}')">Replace</button>`
          : `<span style="font-size:11px;color:var(--text-muted);">No template</span>
             <button class="btn btn-primary btn-sm" style="margin-left:auto;" onclick="uploadTemplate('${key}')">Upload ↑</button>`
        }
      </div>
      <div class="tmpl-cell">
        <button class="btn btn-secondary btn-sm" onclick="openEmailEditor('${key}')">Edit email template</button>
      </div>
    </div>`;
  }).join('');
}

async function openTemplate(workflowKey) {
  const a = api();
  if (!a) { alert('Requires Python backend.'); return; }
  const r = await a.open_template(workflowKey);
  if (!r.ok) alert('Could not open template: ' + r.error);
}

async function uploadTemplate(workflowKey) {
  const a = api();
  if (!a) { alert('Template upload requires the Python backend.'); return; }
  const result = await a.upload_template(workflowKey);
  if (result.ok) {
    showSettingsSaved();
    loadSettings();
  } else if (result.error !== 'cancelled') {
    alert('Upload failed: ' + result.error);
  }
}

async function saveScanSettings() {
  const btn = document.querySelector('[onclick="saveScanSettings()"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

  const a = api();
  const days = parseInt(document.getElementById('cfg-days').value) || 7;
  const wl = document.getElementById('cfg-wl-keywords').value;
  const pref = document.getElementById('cfg-pref-keywords').value;

  if (!a) {
    showSettingsSaved();
    if (btn) { btn.disabled = false; btn.textContent = 'Save Settings'; }
    return;
  }
  try {
    const r = await a.save_scan_settings(days, wl, pref);
    if (!r) { alert('Save failed: no response from backend'); }
    else if (r.ok) showSettingsSaved();
    else alert('Save failed: ' + r.error);
  } catch (err) {
    alert('Save error: ' + err);
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Save Settings'; }
}

function showSettingsSaved() {
  const badge = document.getElementById('settings-saved-badge');
  badge.style.display = 'inline-flex';
  setTimeout(() => { badge.style.display = 'none'; }, 2500);
}

// ── EMAIL EDITOR MODAL ──────────────────────────────────────────────────────
async function openEmailEditor(workflowKey) {
  _emailEditorWorkflow = workflowKey;
  document.getElementById('ee-title').textContent = `Edit Email — ${workflowLabel(workflowKey)}`;

  const a = api();
  if (a) {
    try {
      const tmpl = await a.get_email_template(workflowKey);
      document.getElementById('ee-subject').value = tmpl.subject || '';
      document.getElementById('ee-body').value = tmpl.body || '';
      document.getElementById('ee-cc').value = tmpl.cc || '';
    } catch (_) {}
  }
  document.getElementById('emailEditorModal').classList.add('open');
}

function closeEmailEditor(e) {
  if (e.target === document.getElementById('emailEditorModal'))
    document.getElementById('emailEditorModal').classList.remove('open');
}

function insertEE(placeholder) {
  const ta = document.getElementById('ee-body');
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  ta.value = ta.value.substring(0, start) + placeholder + ta.value.substring(end);
  ta.focus();
  ta.selectionStart = ta.selectionEnd = start + placeholder.length;
}

async function saveEmailTemplate() {
  if (!_emailEditorWorkflow) return;
  const subject = document.getElementById('ee-subject').value;
  const body = document.getElementById('ee-body').value;
  const cc = document.getElementById('ee-cc').value;
  const a = api();
  if (a) {
    const r = await a.save_email_template(_emailEditorWorkflow, subject, body, cc);
    if (!r.ok) { alert('Save failed: ' + r.error); return; }
  }
  document.getElementById('emailEditorModal').classList.remove('open');
  showSettingsSaved();
}

// ── Copy helper ─────────────────────────────────────────────────────────────
function copyField(btn, val) {
  if (!val || val === '—') return;
  navigator.clipboard.writeText(val).then(() => {
    const orig = btn.textContent;
    btn.classList.add('copied');
    btn.textContent = '✓ Copied';
    setTimeout(() => { btn.classList.remove('copied'); btn.textContent = orig; }, 1500);
  });
}

// ── Mock data for browser-only dev ─────────────────────────────────────────
function renderMockWorklist() {
  const mock = [
    { patient_id:'1', patient_name:'Sarah Thompson', file_name:'EPC_Referral_Thompson.pdf', appointment_date:'2026-06-10', workflow:'epc_new', sent:false },
    { patient_id:'2', patient_name:'Michael Chen', file_name:'Workcover_Form_Chen.pdf', appointment_date:'2026-06-09', workflow:'wc_new', sent:false },
    { patient_id:'3', patient_name:'Emma Wilson', file_name:'DVA_Referral_Wilson.pdf', appointment_date:'2026-06-08', workflow:'dva_new', sent:true },
  ];
  state.worklist = mock;
  renderWorklist(mock);
  document.getElementById('wl-count-badge').textContent = '2 pending';
}

// ── Init ────────────────────────────────────────────────────────────────────
// Set version immediately — scripts are at bottom of body so DOM is already ready
(function() {
  const el = document.getElementById('app-version');
  if (el && window.APP_VERSION) el.textContent = `v${window.APP_VERSION}`;
})();

window.addEventListener('pywebviewready', () => {
  refreshWorklist();
});

// If no pywebview after 300ms, show mock data
setTimeout(() => {
  if (!window.pywebview && state.currentScreen === 's1') {
    renderMockWorklist();
  }
}, 300);
