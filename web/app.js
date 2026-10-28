'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const severityNames = ['', 'Critical', 'Urgent', 'Priority', 'Normal'];
const pages = {
  dashboard: ['Overview', 'Clinic overview', 'A clear view of your patients, priorities, and next steps.'],
  assessments: ['Patient assessments','Patient assessment inbox','Patient-entered answers. Transparent suggestions. Staff-confirmed priorities.'],
  patients: ['Patients', 'Patient directory', 'Find a record, register a patient, or prepare their next visit.'],
  queue: ['Live queue', 'The right care, in order', 'Manage arrivals and consultations with staff-assigned priorities.'],
  history: ['Visit history', 'Every visit, accounted for', 'A complete record of consultations and no-shows.'],
  reports: ['Reports', 'Clarity through your data', 'Live clinic statistics and reports powered by C sorting algorithms.'],
  storage: ['Data & persistence', 'Local records. Lasting continuity.', 'Manage your saved clinic snapshot and understand its status.']
};
let state = null, token = '', pending = false, connection = false, searchResults = null;
let reportRows = null, reportDescription = '', persistence = {}, checkinID = '', confirmAction = null, toastTimer;
let page = 'dashboard', assessments = [], activeAssessment = null, publicToken = '', symptomCatalog = null;
function severity(p) { if(p.severity == null) return '<span class="status">Unassigned · staff review needed</span>'; return `<span class="severity s${p.severity}">${p.severity} · ${severityNames[p.severity]}</span>`; }
function initials(name) { return name.trim().split(/\s+/).slice(0, 2).map(s => s[0]).join('').toUpperCase(); }
function person(p) { return `<div class="person"><span class="avatar" aria-hidden="true">${esc(initials(p.name))}</span><span><span class="patient-name">${esc(p.name)}</span><span class="patient-sub">ID ${esc(p.id)} · ${p.age} years</span></span></div>`; }
function status(p) { if(p.needs_review) return '<span class="status">Awaiting assessment review</span>'; return `<span class="status ${esc(p.status)}">${esc(p.status)}</span>`; }
function dateTime(seconds) { return seconds ? new Date(seconds * 1000).toLocaleString([], {dateStyle:'medium', timeStyle:'short'}) : '—'; }
function empty(title, detail, symbol = 'users') { return `<div class="empty">${icon(symbol)}<strong>${esc(title)}</strong><p>${esc(detail)}</p></div>`; }
function error(message) { $('#error-text').textContent = message; $('#error-banner').hidden = false; }
function toast(message) { clearTimeout(toastTimer); $('#toast').textContent = message; $('#toast').hidden = false; toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500); }
function setConnection(online) {
  connection = online;
  $('#connection').textContent = online ? (pending ? 'Working…' : 'Local engine connected') : 'Offline · reconnect to continue';
  $('#connection').classList.toggle('offline', !online);
}
async function request(body = null, quiet = false) {
  if (pending) return null;
  pending = true;
  document.body.classList.add('busy'); $('#main').setAttribute('aria-busy', 'true');
  for (const b of document.querySelectorAll('button')) { b.dataset.disabledBefore = b.disabled ? 'yes' : 'no'; b.disabled = true; }
  setConnection(connection);
  try {
    const response = await fetch(body ? '/api/action' : '/api/state', {
      method: body ? 'POST' : 'GET', headers: {'X-Clinic-Token':token, ...(body ? {'Content-Type':'application/json'} : {})},
      ...(body ? {body:JSON.stringify(body)} : {}), signal:AbortSignal.timeout(15000)
    });
    const data = await response.json();
    setConnection(true);
    if (data.state) {
      if (persistence.revision && data.persistence?.revision !== persistence.revision && !body) { reportRows = null; reportDescription = ''; searchResults = null; }
      assessments = data.assessments || assessments;
      state = data.state; persistence = data.persistence || persistence;
      if (body?.action === 'report' && data.ok) {
        reportRows = data.state.patients;
        reportDescription = `${body.algorithm === 1 ? 'Merge Sort' : 'Insertion Sort'} · ${['Name','Patient ID','Severity'][body.key]} · generated ${new Date().toLocaleTimeString()}`;
      } else if (body && !['find_id','find_name','state'].includes(body.action)) {
        reportRows = null; reportDescription = ''; searchResults = null;
      }
      if (['find_id','find_name'].includes(body?.action) && data.ok) searchResults = data.matches;
    }
    if (!response.ok || !data.ok) {
      if (response.status === 403) setConnection(false);
      throw new Error(data.message || 'The operation could not be completed.');
    }
    if (body && !quiet) { $('#error-banner').hidden = true; toast(data.message); }
    return data;
  } catch (e) {
    if (e.name === 'TypeError' || e.name === 'TimeoutError') {
      setConnection(false); error('Cannot reach the local engine. Refresh or restart the launcher. If a request timed out, refresh before retrying: it may have saved.');
    } else error(e.message);
    return null;
  } finally {
    pending = false; document.body.classList.remove('busy'); $('#main').removeAttribute('aria-busy');
    for (const b of document.querySelectorAll('button')) b.disabled = b.dataset.disabledBefore === 'yes';
    setConnection(connection);
    if (state) render();
  }
}
function statCard(label, value, note, symbol) {
  return `<article class="stat"><div><div class="stat-label">${esc(label)}</div><div class="stat-value">${value}</div><div class="stat-note">${esc(note)}</div></div><span class="stat-icon">${icon(symbol)}</span></article>`;
}
function queueTable(rows, preview = false) {
  if (!rows.length) return empty('A clear queue', 'Check in a registered patient to begin.', 'list');
  return `<table><thead><tr><th scope="col">Patient</th><th scope="col">Priority</th><th scope="col">Est. wait</th>${preview ? '' : '<th scope="col">Arrival</th><th scope="col">Status</th><th scope="col">Actions</th>'}</tr></thead><tbody>${rows.map(p => `<tr><td>${person(p)}</td><td>${severity(p)}</td><td>${p.wait} min</td>${preview ? '' : `<td>#${esc(p.order)}<span class="patient-sub">${dateTime(p.checked_in)}</span></td><td>${status(p)}</td><td class="table-actions"><button data-history="${esc(p.id)}" aria-label="View history for ${esc(p.name)}">History</button><button class="danger" data-no-show="${esc(p.id)}" aria-label="Mark ${esc(p.name)} as no-show">No-show</button></td>`}</tr>`).join('')}</tbody></table>`;
}
function patientTable(rows, report = false) {
  if (!rows.length) return empty('No patients found', 'Register a patient or try another exact search.');
  return `<table><thead><tr><th scope="col">Patient</th><th scope="col">Priority</th><th scope="col">Status</th><th scope="col">Est. wait</th>${report ? '' : '<th scope="col">Actions</th>'}</tr></thead><tbody>${rows.map(p => `<tr><td>${person(p)}</td><td>${severity(p)}</td><td>${status(p)}</td><td>${p.wait === null ? '—' : `${p.wait} min`}</td>${report ? '' : `<td><div class="table-actions">${!p.needs_review && ['Registered','Completed','No-show'].includes(p.status) ? `<button data-checkin="${esc(p.id)}" aria-label="Check in ${esc(p.name)}">Check in</button>` : ''}<button data-invite="${esc(p.id)}" aria-label="Invite ${esc(p.name)} to patient assessment">Patient form</button><button data-history="${esc(p.id)}" aria-label="View history for ${esc(p.name)}">History</button></div></td>`}</tr>`).join('')}</tbody></table>`;
}
function historyTable(patientID = '', newest = true, limit = Infinity) {
  let rows = [], n = state.history.length;
  for (let i = 0; i < n && rows.length < limit; i++) {
    const v = state.history[newest ? n - 1 - i : i];
    if (!patientID || v.patient_id === patientID) rows.push(v);
  }
  if (!rows.length) return empty('No visits recorded yet', 'Completed consultations and no-shows will appear here.', 'clock');
  return `<table><thead><tr><th scope="col">Patient</th><th scope="col">Visit</th><th scope="col">Priority</th><th scope="col">Outcome</th><th scope="col">Check-in</th><th scope="col">Finished</th></tr></thead><tbody>${rows.map(v => `<tr><td><span class="patient-name">${esc(v.name)}</span><span class="patient-sub">ID ${esc(v.patient_id)}</span></td><td>#${esc(v.order)}</td><td>${severity(v)}</td><td>${status({status:v.outcome})}</td><td>${dateTime(v.checked_in)}</td><td>${dateTime(v.ended)}</td></tr>`).join('')}</tbody></table>`;
}
function activeRoom() {
  const p = state.active;
  if (p) return `<div class="room-body"><div class="room-avatar">${esc(initials(p.name))}</div><h3>${esc(p.name)}</h3><p>ID ${esc(p.id)} · ${p.age} years<br>${severity(p)}<br>${status(p)}</p><button class="primary" data-action="complete">${icon('check')}Complete consultation</button></div>`;
  return `<div class="room-body"><div class="room-avatar">${icon('users')}</div><h3>Ready for the next patient</h3><p>${state.queue.length ? `Next: ${esc(state.queue[0].name)}<br>${severity(state.queue[0])}` : 'No consultation in progress.<br>Your next patient will appear here.'}</p><button class="primary" data-action="next" ${!state.queue.length ? 'disabled' : ''}>${icon('arrow')}Call next patient</button></div>`;
}
function render() {
  const s = state.stats;
  renderAssessments();
  for (const b of document.querySelectorAll('[data-register]')) b.disabled = !connection;
  $('#stats').innerHTML = statCard('Patients waiting', s.waiting, 'Currently in the queue', 'users') + statCard('Critical patients', s.critical, 'Severity 1 · Waiting', 'heart') + statCard('Urgent patients', s.urgent, 'Severity 2 · Waiting', 'clock') + statCard('Completed visits', s.completed, 'Across saved visit history', 'check');
  $('#nav-patients').textContent = s.patients; $('#nav-queue').textContent = s.waiting; $('#queue-count').textContent = s.waiting;
  $('#dashboard-queue').innerHTML = queueTable(state.queue.slice(0,5), true);
  $('#live-queue').innerHTML = queueTable(state.queue);
  $('#dashboard-active').innerHTML = $('#queue-active').innerHTML = activeRoom();
  $('#dashboard-history').innerHTML = `<div class="table-wrap">${historyTable('', true, 4)}</div>`;
  $('#patients-table').innerHTML = patientTable(searchResults === null ? state.patients : searchResults);
  $('#search-note').textContent = searchResults === null ? `${s.patients} registered patients` : `${searchResults.length} exact matches · C ${$('#search-kind').value === 'find_id' ? 'hash-table' : 'BST'} lookup`;
  const selected = $('#history-patient').value;
  $('#history-patient').innerHTML = '<option value="">All patients</option>' + state.patients.map(p => `<option value="${esc(p.id)}">${esc(p.name)} · ID ${esc(p.id)}</option>`).join('');
  $('#history-patient').value = selected;
  $('#history-table').innerHTML = historyTable($('#history-patient').value, $('#history-order').value === 'newest');
  $('#report-table').innerHTML = reportRows === null ? empty('Your report is ready to generate', 'Choose the sort order and C algorithm above.', 'chart') : patientTable(reportRows, true);
  $('#report-note').textContent = reportDescription || 'Choose an algorithm and generate a report. Reports reset after a change to avoid showing stale records.';
  $('#download-report').disabled = reportRows === null;
  $('#report-stats').innerHTML = statCard('Registered patients', s.patients, 'Unique generated IDs', 'users') + statCard('Recorded visits', s.visits, 'Completed + no-show', 'clock') + statCard('No-shows', s.no_show, 'Operator-recorded outcomes', 'list') + statCard('Consulting now', state.active ? 1 : 0, 'Single-clinician workflow', 'heart');
  $('#storage-details').innerHTML = `<div><dt>Database</dt><dd>${esc(persistence.file || '—')}</dd></div><div><dt>Workspace</dt><dd>${persistence.demo ? 'Fictional demo' : 'Local records'}</dd></div><div><dt>Persistence</dt><dd>Autosave on every successful change</dd></div><div><dt>Last saved</dt><dd>${dateTime(persistence.saved_at)}</dd></div><div><dt>Undo</dt><dd>${state.can_undo ? 'Eligible check-in available' : 'No eligible check-in'}</dd></div>`;
  for (const b of document.querySelectorAll('[data-action="undo"]')) b.disabled = !state.can_undo;
}
function navigate() {
  page = location.hash.slice(1);
  if (!pages[page]) page = 'dashboard';
  const [short,title,description] = pages[page];
  $('#breadcrumb').textContent = short; $('#page-title').textContent = title; $('#page-description').textContent = description;
  for (const element of document.querySelectorAll('.page')) element.hidden = element.id !== `page-${page}`;
  for (const a of document.querySelectorAll('nav a')) {
    const active = a.dataset.page === page; a.classList.toggle('active', active);
    if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  document.title = `${short} — Smart Clinic`;
}
function confirm(title, description, action, id = undefined) {
  $('#confirm-title').textContent = title; $('#confirm-description').textContent = description;
  confirmAction = {action, ...(id ? {id} : {})}; $('#confirm-dialog').showModal();
}
function showHistory(id) {
  const p = state.patients.find(p => p.id === id);
  if (!p) return;
  $('#visit-title').textContent = p.name;
  $('#visit-content').innerHTML = `<div class="visit-summary">ID ${esc(p.id)} · ${p.age} years · ${severity(p)} ${status(p)}</div><div class="table-wrap">${historyTable(id)}</div>`;
  $('#visit-dialog').showModal();
}
document.addEventListener('click', async e => {
  const button = e.target.closest('button'); if (!button || pending) return;
  if (button.hasAttribute('data-close')) { button.closest('dialog').close(); return; }
  if (button.dataset.go) { location.hash = button.dataset.go; return; }
  if (button.hasAttribute('data-register') && state) {
    $('#registration-form').reset(); $('#new-id').value = `Next available: ${state.next_id}`;
    $('#registration-error').textContent = ''; $('#registration-dialog').showModal(); $('#new-name').focus(); return;
  }
  if (button.dataset.reviewAssessment) { openAssessment(button.dataset.reviewAssessment); return; }
  if (button.dataset.invite) {
    const result=await request({action:'invite_patient',id:button.dataset.invite});
    if(result) { $('#invitation-person').textContent=`${result.invitation.name} · ID ${result.invitation.patient_id}`; $('#invitation-code').textContent=result.invitation.code; $('#invitation-link').href='/patient#'+new URLSearchParams({id:result.invitation.patient_id,code:result.invitation.code}); $('#invitation-dialog').showModal(); }
    return;
  }
  if (button.dataset.history) { showHistory(button.dataset.history); return; }
  if (button.dataset.checkin) {
    checkinID = button.dataset.checkin; const p = state.patients.find(p => p.id === checkinID);
    $('#checkin-name').textContent = `${p.name} · ID ${p.id} · Previous severity ${p.severity}`;
    $('#checkin-form').reset(); $('#checkin-error').textContent = ''; $('#checkin-dialog').showModal(); return;
  }
  if (button.dataset.noShow) { confirm('Mark patient as no-show?', 'This removes the patient from the waiting queue and permanently records a missed visit.', 'no_show', button.dataset.noShow); return; }
  const action = button.dataset.action;
  if (action === 'next') confirm('Start the next consultation?', 'The first patient in C-calculated service order will be called. Other patients remain waiting.', 'next');
  if (action === 'complete') confirm('Complete this consultation?', 'A completed visit will be added to this patient’s history. This action cannot be undone.', 'complete');
  if (action === 'undo') confirm('Undo the latest eligible check-in?', 'The most recent check-in that is still waiting will be removed. Registration is kept. Completed visits are unaffected.', 'undo');
  if (action === 'load') confirm('Reload the saved snapshot?', 'Current autosaved records will be reloaded from disk. Session undo history will reset. A corrupt snapshot will leave your current data unchanged.', 'load');
  if (action === 'save') await request({action:'save'});
});
$('#confirm-action').addEventListener('click', async () => {
  if (pending || !confirmAction) return;
  const data = await request(confirmAction);
  if (data) $('#confirm-dialog').close();
});
$('#registration-form').addEventListener('submit', async e => {
  e.preventDefault(); if (pending) return;
  const value = new FormData(e.target), chosen = value.get('severity');
  const name = value.get('name');
  if (new TextEncoder().encode(name).length > 79) { $('#registration-error').textContent = 'Name must be at most 79 UTF-8 bytes.'; return; }
  if (!chosen) { $('#registration-error').textContent = 'Choose a staff-assigned severity from 1–4.'; return; }
  const data = await request({action:$('#add-to-queue').checked ? 'register_checkin' : 'register', name, age:Number(value.get('age')), severity:Number(chosen)});
  if (data) $('#registration-dialog').close(); else $('#registration-error').textContent = $('#error-text').textContent;
});
$('#checkin-form').addEventListener('submit', async e => {
  e.preventDefault();
  const data = await request({action:'checkin',id:checkinID,severity:Number($('#checkin-severity').value)});
  if (data) $('#checkin-dialog').close(); else $('#checkin-error').textContent = $('#error-text').textContent;
});
$('#search-form').addEventListener('submit', async e => {
  e.preventDefault(); const kind = $('#search-kind').value;
  await request({action:kind,[kind === 'find_id' ? 'id':'name']:$('#search-term').value}, true);
});
$('#clear-search').addEventListener('click', () => { searchResults = null; $('#search-form').reset(); render(); });
$('#search-kind').addEventListener('change', () => { $('#search-term').placeholder = $('#search-kind').value === 'find_id' ? 'Enter a patient ID' : 'Exact name (case-sensitive)'; searchResults = null; if (state) render(); });
for (const id of ['#history-patient','#history-order']) $(id).addEventListener('change', () => { if (state) render(); });
$('#report-form').addEventListener('submit', async e => { e.preventDefault(); await request({action:'report',key:Number($('#report-key').value),algorithm:Number($('#report-algorithm').value)}); });
$('#download-report').addEventListener('click', () => {
  if (!reportRows) return;
  // Prefix spreadsheet formulas to keep names inert in spreadsheet applications.
  const cell = value => { let s = String(value ?? ''); if (/^[=+@\-\t\r\n]/.test(s)) s = `'${s}`; return `"${s.replace(/"/g,'""')}"`; };
  const rows = [['ID','Name','Age','Severity','Status','Estimated wait (minutes)'], ...reportRows.map(p => [p.id,p.name,p.age,p.severity,p.status,p.wait])];
  const url = URL.createObjectURL(new Blob(['\uFEFF'+rows.map(r => r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
  const a = document.createElement('a'); a.href = url; a.download = 'clinic-report.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('#dismiss-error').addEventListener('click', () => { $('#error-banner').hidden = true; });
window.addEventListener('hashchange', navigate);
async function initialize() {
  $('#date-label').textContent = new Date().toLocaleDateString([], {weekday:'long',day:'numeric',month:'long',year:'numeric'}).toUpperCase();
  navigate();
  $('#dashboard-queue').innerHTML = empty('Connecting to your clinic…', 'Loading records from the local C engine.', 'clock');
  try {
    const response = await fetch('/api/session'); if (!response.ok) throw new Error('Local session could not be opened.');
    const session = await response.json(); token = session.token;
    symptomCatalog=await(await fetch('/api/catalog')).json();
    $('#demo-banner').hidden = !session.demo;
    publicToken=token; token=''; $('#staff-login').showModal();
    setInterval(() => { if (token && !pending && !document.hidden) request(null,true); }, 5000);
  } catch (e) { setConnection(false); error(e.message); }
}
initialize();

$('#staff-login').addEventListener('cancel',e=>e.preventDefault());
$('#staff-login-form').addEventListener('submit',async e=>{
  e.preventDefault(); const button=e.target.querySelector('button');button.disabled=true;
  try {
    const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json','X-Clinic-Token':publicToken},body:JSON.stringify({pin:$('#staff-pin').value})});
    const data=await response.json();if(!response.ok)throw new Error(data.message);
    token=data.token;$('#staff-pin').value='';$('#staff-login-error').textContent='';$('#staff-login').close();await request();
  }catch(e){$('#staff-login-error').textContent=e.message;}finally{button.disabled=false;}
});
$('#staff-logout').addEventListener('click',()=>location.reload());
function renderAssessments() {
  const pending=assessments.filter(a=>a.status!=='reviewed'),emergency=pending.filter(a=>a.evaluation.emergency&&state.queue.some(p=>p.id===a.patient_id));
  $('#nav-assessments').textContent=pending.length;
  $('#assessment-overview').textContent=`${pending.length} available for optional review · ${emergency.length} with emergency warning flags`;
  $('#assessment-alert').hidden=!emergency.length;
  $('#assessment-alert').textContent=`Emergency warning reported by ${emergency.length} patient(s). Alert clinic staff immediately and direct them to emergency assistance. Open the patient assessment inbox now.`;
  $('#assessment-inbox').innerHTML=assessments.length?[...assessments].reverse().map(a=>`<article class="assessment-item ${a.evaluation.emergency?'assessment-emergency':''}"><h3>${esc(a.patient_name)} · ID ${esc(a.patient_id)}</h3><p>${esc(a.reference)} · ${dateTime(a.submitted_at)} · ${esc(a.status)}</p><p><strong>Demonstration suggestion: ${esc(a.evaluation.label)}</strong> · ${a.evaluation.emergency?'EMERGENCY WARNING — alert staff':''}</p><p>${esc(a.evaluation.explanation)}</p>${a.review?`<p>Staff-confirmed: ${a.review.priority} · ${severityNames[a.review.priority]} · ${esc(a.review.reviewer)} · ${esc(a.review.override_reason||'Confirmed suggestion')}</p>`:''}<div class="button-row"><button class="${a.status==='pending'?'primary':'secondary'}" data-review-assessment="${esc(a.reference)}">${a.status==='pending'?'Review & confirm priority':'View / override priority'}</button></div></article>`).join(''):empty('No patient assessments yet','Patients complete their checklist at the separate patient page.','heart');
}
function openAssessment(reference) {
  const a=assessments.find(a=>a.reference===reference);if(!a)return;activeAssessment=a;$('#assessment-review-form').reset();$('#review-error').textContent='';
  const rows=[['Patient',`${a.patient_name} · ID ${a.patient_id} · age ${a.patient_age}`],['Assessment',a.reference],['Selected symptoms',a.answers.symptoms.map(id=>symptomCatalog.symptoms.find(s=>s.id===id)?.label||id).join(', ')||'Unanswered'],['Other listed symptoms absent',a.answers.other_listed_absent===true?'Explicitly confirmed':'Not confirmed'],['Duration',a.answers.duration?`${a.answers.duration.value??'Unanswered'} ${a.answers.duration.unit??'(unit unanswered)'}`:'Unknown'],['Self-reported severity',a.answers.self_severity||'Unknown'],['Additional symptoms',a.answers.additional||'No text entered'],...symptomCatalog.warnings.map(w=>[w.label,a.answers.warnings[w.id]||'Unanswered']),...symptomCatalog.symptoms.filter(s=>a.answers.symptoms.includes(s.id)).flatMap(s=>s.followups.map(f=>[s.label+': '+f.label,a.answers.followups[s.id+'.'+f.id]||'Unanswered']))];
  $('#assessment-review-details').innerHTML=`${a.evaluation.emergency?`<div class="emergency-warning"><strong>Emergency warning reported</strong>${esc(a.evaluation.emergency_instruction)}<ul>${a.evaluation.warning_flags.map(f=>`<li>${esc(f)}</li>`).join('')}</ul></div>`:''}<dl class="review-list">${rows.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl><div class="suggestion-box"><strong>Demonstration only: ${esc(a.evaluation.label)}</strong><p>${esc(a.evaluation.explanation)}</p><h3>How priority was calculated</h3><p>Uncertainty: ${esc((a.evaluation.uncertainty_flags||[]).join(' ')||'Unvalidated demonstration rules')}</p><p>Rule(s): ${esc(a.evaluation.rule_ids.join(', ')||'Priority (3) fallback')} · dataset ${esc(a.evaluation.dataset_version)}</p><p>${esc(a.evaluation.sources.join(' / '))}</p><p>Not clinically validated. Automatic preliminary priority is already used by the C queue. Authorized staff can override a waiting patient; original arrival order is preserved.</p></div>`;
  const patient=state.patients.find(p=>p.id===a.patient_id);
  for(const el of $('#assessment-review-form').querySelectorAll('input,select,textarea,button[type=submit]'))el.disabled=a.status!=='pending'&&patient?.status!=='Waiting';
  if(a.review){$('#review-priority').value=String(a.review.priority);$('#reviewer-name').value=a.review.reviewer;$('#override-reason').value=a.review.override_reason;$('#staff-confirmed').checked=true;}
  $('#assessment-review-dialog').showModal();
}
$('#assessment-review-form').addEventListener('submit',async e=>{
  e.preventDefault();if(!activeAssessment||!$('#staff-confirmed').checked)return;
  const result=await request({action:'review_assessment',reference:activeAssessment.reference,patient_id:activeAssessment.patient_id,priority:Number($('#review-priority').value),reviewer:$('#reviewer-name').value,override_reason:$('#override-reason').value});
  if(result)$('#assessment-review-dialog').close();else $('#review-error').textContent=$('#error-text').textContent;
});
