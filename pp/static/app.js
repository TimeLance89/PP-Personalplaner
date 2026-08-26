const state = { me: null, csrf: '', dashboard: null, workers: [], departments: [], agencies: [], fields: [], reasons: [], offboardings: [], users: [] };
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const esc = (v='') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function toast(message, error=false) {
  const el = $('#toast'); el.textContent = message; el.className = `toast${error ? ' error' : ''}`; el.hidden = false;
  clearTimeout(window.__toast); window.__toast = setTimeout(() => el.hidden = true, 3600);
}

async function api(path, options={}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  if (state.csrf && options.method && options.method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  const res = await fetch(path, { ...options, headers });
  let data = null; try { data = await res.json(); } catch { data = null; }
  if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
  return data;
}

function fmtDate(value) {
  if (!value) return '—';
  const d = new Date(`${String(value).slice(0,10)}T12:00:00`);
  return Number.isNaN(d.getTime()) ? value : new Intl.DateTimeFormat('de-DE').format(d);
}
function statusChip(status) {
  const map = { sent:['Versendet','success'], mail_failed:['Mail fehlgeschlagen','danger'], pending:['Ausstehend','warning'], cancelled:['Storniert',''], active:['Aktiv','success'], inactive:['Inaktiv','warning'] };
  const [label, cls] = map[status] || [status,'']; return `<span class="chip ${cls}">${esc(label)}</span>`;
}
function closeModal(){ $('#modal').close(); }
function openModal(html){ $('#modalBody').innerHTML = html; $('#modal').showModal(); }

async function boot() {
  const setup = await api('/api/setup/status');
  if (setup.required) { $('#loginForm').hidden = true; $('#setupForm').hidden = false; return; }
  try { await loadMe(); showApp(); await loadAll(); renderCurrent(); }
  catch { $('#authShell').hidden = false; $('#appShell').hidden = true; }
}

async function loadMe() {
  state.me = await api('/api/me'); state.csrf = state.me.csrf_token;
}
function showApp() {
  $('#authShell').hidden = true; $('#appShell').hidden = false;
  $$('[data-admin-only]').forEach(el => el.hidden = state.me.role !== 'admin');
  $('#userBadge').innerHTML = `<strong>${esc(state.me.display_name)}</strong><br><span>${state.me.role === 'admin' ? 'Administrator' : esc(state.me.department?.name || 'Keine Abteilung')}</span>`;
  $('#contextBadge').textContent = state.me.role === 'admin' ? 'Gesamtübersicht' : (state.me.department?.name || 'Keine Abteilung');
}
async function loadAll() {
  const tasks = [api('/api/dashboard'), api('/api/workers'), api('/api/departments'), api('/api/agencies'), api('/api/custom-fields'), api('/api/offboarding-reasons'), api('/api/offboardings')];
  if (state.me.role === 'admin') tasks.push(api('/api/users'));
  const data = await Promise.all(tasks);
  [state.dashboard,state.workers,state.departments,state.agencies,state.fields,state.reasons,state.offboardings] = data;
  if (state.me.role === 'admin') state.users = data[7];
}

let currentView = 'dashboard';
function setView(view) {
  currentView = view;
  $$('.view').forEach(v => v.hidden = true); $(`#view-${view}`).hidden = false;
  $$('#mainNav button').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  const titles = {dashboard:'Übersicht',workers:state.me.role==='admin'?'Personal':'Mein Personal',offboardings:'Abmeldungen',admin:'Verwaltung',audit:'Aktivitäten'};
  $('#viewTitle').textContent = titles[view] || 'Personalplaner'; renderCurrent();
}
function renderCurrent() {
  if (currentView==='dashboard') renderDashboard();
  if (currentView==='workers') renderWorkers();
  if (currentView==='offboardings') renderOffboardings();
  if (currentView==='admin') renderAdmin();
  if (currentView==='audit') renderAudit();
}

function renderDashboard() {
  const d=state.dashboard, c=d.counts;
  $('#view-dashboard').innerHTML = `
    <div class="grid cards">
      <div class="card stat"><div class="value">${c.workers}</div><div class="label">Aktuell zugeteilt</div></div>
      <div class="card stat"><div class="value">${c.offboardings}</div><div class="label">Abmeldungen im Verlauf</div></div>
      <div class="card stat"><div class="value">${c.departments}</div><div class="label">${state.me.role==='admin'?'Aktive Abteilungen':'Eigene Abteilung'}</div></div>
      <div class="card stat"><div class="value">${state.me.role==='admin'?c.unassigned:(d.smtp_configured?'✓':'!')}</div><div class="label">${state.me.role==='admin'?'Nicht zugeteilt':(d.smtp_configured?'Mailversand bereit':'Mailversand fehlt')}</div></div>
    </div>
    <div class="section-head"><h2>${state.me.role==='admin'?'Aktuell eingesetztes Personal':'Mein aktuelles Personal'}</h2><button class="secondary" onclick="setView('workers')">Alle anzeigen</button></div>
    ${workerTable(d.workers.slice(0,10))}
  `;
}

function workerTable(rows) {
  if (!rows.length) return `<div class="card empty">Noch kein Personal zugeteilt.</div>`;
  return `<div class="table-wrap"><table><thead><tr><th>Mitarbeiter</th><th>Firma</th><th>Abteilung</th><th>Seit</th><th>Status</th><th></th></tr></thead><tbody>
    ${rows.map(w => {
      const workerId = w.worker_id || w.id;
      const off = w.offboarding;
      return `<tr><td class="name-cell"><strong>${esc(w.first_name)} ${esc(w.last_name)}</strong><small>${esc(w.employee_code || 'ohne Kennnummer')}</small></td>
      <td>${esc(w.agency_name)}</td><td>${esc(w.department_name || 'Nicht zugeteilt')}</td><td>${fmtDate(w.assigned_from || w.start_date)}</td>
      <td>${off ? `<span class="chip warning">Abmeldung ${fmtDate(off.effective_at)}</span>` : statusChip(w.worker_status || w.status || 'active')}</td>
      <td><div class="inline-actions">${w.department_name ? `<button class="danger" onclick="openOffboarding(${workerId})">Abmelden</button>` : ''}${state.me.role==='admin'?`${!w.department_name?`<button class="primary" onclick="openAssign(${workerId})">Zuteilen</button>`:''}<button class="secondary" onclick="openWorkerEdit(${workerId})">Bearbeiten</button>`:''}</div></td></tr>`;
    }).join('')}
  </tbody></table></div>`;
}

function renderWorkers() {
  $('#view-workers').innerHTML = `
    <div class="section-head"><div><h2>${state.me.role==='admin'?'Zeitarbeiter':'Personal meiner Abteilung'}</h2><p class="muted">${state.me.role==='admin'?'Stammdaten und aktuelle Zuteilung':'Nur aktuell Ihrer Abteilung zugeteilte Personen werden angezeigt.'}</p></div>
    ${state.me.role==='admin'?'<button class="primary" onclick="openWorkerCreate()">+ Zeitarbeiter</button>':''}</div>
    ${workerTable(state.workers)}
  `;
}

function offboardingTable(rows) {
  if (!rows.length) return `<div class="card empty">Noch keine Abmeldungen vorhanden.</div>`;
  return `<div class="table-wrap"><table><thead><tr><th>Mitarbeiter</th><th>Abteilung</th><th>Wirksam</th><th>Grund</th><th>Ersatz</th><th>Mail</th><th></th></tr></thead><tbody>${rows.map(o=>`<tr>
    <td class="name-cell"><strong>${esc(o.first_name || `#${o.worker_id}`)} ${esc(o.last_name || '')}</strong><small>${esc(o.agency_name || '')}</small></td>
    <td>${esc(o.department_name || '')}</td><td>${fmtDate(o.effective_at)}</td><td>${esc(o.reason_label || o.reason_text || '—')}</td>
    <td>${o.replacement_required?'Ja':'Nein'}</td><td>${statusChip(o.status)}</td><td>${o.status==='mail_failed'?`<button class="secondary" onclick="retryOffboarding(${o.id})">Erneut senden</button>`:''}</td>
  </tr>`).join('')}</tbody></table></div>`;
}
function renderOffboardings(){ $('#view-offboardings').innerHTML=`<div class="section-head"><div><h2>Abmeldungen</h2><p class="muted">Historie inklusive Mailstatus und Ersatzwunsch.</p></div></div>${offboardingTable(state.offboardings)}`; }

let adminTab='departments';
function setAdminTab(k){ adminTab=k; renderAdmin(); }
function openAssign(workerId){
  const w=state.workers.find(x=>Number(x.id)===Number(workerId)); if(!w)return;
  openModal(`<h2>Personal zuteilen</h2><p class="muted">${esc(w.first_name)} ${esc(w.last_name)}</p><form id="assignForm" class="form-grid"><label>Abteilung<select name="department_id" required><option value="">Bitte wählen</option>${state.departments.filter(d=>d.active).map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></label><label>Ab<input type="date" name="assigned_from" value="${new Date().toISOString().slice(0,10)}" required></label><label class="full">Hinweis<textarea name="notes"></textarea></label><div class="form-actions full"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Zuteilen</button></div></form>`);
  $('#assignForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;try{await api('/api/assignments',{method:'POST',body:JSON.stringify({worker_id:workerId,department_id:Number(f.department_id.value),assigned_from:f.assigned_from.value,assigned_until:null,notes:f.notes.value})});closeModal();await refresh();toast('Personal wurde zugeteilt.')}catch(err){toast(err.message,true)}};
}
function renderAdmin(){
  if(state.me.role!=='admin') return;
  const tabs=[['departments','Abteilungen'],['agencies','Zeitarbeitsfirmen'],['users','Bereichsleiter'],['fields','Zusatzfelder'],['reasons','Abmeldegründe']];
  $('#view-admin').innerHTML=`<div class="tabs">${tabs.map(([k,l])=>`<button class="${adminTab===k?'active':''}" onclick="setAdminTab('${k}')">${l}</button>`).join('')}</div><div id="adminPane"></div>`;
  const pane=$('#adminPane');
  if(adminTab==='departments') pane.innerHTML=adminDepartments();
  if(adminTab==='agencies') pane.innerHTML=adminAgencies();
  if(adminTab==='users') pane.innerHTML=adminUsers();
  if(adminTab==='fields') pane.innerHTML=adminFields();
  if(adminTab==='reasons') pane.innerHTML=adminReasons();
}
function adminDepartments(){return `<div class="section-head"><h2>Abteilungen</h2><button class="primary" onclick="openDepartmentCreate()">+ Abteilung</button></div><div class="table-wrap"><table><thead><tr><th>Name</th><th>Kürzel</th><th>Status</th></tr></thead><tbody>${state.departments.map(d=>`<tr><td>${esc(d.name)}</td><td>${esc(d.code)}</td><td>${d.active?statusChip('active'):statusChip('inactive')}</td></tr>`).join('')}</tbody></table></div>`;}
function adminAgencies(){return `<div class="section-head"><h2>Zeitarbeitsfirmen</h2><button class="primary" onclick="openAgencyCreate()">+ Firma</button></div><div class="table-wrap"><table><thead><tr><th>Firma</th><th>Ansprechpartner</th><th>E-Mail</th><th>Telefon</th></tr></thead><tbody>${state.agencies.map(a=>`<tr><td>${esc(a.name)}</td><td>${esc(a.contact_name)}</td><td>${esc(a.email)}</td><td>${esc(a.phone)}</td></tr>`).join('')}</tbody></table></div>`;}
function adminUsers(){return `<div class="section-head"><h2>Benutzer</h2><button class="primary" onclick="openUserCreate()">+ Zugang</button></div><div class="table-wrap"><table><thead><tr><th>Name</th><th>Benutzer</th><th>Rolle</th><th>Abteilung</th><th>Status</th></tr></thead><tbody>${state.users.map(u=>`<tr><td>${esc(u.display_name)}</td><td>${esc(u.username)}</td><td>${u.role==='admin'?'Administrator':'Bereichsleiter'}</td><td>${esc(u.department_name||'—')}</td><td>${u.active?statusChip('active'):statusChip('inactive')}</td></tr>`).join('')}</tbody></table></div>`;}
function adminFields(){return `<div class="section-head"><div><h2>Zusatzfelder</h2><p class="muted">Eigene Felder für Personal- oder Abteilungsstammdaten.</p></div><button class="primary" onclick="openFieldCreate()">+ Feld</button></div><div class="table-wrap"><table><thead><tr><th>Bereich</th><th>Feld</th><th>Typ</th><th>Pflicht</th><th>Status</th></tr></thead><tbody>${state.fields.map(f=>`<tr><td>${f.entity_type==='worker'?'Personal':'Abteilung'}</td><td>${esc(f.label)}<br><small class="muted">${esc(f.field_key)}</small></td><td>${esc(f.field_type)}</td><td>${f.required?'Ja':'Nein'}</td><td>${f.active?statusChip('active'):statusChip('inactive')}</td></tr>`).join('')}</tbody></table></div>`;}
function adminReasons(){return `<div class="section-head"><h2>Abmeldegründe</h2><button class="primary" onclick="openReasonCreate()">+ Grund</button></div><div class="table-wrap"><table><thead><tr><th>Grund</th><th>Reihenfolge</th><th>Status</th></tr></thead><tbody>${state.reasons.map(r=>`<tr><td>${esc(r.label)}</td><td>${r.sort_order}</td><td>${r.active?statusChip('active'):statusChip('inactive')}</td></tr>`).join('')}</tbody></table></div>`;}

async function renderAudit(){
  if(state.me.role!=='admin') return;
  const rows=await api('/api/audit');
  $('#view-audit').innerHTML=`<div class="section-head"><div><h2>Aktivitätsprotokoll</h2><p class="muted">Die letzten 300 sicherheits- und personalrelevanten Aktionen.</p></div></div><div class="card">${rows.map(a=>`<div class="audit-row"><strong>${esc(a.action)}</strong> · ${esc(a.entity_type)} ${a.entity_id||''}<br><small>${esc(a.user_name||'System')} · ${esc(a.created_at)}</small></div>`).join('') || '<div class="empty">Noch keine Aktivitäten.</div>'}</div>`;
}

function workerCustomFields(current={}) {
  return state.fields.filter(f=>f.entity_type==='worker'&&f.active).map(f=>{
    const name=`custom_${f.field_key}`, val=current[f.field_key]??'';
    if(f.field_type==='boolean') return `<label>${esc(f.label)}<select name="${name}"><option value="false" ${!val?'selected':''}>Nein</option><option value="true" ${val?'selected':''}>Ja</option></select></label>`;
    if(f.field_type==='select') return `<label>${esc(f.label)}<select name="${name}" ${f.required?'required':''}><option value="">Bitte wählen</option>${(f.options||[]).map(o=>`<option ${String(o)===String(val)?'selected':''}>${esc(o)}</option>`).join('')}</select></label>`;
    const type=f.field_type==='number'?'number':f.field_type==='date'?'date':'text'; return `<label>${esc(f.label)}<input type="${type}" name="${name}" value="${esc(val)}" ${f.required?'required':''}></label>`;
  }).join('');
}
function collectCustom(form, entity='worker') {
  const out={}; state.fields.filter(f=>f.entity_type===entity&&f.active).forEach(f=>{ const el=form.elements[`custom_${f.field_key}`]; if(!el)return; let v=el.value; if(f.field_type==='boolean')v=v==='true'; out[f.field_key]=v; }); return out;
}

function openWorkerCreate(){
  openModal(`<h2>Zeitarbeiter anlegen</h2><form id="workerForm" class="form-grid">
    <label>Vorname<input name="first_name" required></label><label>Nachname<input name="last_name" required></label>
    <label>Kennnummer<input name="employee_code"></label><label>Zeitarbeitsfirma<select name="agency_id" required><option value="">Bitte wählen</option>${state.agencies.filter(a=>a.active).map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></label>
    <label>Startdatum<input type="date" name="start_date"></label><label>Abteilung<select name="department_id"><option value="">Noch nicht zuteilen</option>${state.departments.filter(d=>d.active).map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></label>
    ${workerCustomFields()}<label class="full">Notizen<textarea name="notes"></textarea></label>
    <div class="form-actions full"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Speichern</button></div>
  </form>`);
  $('#workerForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;try{const worker=await api('/api/workers',{method:'POST',body:JSON.stringify({first_name:f.first_name.value,last_name:f.last_name.value,employee_code:f.employee_code.value,agency_id:Number(f.agency_id.value),start_date:f.start_date.value||null,notes:f.notes.value,status:'active',custom_data:collectCustom(f)})});if(f.department_id.value)await api('/api/assignments',{method:'POST',body:JSON.stringify({worker_id:worker.id,department_id:Number(f.department_id.value),assigned_from:f.start_date.value||null,notes:''})});closeModal();await refresh();toast('Zeitarbeiter wurde angelegt.');}catch(err){toast(err.message,true)}};
}
function openWorkerEdit(id){
  const w=state.workers.find(x=>Number(x.id)===Number(id)); if(!w)return;
  openModal(`<h2>${esc(w.first_name)} ${esc(w.last_name)}</h2><form id="workerEditForm" class="form-grid">
    <label>Vorname<input name="first_name" value="${esc(w.first_name)}" required></label><label>Nachname<input name="last_name" value="${esc(w.last_name)}" required></label>
    <label>Kennnummer<input name="employee_code" value="${esc(w.employee_code)}"></label><label>Firma<select name="agency_id">${state.agencies.map(a=>`<option value="${a.id}" ${Number(a.id)===Number(w.agency_id)?'selected':''}>${esc(a.name)}</option>`).join('')}</select></label>
    <label>Startdatum<input type="date" name="start_date" value="${esc(w.start_date||'')}"></label><label>Status<select name="status"><option value="active" ${w.status==='active'?'selected':''}>Aktiv</option><option value="inactive" ${w.status==='inactive'?'selected':''}>Inaktiv</option><option value="archived" ${w.status==='archived'?'selected':''}>Archiviert</option></select></label>
    ${workerCustomFields(w.custom_data||{})}<label class="full">Notizen<textarea name="notes">${esc(w.notes||'')}</textarea></label>
    <div class="form-actions full"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Speichern</button></div></form>`);
  $('#workerEditForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;try{await api(`/api/workers/${id}`,{method:'PATCH',body:JSON.stringify({first_name:f.first_name.value,last_name:f.last_name.value,employee_code:f.employee_code.value,agency_id:Number(f.agency_id.value),start_date:f.start_date.value||null,notes:f.notes.value,status:f.status.value,custom_data:collectCustom(f)})});closeModal();await refresh();toast('Änderungen gespeichert.');}catch(err){toast(err.message,true)}};
}

function openOffboarding(workerId){
  const w=(state.dashboard?.workers||[]).find(x=>Number(x.worker_id||x.id)===Number(workerId)) || state.workers.find(x=>Number(x.id)===Number(workerId));
  openModal(`<h2>Zeitarbeiter abmelden</h2><p class="muted">${esc(w?.first_name||'')} ${esc(w?.last_name||'')} · ${esc(w?.department_name||state.me.department?.name||'')}</p>
    <form id="offForm" class="form-grid"><label>Wirksam zum<input type="date" name="effective_at" min="${new Date().toISOString().slice(0,10)}" required></label>
    <label>Grund<select name="reason_id" required><option value="">Bitte wählen</option>${state.reasons.map(r=>`<option value="${r.id}">${esc(r.label)}</option>`).join('')}</select></label>
    <label class="full">Erläuterung<textarea name="reason_text" placeholder="Optional genauer beschreiben"></textarea></label>
    <label>Ersatz benötigt?<select name="replacement_required"><option value="false">Nein</option><option value="true">Ja</option></select></label>
    <label>Hinweis zum Ersatz<input name="replacement_notes" placeholder="z. B. gleiche Schicht / Qualifikation"></label>
    <div class="form-actions full"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary" type="submit">E-Mail prüfen</button></div></form>`);
  $('#offForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;const payload={worker_id:workerId,effective_at:f.effective_at.value,reason_id:Number(f.reason_id.value),reason_text:f.reason_text.value,replacement_required:f.replacement_required.value==='true',replacement_notes:f.replacement_notes.value};try{const preview=await api('/api/offboardings/preview',{method:'POST',body:JSON.stringify(payload)});openModal(`<h2>Abmeldung bestätigen</h2><p><strong>${esc(preview.subject)}</strong></p><div class="mail-preview">${esc(preview.body)}</div><div class="form-actions"><button class="ghost" type="button" onclick="closeModal()">Abbrechen</button><button class="danger" id="confirmOff">Abmelden & senden</button></div>`);$('#confirmOff').onclick=async()=>{try{const result=await api('/api/offboardings',{method:'POST',body:JSON.stringify(payload)});closeModal();await refresh();toast(result.status==='sent'?'Abmeldung wurde versendet.':'Abmeldung gespeichert, aber E-Mailversand ist fehlgeschlagen.',result.status!=='sent');}catch(err){toast(err.message,true)}};}catch(err){toast(err.message,true)}};
}
async function retryOffboarding(id){try{await api(`/api/offboardings/${id}/retry`,{method:'POST'});await refresh();toast('E-Mail wurde versendet.')}catch(err){toast(err.message,true)}}

function openDepartmentCreate(){
  openModal(`<h2>Abteilung anlegen</h2><form id="depForm" class="form-grid"><label>Name<input name="name" required></label><label>Kürzel<input name="code"></label><div class="form-actions full"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Anlegen</button></div></form>`);
  $('#depForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;try{await api('/api/departments',{method:'POST',body:JSON.stringify({name:f.name.value,code:f.code.value,active:true,custom_data:{}})});closeModal();await refresh();renderAdmin();toast('Abteilung angelegt.')}catch(err){toast(err.message,true)}};
}
function openAgencyCreate(){
  openModal(`<h2>Zeitarbeitsfirma anlegen</h2><form id="agencyForm" class="form-grid"><label>Firmenname<input name="name" required></label><label>Ansprechpartner<input name="contact_name"></label><label>E-Mail<input type="email" name="email"></label><label>Telefon<input name="phone"></label><div class="form-actions full"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Anlegen</button></div></form>`);
  $('#agencyForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;try{await api('/api/agencies',{method:'POST',body:JSON.stringify({name:f.name.value,contact_name:f.contact_name.value,email:f.email.value,phone:f.phone.value,active:true})});closeModal();await refresh();renderAdmin();toast('Zeitarbeitsfirma angelegt.')}catch(err){toast(err.message,true)}};
}
function openUserCreate(){
  openModal(`<h2>Zugang anlegen</h2><form id="userForm" class="form-grid"><label>Name<input name="display_name" required></label><label>Benutzername<input name="username" required></label><label>Passwort<input type="password" name="password" minlength="10" required></label><label>Rolle<select name="role"><option value="leader">Bereichsleiter</option><option value="admin">Administrator</option></select></label><label class="full">Abteilung<select name="department_id"><option value="">Bitte wählen</option>${state.departments.filter(d=>d.active).map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></label><div class="form-actions full"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Anlegen</button></div></form>`);
  $('#userForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;try{await api('/api/users',{method:'POST',body:JSON.stringify({display_name:f.display_name.value,username:f.username.value,password:f.password.value,role:f.role.value,department_id:f.department_id.value?Number(f.department_id.value):null,active:true})});closeModal();await refresh();renderAdmin();toast('Zugang angelegt.')}catch(err){toast(err.message,true)}};
}
function openFieldCreate(){
  openModal(`<h2>Zusatzfeld anlegen</h2><form id="fieldForm" class="form-grid"><label>Bereich<select name="entity_type"><option value="worker">Personal</option><option value="department">Abteilung</option></select></label><label>Bezeichnung<input name="label" required></label><label>Feldschlüssel<input name="field_key" placeholder="z. B. schicht" pattern="[a-z][a-z0-9_]+" required></label><label>Typ<select name="field_type"><option value="text">Text</option><option value="number">Zahl</option><option value="date">Datum</option><option value="boolean">Ja/Nein</option><option value="select">Auswahl</option></select></label><label class="full">Auswahlwerte (mit Komma trennen)<input name="options" placeholder="Früh, Spät, Nacht"></label><label>Pflichtfeld<select name="required"><option value="false">Nein</option><option value="true">Ja</option></select></label><label>Reihenfolge<input type="number" name="sort_order" value="100"></label><div class="form-actions full"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Anlegen</button></div></form>`);
  $('#fieldForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;try{await api('/api/custom-fields',{method:'POST',body:JSON.stringify({entity_type:f.entity_type.value,field_key:f.field_key.value,label:f.label.value,field_type:f.field_type.value,required:f.required.value==='true',options:f.options.value.split(',').map(x=>x.trim()).filter(Boolean),active:true,sort_order:Number(f.sort_order.value)})});closeModal();await refresh();renderAdmin();toast('Zusatzfeld angelegt.')}catch(err){toast(err.message,true)}};
}
function openReasonCreate(){
  openModal(`<h2>Abmeldegrund anlegen</h2><form id="reasonForm" class="form-grid"><label class="full">Bezeichnung<input name="label" required></label><label>Reihenfolge<input type="number" name="sort_order" value="100"></label><div class="form-actions full"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Anlegen</button></div></form>`);
  $('#reasonForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;try{await api('/api/offboarding-reasons',{method:'POST',body:JSON.stringify({label:f.label.value,active:true,sort_order:Number(f.sort_order.value)})});closeModal();await refresh();renderAdmin();toast('Abmeldegrund angelegt.')}catch(err){toast(err.message,true)}};
}

async function refresh(){ await loadAll(); renderCurrent(); }

$('#loginForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;try{const r=await api('/api/auth/login',{method:'POST',body:JSON.stringify({username:f.username.value,password:f.password.value})});state.csrf=r.csrf_token;await loadMe();showApp();await loadAll();setView('dashboard');}catch(err){toast(err.message,true)}};
$('#setupForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;try{await api('/api/setup',{method:'POST',body:JSON.stringify({token:f.token.value,display_name:f.display_name.value,username:f.username.value,password:f.password.value})});toast('Administrator angelegt. Bitte anmelden.');f.reset();$('#setupForm').hidden=true;$('#loginForm').hidden=false;}catch(err){toast(err.message,true)}};
$('#logoutBtn').onclick=async()=>{try{await api('/api/auth/logout',{method:'POST'});}catch{}location.reload();};
$$('#mainNav button').forEach(b=>b.onclick=()=>setView(b.dataset.view));
window.setView=setView; window.setAdminTab=setAdminTab; window.renderAdmin=renderAdmin; window.openWorkerCreate=openWorkerCreate; window.openAssign=openAssign; window.openWorkerEdit=openWorkerEdit; window.openOffboarding=openOffboarding; window.retryOffboarding=retryOffboarding; window.openDepartmentCreate=openDepartmentCreate; window.openAgencyCreate=openAgencyCreate; window.openUserCreate=openUserCreate; window.openFieldCreate=openFieldCreate; window.openReasonCreate=openReasonCreate; window.closeModal=closeModal;
boot().catch(err=>toast(err.message,true));
