(() => {
  const stateMeta = {
    needs_decision: ['Du entscheidest', 'decision'],
    pp_handling: ['PP kümmert sich', 'handling'],
    open: ['Beobachten', 'watch'],
    done: ['Erledigt', 'done'],
    dismissed: ['Ausgeblendet', 'done']
  };

  function nl2br(value) {
    return esc(value || '').replace(/\n/g, '<br>');
  }

  function dueLabel(value) {
    if (!value) return '';
    return `<span class="workflow-due">bis ${fmtDate(value)}</span>`;
  }

  function workflowAction(item) {
    if (item.state === 'pp_handling') return '<span class="workflow-owned">Automatisch</span>';
    if (item.action_hint === 'assignment_review' && item.worker_id) {
      return `<div class="inline-actions"><button class="secondary" onclick="extendWorkflowAssignment(${item.id},'${esc(item.assigned_until || '')}')">Verlängern</button><button class="danger" onclick="openOffboarding(${item.worker_id})">Abmelden</button><button class="ghost" onclick="resolveWorkflowItem(${item.id})">Erledigt</button></div>`;
    }
    if (item.action_hint === 'assign_worker' && state.me?.role === 'admin') {
      return `<div class="inline-actions"><button class="secondary" onclick="setView('workers')">Personal öffnen</button><button class="ghost" onclick="resolveWorkflowItem(${item.id})">Erledigt</button></div>`;
    }
    if (item.state === 'needs_decision') return `<button class="ghost" onclick="resolveWorkflowItem(${item.id})">Erledigt</button>`;
    return '';
  }

  function workflowRows(items) {
    if (!items.length) return '<div class="workflow-empty"><strong>Alles im Fluss.</strong><span>PP hat aktuell nichts, das Ihre Aufmerksamkeit braucht.</span></div>';
    return items.slice(0, 10).map(item => {
      const [label, cls] = stateMeta[item.state] || [item.state, 'watch'];
      return `<div class="workflow-item ${cls}">
        <div class="workflow-state"><span></span><strong>${label}</strong></div>
        <div class="workflow-copy"><strong>${esc(item.title)}</strong><span>${esc(item.detail)}</span><small>${esc(item.department_name || '')} ${dueLabel(item.due_at)}</small></div>
        <div class="workflow-actions">${workflowAction(item)}</div>
      </div>`;
    }).join('');
  }

  function briefingCard(briefing) {
    if (!briefing?.available) {
      return `<div class="daily-briefing-card"><div><span class="ops-kicker">DAILY BRIEF</span><h3>Noch kein Tagesbriefing</h3><p>PP fasst Personalbestand, Entscheidungen und laufende Automationen zu einem kurzen Arbeitsstart zusammen.</p></div><button class="secondary" onclick="generateWorkflowBriefing()">Jetzt erstellen</button></div>`;
    }
    const s = briefing.summary || {};
    return `<div class="daily-briefing-card">
      <div class="briefing-main"><span class="ops-kicker">DAILY BRIEF · ${esc(briefing.briefing_date)}</span><h3>${esc(briefing.title)}</h3><div class="briefing-kpis"><span><b>${s.active_workers ?? 0}</b> im Einsatz</span><span class="${Number(s.decisions || 0) ? 'hot' : ''}"><b>${s.decisions ?? 0}</b> Entscheidungen</span><span><b>${s.pp_handling ?? 0}</b> durch PP</span><span><b>${s.upcoming_offboardings ?? 0}</b> kommende Abmeldungen</span></div></div>
      <details class="briefing-details"><summary>Briefing lesen</summary><div>${nl2br(briefing.body)}</div></details>
      <button class="ghost" onclick="generateWorkflowBriefing()">Aktualisieren</button>
    </div>`;
  }

  async function loadWorkflowDashboard() {
    const anchor = $('.autonomy-banner') || $('.ops-hero');
    if (!anchor || $('#workflowDashboard')) return;
    const shell = document.createElement('section');
    shell.id = 'workflowDashboard';
    shell.className = 'workflow-dashboard';
    shell.innerHTML = '<div class="card empty">PP Workflow Center wird geladen …</div>';
    anchor.insertAdjacentElement('afterend', shell);
    try {
      const [items, briefing] = await Promise.all([api('/api/workflow/inbox'), api('/api/workflow/briefings/latest')]);
      const decisions = items.filter(i => i.state === 'needs_decision').length;
      const handling = items.filter(i => i.state === 'pp_handling').length;
      const watching = items.filter(i => i.state === 'open').length;
      shell.innerHTML = `
        ${briefingCard(briefing)}
        <div class="workflow-inbox-card">
          <div class="workflow-inbox-head"><div><span class="ops-kicker">PP WORK INBOX</span><h3>PP kümmert sich darum</h3><p>Nur Entscheidungen bleiben bei Ihnen. Routinearbeit läuft nach den freigegebenen Regeln weiter.</p></div><div class="workflow-counters"><span class="decision"><b>${decisions}</b> entscheiden</span><span class="handling"><b>${handling}</b> PP aktiv</span><span><b>${watching}</b> beobachten</span></div></div>
          <div class="workflow-list">${workflowRows(items)}</div>
        </div>`;
    } catch (err) {
      shell.innerHTML = `<div class="card empty">Workflow Center konnte nicht geladen werden: ${esc(err.message)}</div>`;
    }
  }

  const previousDashboard = window.renderDashboard;
  window.renderDashboard = function workflowDashboard() {
    previousDashboard();
    queueMicrotask(loadWorkflowDashboard);
  };

  window.generateWorkflowBriefing = async function generateWorkflowBriefing() {
    try {
      await api('/api/workflow/briefings/generate', { method: 'POST' });
      renderDashboard();
      toast('Tagesbriefing wurde aktualisiert.');
    } catch (err) { toast(err.message, true); }
  };

  window.resolveWorkflowItem = async function resolveWorkflowItem(itemId) {
    try {
      await api(`/api/workflow/inbox/${itemId}/resolve`, { method: 'POST' });
      renderDashboard();
      toast('Vorgang wurde als erledigt markiert.');
    } catch (err) { toast(err.message, true); }
  };

  window.extendWorkflowAssignment = function extendWorkflowAssignment(itemId, currentEnd) {
    const fallback = currentEnd || isoPlusDays(30);
    openModal(`<h2>Einsatz verlängern</h2><p class="muted">PP aktualisiert das Einsatzende und plant den nächsten Prüfpunkt automatisch neu.</p><form id="extendWorkflowForm" class="stack"><label>Neues Einsatzende<input type="date" name="assigned_until" value="${esc(fallback)}" required></label><div class="form-actions"><button type="button" class="ghost" onclick="closeModal()">Abbrechen</button><button class="primary">Verlängern</button></div></form>`);
    $('#extendWorkflowForm').onsubmit = async event => {
      event.preventDefault();
      try {
        await api(`/api/workflow/inbox/${itemId}/extend-assignment`, { method: 'POST', body: JSON.stringify({ assigned_until: event.currentTarget.assigned_until.value }) });
        closeModal();
        await refresh();
        toast('Einsatz wurde verlängert. PP plant die nächste Prüfung automatisch.');
      } catch (err) { toast(err.message, true); }
    };
  };

  const previousAdminAutonomy = window.adminAutonomy;
  window.adminAutonomy = function workflowAdminAutonomy() {
    return `${previousAdminAutonomy()}
      <div class="workflow-admin-extension">
        <div class="settings-heading"><div><div class="ops-kicker">DECISION FLOW</div><h2>Briefing & vorbereitete Entscheidungen</h2><p class="muted">PP bereitet auslaufende Einsätze vor und bringt morgens nur das auf den Tisch, was relevant ist.</p></div></div>
        <form id="workflowConfigForm" class="card settings-card" onsubmit="saveWorkflowConfig(event)">
          <div id="workflowConfigFields" class="form-grid"><div class="muted">Einstellungen werden geladen …</div></div>
          <div class="settings-actions"><button class="primary">Workflow speichern</button></div>
        </form>
        <div class="settings-grid workflow-admin-grid">
          <div class="card settings-card"><div class="settings-heading compact"><div><h3>Briefing-Empfänger</h3><p class="muted">E-Mail ist optional. In PP wird das Briefing immer bereitgestellt.</p></div></div><div id="workflowRecipients"><div class="muted">Empfänger werden geladen …</div></div></div>
          <div class="card settings-card"><div class="settings-heading compact"><div><h3>Geplante Aktionen</h3><p class="muted">Von PP vorbereitete Prüfpunkte für befristete Einsätze.</p></div></div><div id="workflowSchedules"><div class="muted">Planung wird geladen …</div></div></div>
        </div>
      </div>`;
  };

  function configFields(config) {
    return `
      <label>Auslaufende Einsätze vorbereiten<select name="workflow_assignment_review_enabled"><option value="true" ${config.workflow_assignment_review_enabled ? 'selected' : ''}>Aktiv</option><option value="false" ${!config.workflow_assignment_review_enabled ? 'selected' : ''}>Aus</option></select></label>
      <label>Entscheidung vor Einsatzende<input type="number" min="1" max="60" name="workflow_assignment_review_days" value="${esc(config.workflow_assignment_review_days ?? 7)}"><small>Tage vorher</small></label>
      <label>Tagesbriefing<select name="briefing_enabled"><option value="true" ${config.briefing_enabled ? 'selected' : ''}>Aktiv</option><option value="false" ${!config.briefing_enabled ? 'selected' : ''}>Aus</option></select></label>
      <label>Briefing ab Uhrzeit<input type="number" min="0" max="23" name="briefing_hour" value="${esc(config.briefing_hour ?? 6)}"><small>Uhr, Europe/Berlin</small></label>
      <label>Vorschauzeitraum<input type="number" min="1" max="30" name="briefing_days_ahead" value="${esc(config.briefing_days_ahead ?? 7)}"><small>Tage</small></label>
      <label>E-Mail-Briefings global<select name="briefing_email_enabled"><option value="true" ${config.briefing_email_enabled ? 'selected' : ''}>Erlauben</option><option value="false" ${!config.briefing_email_enabled ? 'selected' : ''}>Nur in PP</option></select></label>`;
  }

  function recipientsTable(rows) {
    if (!rows.length) return '<div class="empty">Keine aktiven Benutzer.</div>';
    return `<div class="recipient-list">${rows.map(row => `<div class="recipient-row" data-user="${row.user_id}"><div><strong>${esc(row.display_name)}</strong><span>${esc(row.role === 'admin' ? 'Administrator' : row.department_name || 'Bereichsleiter')}</span></div><input type="email" class="recipient-email" value="${esc(row.email || '')}" placeholder="name@firma.de"><label class="recipient-check"><input type="checkbox" class="recipient-enabled" ${row.briefing_email_enabled ? 'checked' : ''}> per E-Mail</label><button class="secondary" onclick="saveWorkflowRecipient(${row.user_id})">Speichern</button></div>`).join('')}</div>`;
  }

  function schedulesList(rows) {
    const active = rows.filter(row => row.state === 'scheduled').slice(0, 12);
    if (!active.length) return '<div class="workflow-empty small"><strong>Keine offenen Prüfpunkte.</strong><span>PP plant automatisch, sobald befristete Einsätze vorhanden sind.</span></div>';
    return active.map(row => `<div class="schedule-row"><div><strong>${row.action_type === 'assignment_review' ? 'Einsatzentscheidung vorbereiten' : esc(row.action_type)}</strong><span>${esc(row.department_name || '')}</span></div><span>${fmtDate(row.scheduled_for)}</span></div>`).join('');
  }

  window.loadWorkflowAdmin = async function loadWorkflowAdmin() {
    if (state.me?.role !== 'admin' || adminTab !== 'autonomy') return;
    try {
      const [config, recipients, schedules] = await Promise.all([
        api('/api/admin/workflow/config'), api('/api/admin/workflow/notifications'), api('/api/workflow/schedules')
      ]);
      if ($('#workflowConfigFields')) $('#workflowConfigFields').innerHTML = configFields(config);
      if ($('#workflowRecipients')) $('#workflowRecipients').innerHTML = recipientsTable(recipients);
      if ($('#workflowSchedules')) $('#workflowSchedules').innerHTML = schedulesList(schedules);
    } catch (err) { toast(`Workflow-Einstellungen: ${err.message}`, true); }
  };

  window.saveWorkflowConfig = async function saveWorkflowConfig(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = {
      workflow_assignment_review_enabled: form.workflow_assignment_review_enabled.value === 'true',
      workflow_assignment_review_days: Number(form.workflow_assignment_review_days.value),
      briefing_enabled: form.briefing_enabled.value === 'true',
      briefing_hour: Number(form.briefing_hour.value),
      briefing_days_ahead: Number(form.briefing_days_ahead.value),
      briefing_email_enabled: form.briefing_email_enabled.value === 'true'
    };
    try {
      await api('/api/admin/workflow/config', { method: 'PUT', body: JSON.stringify({ values }) });
      await loadWorkflowAdmin();
      toast('Briefing- und Entscheidungsworkflow gespeichert.');
    } catch (err) { toast(err.message, true); }
  };

  window.saveWorkflowRecipient = async function saveWorkflowRecipient(userId) {
    const row = $(`.recipient-row[data-user="${userId}"]`);
    if (!row) return;
    try {
      await api('/api/admin/workflow/notifications', {
        method: 'PUT',
        body: JSON.stringify({ user_id: userId, email: $('.recipient-email', row).value, briefing_email_enabled: $('.recipient-enabled', row).checked })
      });
      toast('Briefing-Empfänger gespeichert.');
    } catch (err) { toast(err.message, true); }
  };

  const previousRenderAdmin = window.renderAdmin;
  window.renderAdmin = function workflowRenderAdmin() {
    previousRenderAdmin();
    if (adminTab === 'autonomy') queueMicrotask(loadWorkflowAdmin);
  };
})();
