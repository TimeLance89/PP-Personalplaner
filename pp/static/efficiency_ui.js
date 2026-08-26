(() => {
  const monthNow = () => new Date().toISOString().slice(0, 7);
  const todayIso = () => new Date().toISOString().slice(0, 10);
  const dayPart = value => value === 'morning' ? 'Vormittag' : value === 'afternoon' ? 'Nachmittag' : 'Ganzer Tag';
  const days = value => {
    const n = Number(value || 0);
    return Number.isInteger(n) ? String(n) : n.toLocaleString('de-DE', { maximumFractionDigits: 1 });
  };

  function isSickToday(row) {
    const today = todayIso();
    if (row.absence_code !== 'sick' || row.starts_on > today) return false;
    return Boolean(row.open_ended) || row.ends_on >= today;
  }

  function openSickRows(rows) {
    return rows.filter(row => row.absence_code === 'sick' && Boolean(row.open_ended));
  }

  window.openQuickSick = async function openQuickSick() {
    try {
      const rows = await api(`/api/absences?month=${encodeURIComponent(monthNow())}`);
      const alreadyOpen = new Set(openSickRows(rows).map(row => Number(row.worker_id)));
      const workers = state.workers.filter(worker => Boolean(worker.department_name) && !alreadyOpen.has(Number(worker.id || worker.worker_id)));
      if (!workers.length) {
        toast('Alle aktuell sichtbaren Personen sind bereits krank gemeldet oder es ist niemand zugeteilt.', true);
        return;
      }
      openModal(`
        <h2>Krank ab heute</h2>
        <p class="muted">Einmal erfassen. PP zählt die Krankentage automatisch weiter, bis die Person wieder da ist.</p>
        <form id="quickSickForm" class="stack">
          <label>Zeitarbeiter
            <select name="worker_id" required>
              <option value="">Bitte wählen</option>
              ${workers.map(worker => `<option value="${worker.id || worker.worker_id}">${esc(worker.first_name)} ${esc(worker.last_name)} · ${esc(worker.department_name || '')}</option>`).join('')}
            </select>
          </label>
          <div class="notice"><strong>Keine Enddatum-Pflege:</strong> PP führt die Krankmeldung automatisch weiter. Bei Rückkehr genügt ein Klick auf „Wieder da“.</div>
          <div class="form-actions"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Krank melden</button></div>
        </form>`);
      $('#quickSickForm').onsubmit = async event => {
        event.preventDefault();
        try {
          await api('/api/absences/quick-sick', { method: 'POST', body: JSON.stringify({ worker_id: Number(event.currentTarget.worker_id.value) }) });
          closeModal();
          if (typeof window.renderAbsences === 'function' && !$('#view-absences')?.hidden) await window.renderAbsences();
          if (typeof window.renderDashboard === 'function' && !$('#view-dashboard')?.hidden) window.renderDashboard();
          toast('Krankmeldung läuft. PP zählt die Tage automatisch.');
        } catch (err) { toast(err.message, true); }
      };
    } catch (err) { toast(err.message, true); }
  };

  window.returnFromSickness = async function returnFromSickness(absenceId) {
    try {
      const result = await api(`/api/absences/${absenceId}/return`, { method: 'POST' });
      if (typeof window.renderAbsences === 'function' && !$('#view-absences')?.hidden) await window.renderAbsences();
      if (typeof window.renderDashboard === 'function' && !$('#view-dashboard')?.hidden) window.renderDashboard();
      toast(`Rückkehr erfasst. Letzter Fehltag: ${fmtDate(result.ends_on)}.`);
    } catch (err) { toast(err.message, true); }
  };

  const previousRenderAbsences = window.renderAbsences;
  window.renderAbsences = async function efficientAbsences() {
    const root = $('#view-absences');
    if (!root) return;
    const month = $('#absenceMonth')?.value || monthNow();
    root.innerHTML = '<div class="card empty">Abwesenheiten werden geladen …</div>';
    try {
      const [types, rows] = await Promise.all([
        api('/api/absence-types'),
        api(`/api/absences?month=${encodeURIComponent(month)}`)
      ]);
      state.absenceTypes = types;
      state.absences = rows;
      const openSick = openSickRows(rows);
      const sickToday = new Set(rows.filter(isSickToday).map(row => row.worker_id)).size;
      const affected = new Set(rows.map(row => row.worker_id)).size;
      const sickDays = rows.filter(row => row.absence_code === 'sick').reduce((sum, row) => sum + Number(row.working_days || 0), 0);
      const allDays = rows.reduce((sum, row) => sum + Number(row.working_days || 0), 0);

      const openPanel = openSick.length ? `
        <div class="card" style="margin-bottom:16px">
          <div class="section-head"><div><h3>Aktuell krank</h3><p class="muted">Diese Einträge laufen automatisch weiter. Nur die Rückkehr muss bestätigt werden.</p></div><span class="chip warning">${openSick.length} offen</span></div>
          <div class="workflow-list">${openSick.map(row => `
            <div class="workflow-item decision">
              <div class="workflow-state"><span></span><strong>Krank</strong></div>
              <div class="workflow-copy"><strong>${esc(row.first_name)} ${esc(row.last_name)}</strong><span>${esc(row.department_name || '')} · seit ${fmtDate(row.starts_on)}</span><small>${days(row.working_days)} Arbeitstage bisher</small></div>
              <div class="workflow-actions"><button class="primary" onclick="returnFromSickness(${row.id})">Wieder da</button></div>
            </div>`).join('')}</div>
        </div>` : '';

      const table = rows.length ? `<div class="table-wrap"><table><thead><tr><th>Person</th><th>Art</th><th>Zeitraum</th><th>Tage</th><th>Bereich</th><th></th></tr></thead><tbody>${rows.map(row => `
        <tr>
          <td><strong>${esc(row.first_name)} ${esc(row.last_name)}</strong><br><small>${esc(row.agency_name || '')}</small></td>
          <td><span class="absence-type ${row.absence_code === 'sick' ? 'sick' : ''}">${esc(row.absence_type)}</span></td>
          <td><strong>${Boolean(row.open_ended) ? `Seit ${fmtDate(row.starts_on)} · läuft` : `${fmtDate(row.starts_on)}${row.ends_on !== row.starts_on ? ` – ${fmtDate(row.ends_on)}` : ''}`}</strong><br><small>${dayPart(row.day_part)}</small></td>
          <td><strong>${days(row.working_days)}</strong></td>
          <td>${esc(row.department_name || '—')}</td>
          <td><div class="inline-actions">${Boolean(row.open_ended) ? `<button class="primary" onclick="returnFromSickness(${row.id})">Wieder da</button>` : ''}<button class="secondary" onclick="openAbsenceEdit(${row.id})">Korrigieren</button></div></td>
        </tr>`).join('')}</tbody></table></div>` : '<div class="card empty">Für diesen Monat ist nichts zu pflegen.</div>';

      root.innerHTML = `
        <div class="section-head">
          <div><h2>Abwesenheiten</h2><p class="muted">Der schnelle Weg: krank melden, später „Wieder da“. PP übernimmt Zählung und Monatsauswertung.</p></div>
          <div class="inline-actions"><button class="primary" onclick="openQuickSick()">Krank ab heute</button><button class="secondary" onclick="openAbsenceCreate()">Andere Abwesenheit</button></div>
        </div>
        <div class="status-board absence-status-board">
          <div class="status-tile"><strong>${sickToday}</strong><span>Heute krank</span></div>
          <div class="status-tile"><strong>${openSick.length}</strong><span>Laufende Krankmeldungen</span></div>
          <div class="status-tile"><strong>${days(sickDays)}</strong><span>Krankentage im Monat</span></div>
          <div class="status-tile"><strong>${days(allDays)}</strong><span>Abwesenheitstage gesamt</span></div>
        </div>
        ${openPanel}
        <div class="roster-toolbar absence-toolbar"><label>Monat<input id="absenceMonth" type="month" value="${esc(month)}" onchange="renderAbsences()"></label><div></div><button class="secondary" onclick="setView('reports')">Bericht ansehen</button></div>
        ${table}`;
    } catch (err) {
      root.innerHTML = `<div class="card empty">Abwesenheiten konnten nicht geladen werden: ${esc(err.message)}</div>`;
      if (previousRenderAbsences) console.debug('Fallback renderer available', Boolean(previousRenderAbsences));
    }
  };

  async function injectSicknessIntoDashboard() {
    const root = $('#view-dashboard');
    if (!root || root.hidden || $('#todaySicknessPanel')) return;
    try {
      const rows = await api(`/api/absences?month=${encodeURIComponent(monthNow())}`);
      const sick = rows.filter(isSickToday);
      if (!sick.length) return;
      const anchor = $('.attention-strip', root) || $('.ops-hero', root);
      if (!anchor) return;
      const panel = document.createElement('div');
      panel.id = 'todaySicknessPanel';
      panel.className = 'card';
      panel.style.marginBottom = '16px';
      panel.innerHTML = `
        <div class="section-head"><div><span class="ops-kicker">HEUTE</span><h3>${sick.length} krank gemeldet</h3><p class="muted">PP führt laufende Krankmeldungen automatisch weiter.</p></div><button class="secondary" onclick="setView('absences')">Abwesenheiten</button></div>
        <div class="workflow-list">${sick.slice(0, 6).map(row => `<div class="workflow-item ${row.open_ended ? 'decision' : 'watch'}"><div class="workflow-copy"><strong>${esc(row.first_name)} ${esc(row.last_name)}</strong><span>${esc(row.department_name || '')} · seit ${fmtDate(row.starts_on)}</span></div><div class="workflow-actions">${row.open_ended ? `<button class="primary" onclick="returnFromSickness(${row.id})">Wieder da</button>` : ''}</div></div>`).join('')}</div>`;
      anchor.insertAdjacentElement('afterend', panel);
    } catch { /* Dashboard bleibt auch ohne Zusatzpanel nutzbar. */ }
  }

  const previousDashboard = window.renderDashboard;
  window.renderDashboard = function efficientDashboard() {
    previousDashboard();
    queueMicrotask(injectSicknessIntoDashboard);
  };

  const previousReports = window.renderAbsenceReports;
  window.renderAbsenceReports = async function efficientReports() {
    await previousReports();
    const root = $('#view-reports');
    if (!root) return;
    const manual = $('button[onclick="finalizeAbsenceReport()"]', root);
    if (manual) {
      if (state.me?.role === 'admin') {
        manual.textContent = 'Nach Korrektur neu erzeugen';
        manual.className = 'ghost';
        manual.title = 'Nur nötig, wenn nachträglich Daten korrigiert wurden.';
      } else {
        manual.remove();
      }
    }
    const subtitle = $('.section-head .muted', root);
    if (subtitle && state.absenceReport?.finalized) subtitle.textContent = `${state.absenceReport.department?.name || 'Gesamtbetrieb'} · automatisch gespeicherter Monatsbericht`;
  };

  const previousSetView = window.setView;
  window.setView = function efficientSetView(view) {
    previousSetView(view);
    if (view === 'absences') {
      const slot = $('#warehouseQuickAction');
      if (slot) slot.innerHTML = '<button class="accent-action" onclick="openQuickSick()">Krank ab heute</button>';
    }
  };
})();
