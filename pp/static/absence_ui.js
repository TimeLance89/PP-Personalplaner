(() => {
  state.absences = [];
  state.absenceTypes = [];
  state.absenceReport = null;

  const absenceIcon = '<svg viewBox="0 0 24 24"><path d="M8 2v4M16 2v4M3 9h18M5 4h14a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm4 9h6M12 10v6"/></svg>';
  const reportIcon = '<svg viewBox="0 0 24 24"><path d="M4 19.5V4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22v-2.5ZM8 7h8M8 11h8M8 15h5"/></svg>';

  function currentMonth() { return new Date().toISOString().slice(0, 7); }
  function previousMonth() { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1); return d.toISOString().slice(0, 7); }
  function dayPartLabel(value) { return value === 'morning' ? 'Vormittag' : value === 'afternoon' ? 'Nachmittag' : 'Ganzer Tag'; }
  function formatDays(value) { const n = Number(value || 0); return Number.isInteger(n) ? String(n) : n.toLocaleString('de-DE', { maximumFractionDigits: 1 }); }

  function enhanceAbsenceNav() {
    const abs = $('#mainNav button[data-view="absences"]');
    const reports = $('#mainNav button[data-view="reports"]');
    if (abs) abs.innerHTML = `<span class="nav-icon">${absenceIcon}</span><span class="nav-label">Abwesenheiten</span>`;
    if (reports) reports.innerHTML = `<span class="nav-icon">${reportIcon}</span><span class="nav-label">Berichte</span>`;
    $$('#mainNav button').forEach(button => button.onclick = () => window.setView(button.dataset.view));
  }

  const previousShowApp = window.showApp;
  window.showApp = function absenceShowApp() {
    previousShowApp();
    enhanceAbsenceNav();
  };

  const previousSetView = window.setView;
  window.setView = function absenceSetView(view) {
    previousSetView(view);
    if (view === 'absences') {
      if ($('#eyebrow')) $('#eyebrow').textContent = 'ATTENDANCE FLOW';
      if ($('#viewTitle')) $('#viewTitle').textContent = 'Abwesenheiten';
      const slot = $('#warehouseQuickAction');
      if (slot) slot.innerHTML = '<button class="accent-action" onclick="openAbsenceCreate()">+ Abwesenheit</button>';
      renderAbsences();
    }
    if (view === 'reports') {
      if ($('#eyebrow')) $('#eyebrow').textContent = 'MONTHLY CONTROL';
      if ($('#viewTitle')) $('#viewTitle').textContent = 'Monatsberichte';
      const slot = $('#warehouseQuickAction');
      if (slot) slot.innerHTML = '';
      renderAbsenceReports();
    }
  };

  async function loadAbsenceData(month = currentMonth()) {
    const [types, rows] = await Promise.all([api('/api/absence-types'), api(`/api/absences?month=${encodeURIComponent(month)}`)]);
    state.absenceTypes = types;
    state.absences = rows;
    return rows;
  }

  function absenceStats(rows) {
    const today = new Date().toISOString().slice(0, 10);
    const sickToday = new Set(rows.filter(r => r.absence_code === 'sick' && r.starts_on <= today && r.ends_on >= today).map(r => r.worker_id)).size;
    const affected = new Set(rows.map(r => r.worker_id)).size;
    const sickDays = rows.filter(r => r.absence_code === 'sick').reduce((sum, r) => sum + Number(r.working_days || 0), 0);
    const allDays = rows.reduce((sum, r) => sum + Number(r.working_days || 0), 0);
    return { sickToday, affected, sickDays, allDays };
  }

  function absenceTable(rows) {
    if (!rows.length) return '<div class="card empty">Für diesen Monat sind keine Abwesenheiten erfasst.</div>';
    return `<div class="table-wrap"><table><thead><tr><th>Person</th><th>Art</th><th>Zeitraum</th><th>Tage</th><th>Bereich</th><th>Erfasst von</th><th></th></tr></thead><tbody>${rows.map(row => `<tr>
      <td><div class="roster-person"><div class="person-avatar">${esc(`${String(row.first_name||'').slice(0,1)}${String(row.last_name||'').slice(0,1)}`.toUpperCase())}</div><div class="person-meta"><strong>${esc(row.first_name)} ${esc(row.last_name)}</strong><small>${esc(row.agency_name || '')}</small></div></div></td>
      <td><span class="absence-type ${row.absence_code === 'sick' ? 'sick' : ''}">${esc(row.absence_type)}</span></td>
      <td><strong>${fmtDate(row.starts_on)}${row.ends_on !== row.starts_on ? ` – ${fmtDate(row.ends_on)}` : ''}</strong><small class="absence-sub">${dayPartLabel(row.day_part)}</small></td>
      <td><span class="absence-days">${formatDays(row.working_days)}</span></td>
      <td>${esc(row.department_name || '—')}</td>
      <td>${esc(row.recorded_by_name || 'System')}</td>
      <td><div class="inline-actions"><button class="secondary" onclick="openAbsenceEdit(${row.id})">Bearbeiten</button><button class="ghost" onclick="deleteAbsence(${row.id})">Löschen</button></div></td>
    </tr>`).join('')}</tbody></table></div>`;
  }

  window.renderAbsences = async function renderAbsences() {
    const root = $('#view-absences');
    if (!root) return;
    const month = $('#absenceMonth')?.value || currentMonth();
    root.innerHTML = '<div class="card empty">Abwesenheiten werden geladen …</div>';
    try {
      const rows = await loadAbsenceData(month);
      const s = absenceStats(rows);
      root.innerHTML = `
        <div class="section-head"><div><h2>Abwesenheiten & Krankentage</h2><p class="muted">Krankheit, Urlaub und sonstige Abwesenheiten werden direkt am zugeteilten Personal dokumentiert.</p></div><button class="primary" onclick="openAbsenceCreate()">+ Abwesenheit erfassen</button></div>
        <div class="status-board absence-status-board">
          <div class="status-tile"><strong>${s.sickToday}</strong><span>Heute krank</span></div>
          <div class="status-tile"><strong>${s.affected}</strong><span>Betroffene Personen</span></div>
          <div class="status-tile"><strong>${formatDays(s.sickDays)}</strong><span>Krankentage im Monat</span></div>
          <div class="status-tile"><strong>${formatDays(s.allDays)}</strong><span>Abwesenheitstage gesamt</span></div>
        </div>
        <div class="roster-toolbar absence-toolbar"><label>Monat<input id="absenceMonth" type="month" value="${esc(month)}" onchange="renderAbsences()"></label><div></div><button class="secondary" onclick="setView('reports')">Monatsbericht öffnen</button></div>
        ${absenceTable(rows)}`;
    } catch (err) { root.innerHTML = `<div class="card empty">Abwesenheiten konnten nicht geladen werden: ${esc(err.message)}</div>`; }
  };

  function absenceForm(row = null) {
    const workers = state.workers.filter(w => Boolean(w.department_name));
    const workerId = row?.worker_id || '';
    const typeId = row?.absence_type_id || state.absenceTypes[0]?.id || '';
    return `<form id="absenceForm" class="form-grid">
      <label class="full">Zeitarbeiter<select name="worker_id" required><option value="">Bitte wählen</option>${workers.map(w => `<option value="${w.id || w.worker_id}" ${Number(workerId)===Number(w.id||w.worker_id)?'selected':''}>${esc(w.first_name)} ${esc(w.last_name)} · ${esc(w.department_name || '')}</option>`).join('')}</select></label>
      <label>Abwesenheitsart<select name="absence_type_id" required>${state.absenceTypes.map(t => `<option value="${t.id}" ${Number(typeId)===Number(t.id)?'selected':''}>${esc(t.label)}</option>`).join('')}</select></label>
      <label>Umfang<select name="day_part"><option value="full" ${!row||row.day_part==='full'?'selected':''}>Ganzer Tag</option><option value="morning" ${row?.day_part==='morning'?'selected':''}>Vormittag</option><option value="afternoon" ${row?.day_part==='afternoon'?'selected':''}>Nachmittag</option></select></label>
      <label>Von<input type="date" name="starts_on" value="${esc(row?.starts_on || new Date().toISOString().slice(0,10))}" required></label>
      <label>Bis<input type="date" name="ends_on" value="${esc(row?.ends_on || new Date().toISOString().slice(0,10))}" required></label>
      <label class="full">Sachliche Notiz<textarea name="note" maxlength="1000" placeholder="Optional – keine Diagnosen oder unnötigen Gesundheitsdetails erfassen">${esc(row?.note || '')}</textarea></label>
      <div class="notice full"><strong>Datensparsam erfassen:</strong> Für Krankheit genügt die Abwesenheitsart und der Zeitraum. Medizinische Diagnosen gehören nicht in PP.</div>
      <div class="form-actions full"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Speichern</button></div>
    </form>`;
  }

  window.openAbsenceCreate = async function openAbsenceCreate() {
    try {
      if (!state.absenceTypes.length) state.absenceTypes = await api('/api/absence-types');
      openModal(`<h2>Abwesenheit erfassen</h2><p class="muted">Der Eintrag wird der aktuellen Abteilung des Mitarbeiters zugeordnet.</p>${absenceForm()}`);
      bindAbsenceForm(null);
    } catch (err) { toast(err.message, true); }
  };

  window.openAbsenceEdit = function openAbsenceEdit(id) {
    const row = state.absences.find(x => Number(x.id) === Number(id));
    if (!row) return;
    openModal(`<h2>Abwesenheit bearbeiten</h2>${absenceForm(row)}`);
    bindAbsenceForm(id);
  };

  function bindAbsenceForm(id) {
    $('#absenceForm').onsubmit = async event => {
      event.preventDefault();
      const f = event.currentTarget;
      const payload = {
        worker_id: Number(f.worker_id.value), absence_type_id: Number(f.absence_type_id.value),
        starts_on: f.starts_on.value, ends_on: f.ends_on.value, day_part: f.day_part.value, note: f.note.value
      };
      try {
        await api(id ? `/api/absences/${id}` : '/api/absences', { method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload) });
        closeModal();
        await renderAbsences();
        toast(id ? 'Abwesenheit aktualisiert.' : 'Abwesenheit erfasst.');
      } catch (err) { toast(err.message, true); }
    };
  }

  window.deleteAbsence = async function deleteAbsence(id) {
    if (!confirm('Abwesenheit wirklich löschen? Der Vorgang wird im Audit protokolliert.')) return;
    try { await api(`/api/absences/${id}`, { method: 'DELETE' }); await renderAbsences(); toast('Abwesenheit gelöscht.'); }
    catch (err) { toast(err.message, true); }
  };

  function reportWorkerTable(report) {
    const workers = report.workers || [];
    if (!workers.length) return '<div class="card empty">Keine Abwesenheiten in diesem Berichtsmonat.</div>';
    return `<div class="table-wrap"><table><thead><tr><th>Person</th><th>Zeitarbeitsfirma</th><th>Bereich</th><th>Abwesenheitstage</th><th>Krankentage</th></tr></thead><tbody>${workers.map(w => `<tr><td><strong>${esc(w.name)}</strong><br><small>${esc(w.employee_code || '')}</small></td><td>${esc(w.agency_name)}</td><td>${esc(w.department_name)}</td><td><strong>${formatDays(w.total_days)}</strong></td><td><strong>${formatDays(w.sick_days)}</strong></td></tr>`).join('')}</tbody></table></div>`;
  }

  async function loadReport() {
    const month = $('#reportMonth')?.value || previousMonth();
    const dep = state.me.role === 'admin' ? ($('#reportDepartment')?.value || '') : '';
    const qs = new URLSearchParams({ month });
    if (dep) qs.set('department_id', dep);
    const report = await api(`/api/reports/absences/monthly?${qs}`);
    state.absenceReport = report;
    return { report, month, dep };
  }

  window.renderAbsenceReports = async function renderAbsenceReports() {
    const root = $('#view-reports');
    if (!root) return;
    const chosenMonth = $('#reportMonth')?.value || previousMonth();
    const chosenDep = $('#reportDepartment')?.value || '';
    root.innerHTML = '<div class="card empty">Monatsbericht wird geladen …</div>';
    try {
      const qs = new URLSearchParams({ month: chosenMonth });
      if (state.me.role === 'admin' && chosenDep) qs.set('department_id', chosenDep);
      const report = await api(`/api/reports/absences/monthly?${qs}`);
      state.absenceReport = report;
      const s = report.summary || {};
      const current = currentMonth();
      const canFinalize = chosenMonth < current;
      root.innerHTML = `
        <div class="section-head"><div><h2>Monatsbericht ${esc(chosenMonth)}</h2><p class="muted">${esc(report.department?.name || 'Gesamtbetrieb')} · ${report.finalized ? 'Gespeicherter Monatsabschluss' : 'Live-Auswertung'}</p></div><div class="inline-actions"><button class="secondary" onclick="downloadAbsenceReport()">CSV herunterladen</button>${canFinalize?'<button class="primary" onclick="finalizeAbsenceReport()">Monat abschließen</button>':''}</div></div>
        <div class="roster-toolbar report-toolbar">
          <label>Monat<input id="reportMonth" type="month" value="${esc(chosenMonth)}" onchange="renderAbsenceReports()"></label>
          ${state.me.role === 'admin' ? `<label>Bereich<select id="reportDepartment" onchange="renderAbsenceReports()"><option value="">Gesamtbetrieb</option>${state.departments.filter(d=>d.active).map(d=>`<option value="${d.id}" ${String(chosenDep)===String(d.id)?'selected':''}>${esc(d.name)}</option>`).join('')}</select></label>` : '<div></div>'}
          <div></div>
        </div>
        <div class="status-board report-status-board">
          <div class="status-tile"><strong>${s.absence_entries || 0}</strong><span>Einträge</span></div>
          <div class="status-tile"><strong>${s.affected_workers || 0}</strong><span>Betroffene Personen</span></div>
          <div class="status-tile"><strong>${formatDays(s.absence_days)}</strong><span>Abwesenheitstage</span></div>
          <div class="status-tile"><strong>${formatDays(s.sick_days)}</strong><span>Krankentage</span></div>
        </div>
        <div class="report-type-grid">${(report.by_type||[]).map(item=>`<div class="card report-type-card"><span>${esc(item.label)}</span><strong>${formatDays(item.days)}</strong><small>Arbeitstage</small></div>`).join('') || '<div class="card empty">Keine Abwesenheitsarten im Monat.</div>'}</div>
        <div class="section-head"><div><h3>Auswertung nach Mitarbeiter</h3><p class="muted">Arbeitstage Montag bis Freitag; halbe Tage zählen 0,5.</p></div></div>
        ${reportWorkerTable(report)}`;
    } catch (err) { root.innerHTML = `<div class="card empty">Bericht konnte nicht geladen werden: ${esc(err.message)}</div>`; }
  };

  window.finalizeAbsenceReport = async function finalizeAbsenceReport() {
    const month = $('#reportMonth')?.value || previousMonth();
    const dep = state.me.role === 'admin' ? ($('#reportDepartment')?.value || '') : '';
    const qs = new URLSearchParams({ month }); if (dep) qs.set('department_id', dep);
    try { await api(`/api/reports/absences/monthly/finalize?${qs}`, { method: 'POST' }); await renderAbsenceReports(); toast('Monatsbericht wurde als Snapshot gespeichert.'); }
    catch (err) { toast(err.message, true); }
  };

  window.downloadAbsenceReport = function downloadAbsenceReport() {
    const month = $('#reportMonth')?.value || previousMonth();
    const dep = state.me.role === 'admin' ? ($('#reportDepartment')?.value || '') : '';
    const qs = new URLSearchParams({ month }); if (dep) qs.set('department_id', dep);
    location.href = `/api/reports/absences/monthly.csv?${qs}`;
  };
})();
