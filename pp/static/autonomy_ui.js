(() => {
  state.automation = null;

  const modeMeta = {
    manual: {
      title: 'Manuell',
      tag: '0',
      text: 'PP beobachtet nicht automatisch. Alle Vorgänge werden bewusst durch Benutzer ausgelöst.'
    },
    assist: {
      title: 'Assistent',
      tag: '1',
      text: 'PP überwacht Fristen und Auffälligkeiten und stellt sie bereit, führt aber keine Aktion selbst aus.'
    },
    rules: {
      title: 'Regelbetrieb',
      tag: '2',
      text: 'PP führt ausdrücklich freigegebene Verwaltungsregeln selbstständig aus, z. B. Mail-Retries.'
    },
    autopilot: {
      title: 'Autopilot',
      tag: '3',
      text: 'PP übernimmt freigegebene Routinearbeit vollständig und erledigt zusätzlich technische Wartung.'
    }
  };

  const originalDashboard = window.renderDashboard;
  window.renderDashboard = function autonomyDashboard() {
    originalDashboard();
    if (state.me?.role !== 'admin') return;
    const mode = String(state.settings?.autonomy_mode || 'manual');
    const meta = modeMeta[mode] || modeMeta.manual;
    const stopped = Boolean(state.settings?.automation_emergency_stop);
    const hero = $('.ops-hero');
    if (!hero) return;
    const banner = document.createElement('div');
    banner.className = `autonomy-banner ${stopped ? 'stopped' : mode}`;
    banner.innerHTML = `
      <div class="autonomy-pulse"></div>
      <div><span>AUTOMATION</span><strong>${stopped ? 'NOT-AUS AKTIV' : meta.title}</strong><small>${stopped ? 'Automatische Aktionen sind sofort gestoppt.' : meta.text}</small></div>
      <button class="ghost" onclick="setAdminTab('autonomy');setView('admin')">Steuern</button>`;
    hero.insertAdjacentElement('afterend', banner);
  };

  function adminContentAutonomy(tab) {
    if (tab === 'autonomy') return adminAutonomy();
    if (tab === 'system') return adminCompany();
    if (tab === 'mail') return adminMail();
    if (tab === 'workflow') return adminWorkflow();
    if (tab === 'departments') return adminDepartments();
    if (tab === 'agencies') return adminAgencies();
    if (tab === 'users') return adminUsers();
    if (tab === 'fields') return adminFields();
    if (tab === 'reasons') return adminReasons();
    if (tab === 'security') return adminSecurity();
    return adminCompany();
  }

  const adminGroupsAutonomy = [
    ['Betrieb', [['system','Unternehmen'], ['departments','Abteilungen'], ['agencies','Zeitarbeitsfirmen']]],
    ['Automation', [['autonomy','Autonomie & Regeln']]],
    ['Kommunikation', [['mail','E-Mail & Microsoft 365']]],
    ['Regeln & Datenmodell', [['workflow','Abmeldeprozess'], ['reasons','Abmeldegründe'], ['fields','Zusatzfelder']]],
    ['Zugriff & Governance', [['users','Bereichsleiter'], ['security','Sicherheit & Daten']]]
  ];

  window.renderAdmin = function autonomyAdmin() {
    if (state.me.role !== 'admin') return;
    const rail = adminGroupsAutonomy.map(([group, tabs]) => `<div class="admin-rail-group">${esc(group)}</div>${tabs.map(([key,label]) => `<button class="${adminTab === key ? 'active' : ''}" onclick="setAdminTab('${key}')">${esc(label)}</button>`).join('')}`).join('');
    $('#view-admin').innerHTML = `<div class="admin-workspace"><aside class="admin-rail">${rail}</aside><div id="adminPane" class="admin-pane">${adminContentAutonomy(adminTab)}</div></div>`;
    if (adminTab === 'mail') toggleMailProvider();
    if (adminTab === 'autonomy') loadAutomationStatus();
  };

  function boolSelect(key, value, yes='Aktiv', no='Aus') {
    return `<select data-setting="${key}" data-bool><option value="true" ${value ? 'selected' : ''}>${yes}</option><option value="false" ${!value ? 'selected' : ''}>${no}</option></select>`;
  }

  window.adminAutonomy = function adminAutonomy() {
    const s = state.settings || {};
    const current = String(s.autonomy_mode || 'manual');
    return `
      <div class="settings-heading autonomy-heading">
        <div><div class="ops-kicker">PP AUTOMATION ENGINE</div><h2>Autonomie & Regeln</h2><p class="muted">PP darf Routinearbeit selbst erledigen – aber nur genau innerhalb der Regeln, die hier freigegeben sind.</p></div>
        <div class="autonomy-head-actions"><button class="secondary" onclick="runAutomationNow()">Jetzt prüfen</button><button class="danger autonomy-stop" onclick="toggleEmergencyStop()">${s.automation_emergency_stop ? 'Autonomie fortsetzen' : 'NOT-AUS'}</button></div>
      </div>

      <div class="autonomy-mode-grid">
        ${Object.entries(modeMeta).map(([key,meta]) => `<button type="button" class="autonomy-mode ${current === key ? 'active' : ''}" onclick="selectAutonomyMode('${key}')"><span>${meta.tag}</span><strong>${meta.title}</strong><small>${meta.text}</small></button>`).join('')}
      </div>

      <div id="automationLiveStatus" class="automation-live"><div class="card empty">Automationsstatus wird geladen …</div></div>

      <form id="autonomySettingsForm" class="settings-stack" onsubmit="saveAutonomySettings(event)">
        <input type="hidden" id="autonomyModeInput" data-setting="autonomy_mode" value="${esc(current)}">
        <div class="settings-grid autonomy-rules-grid">
          <div class="card settings-card"><div class="rule-card-head"><div><h3>Kommunikation selbst heilen</h3><p class="muted">Fehlgeschlagene Abmelde-Mails automatisch erneut senden.</p></div><span class="rule-safe">SAFE AUTO</span></div><div class="form-grid"><label>Regel${boolSelect('automation_retry_failed_mail', Boolean(s.automation_retry_failed_mail))}</label><label>Erneut nach<input type="number" min="1" max="1440" data-setting="automation_retry_after_minutes" data-number value="${esc(s.automation_retry_after_minutes || 15)}"><small>Minuten</small></label><label>Max. Versuche<input type="number" min="1" max="50" data-setting="automation_retry_max_attempts" data-number value="${esc(s.automation_retry_max_attempts || 5)}"></label></div></div>

          <div class="card settings-card"><div class="rule-card-head"><div><h3>Fristen überwachen</h3><p class="muted">Abmeldungen werden automatisch in die Attention Queue aufgenommen.</p></div><span class="rule-watch">WATCH</span></div><div class="form-grid"><label>Überwachung${boolSelect('automation_watch_upcoming', Boolean(s.automation_watch_upcoming))}</label><label>Vorlauf<input type="number" min="1" max="60" data-setting="automation_upcoming_days" data-number value="${esc(s.automation_upcoming_days || 7)}"><small>Tage</small></label></div></div>

          <div class="card settings-card"><div class="rule-card-head"><div><h3>Unzugeteiltes Personal erkennen</h3><p class="muted">Aktive Zeitarbeiter ohne laufende Zuteilung werden automatisch sichtbar gemacht.</p></div><span class="rule-watch">WATCH</span></div><div class="form-grid"><label>Überwachung${boolSelect('automation_watch_unassigned', Boolean(s.automation_watch_unassigned))}</label></div><p class="settings-note">PP weist Personen nicht eigenständig einer Abteilung zu. Es macht den Handlungsbedarf sichtbar.</p></div>

          <div class="card settings-card"><div class="rule-card-head"><div><h3>Auslaufende Einsätze</h3><p class="muted">Befristete Zuteilungen werden vor Ablauf automatisch hervorgehoben.</p></div><span class="rule-watch">WATCH</span></div><div class="form-grid"><label>Überwachung${boolSelect('automation_watch_assignment_end', Boolean(s.automation_watch_assignment_end))}</label><label>Vorlauf<input type="number" min="1" max="60" data-setting="automation_assignment_end_days" data-number value="${esc(s.automation_assignment_end_days || 3)}"><small>Tage</small></label></div></div>

          <div class="card settings-card"><div class="rule-card-head"><div><h3>Technische Selbstpflege</h3><p class="muted">Im Autopilot darf PP abgelaufene Sessions und alte Auditdaten nach der Aufbewahrungsregel entfernen.</p></div><span class="rule-autopilot">AUTOPILOT</span></div><div class="form-grid"><label>Housekeeping${boolSelect('automation_housekeeping', Boolean(s.automation_housekeeping))}</label></div></div>

          <div class="card settings-card"><div class="rule-card-head"><div><h3>Prüfintervall</h3><p class="muted">Wie oft der lokale NAS-Agent die freigegebenen Regeln prüft.</p></div></div><div class="form-grid"><label>Alle<input type="number" min="1" max="1440" data-setting="automation_interval_minutes" data-number value="${esc(s.automation_interval_minutes || 5)}"><small>Minuten</small></label></div></div>
        </div>
        <div class="settings-actions autonomy-save"><span>Personalentscheidungen werden nicht autonom getroffen. PP automatisiert den freigegebenen administrativen Ablauf.</span><button class="primary">Autonomie speichern</button></div>
      </form>`;
  };

  window.selectAutonomyMode = function selectAutonomyMode(mode) {
    if (!modeMeta[mode]) return;
    $('#autonomyModeInput').value = mode;
    $$('.autonomy-mode').forEach((el, index) => el.classList.toggle('active', Object.keys(modeMeta)[index] === mode));
  };

  window.saveAutonomySettings = async function saveAutonomySettings(event) {
    event.preventDefault();
    const ok = await saveSettingsForm(null, 'autonomySettingsForm', false);
    if (!ok) return;
    await reloadSettings();
    renderAdmin();
    toast('Autonomie-Regeln wurden gespeichert.');
  };

  function severityChip(severity) {
    const map = { danger: 'danger', warning: 'warning', info: '' };
    return `<span class="chip ${map[severity] || ''}">${severity === 'danger' ? 'Kritisch' : severity === 'warning' ? 'Beobachten' : 'Info'}</span>`;
  }

  window.loadAutomationStatus = async function loadAutomationStatus() {
    try {
      const data = await api('/api/admin/automation/status');
      state.automation = data;
      const root = $('#automationLiveStatus');
      if (!root) return;
      const last = data.last_run;
      const events = (data.events || []).filter(e => e.state === 'open').slice(0, 12);
      root.innerHTML = `
        <div class="automation-status-grid">
          <div class="card automation-status ${data.emergency_stop ? 'danger-state' : ''}"><span>STATUS</span><strong>${data.emergency_stop ? 'Gestoppt' : (modeMeta[data.mode]?.title || data.mode)}</strong><small>${data.emergency_stop ? 'Not-Aus ist aktiv' : `Prüfung alle ${data.interval_minutes} Min.`}</small></div>
          <div class="card automation-status"><span>OFFENE EREIGNISSE</span><strong>${data.open_counts.total}</strong><small>${data.open_counts.danger} kritisch · ${data.open_counts.warning} beobachten</small></div>
          <div class="card automation-status"><span>LETZTER LAUF</span><strong>${last ? (last.status === 'success' ? 'OK' : last.status) : '—'}</strong><small>${last?.finished_at ? esc(last.finished_at) : 'Noch kein Lauf'}</small></div>
        </div>
        <div class="section-head"><div><h3>Automation Inbox</h3><p class="muted">PP sammelt hier automatisch erkannte Abweichungen und Fristen.</p></div></div>
        <div class="automation-events">${events.length ? events.map(e => `<div class="automation-event"><div><div class="automation-event-top">${severityChip(e.severity)}<strong>${esc(e.title)}</strong></div><span>${esc(e.detail)}</span></div><button class="ghost" onclick="resolveAutomationEvent(${e.id})">Erledigt</button></div>`).join('') : '<div class="card empty">Keine offenen Automation-Ereignisse.</div>'}</div>`;
    } catch (err) {
      if ($('#automationLiveStatus')) $('#automationLiveStatus').innerHTML = `<div class="notice">${esc(err.message)}</div>`;
    }
  };

  window.runAutomationNow = async function runAutomationNow() {
    try {
      const result = await api('/api/admin/automation/run', { method: 'POST' });
      await loadAutomationStatus();
      toast(result.skipped ? 'Automationslauf wurde wegen des aktuellen Modus übersprungen.' : 'PP hat alle Automationsregeln geprüft.');
    } catch (err) { toast(err.message, true); }
  };

  window.toggleEmergencyStop = async function toggleEmergencyStop() {
    const stopped = Boolean(state.settings?.automation_emergency_stop);
    if (!stopped && !confirm('Automatische Aktionen sofort stoppen? Beobachtungen und Daten bleiben erhalten.')) return;
    try {
      await api(stopped ? '/api/admin/automation/resume' : '/api/admin/automation/emergency-stop', { method: 'POST' });
      await reloadSettings();
      renderAdmin();
      toast(stopped ? 'Autonomie wurde fortgesetzt.' : 'Not-Aus ist aktiv. Automatische Aktionen sind gestoppt.', !stopped);
    } catch (err) { toast(err.message, true); }
  };

  window.resolveAutomationEvent = async function resolveAutomationEvent(id) {
    try {
      await api(`/api/admin/automation/events/${id}/resolve`, { method: 'POST' });
      await loadAutomationStatus();
    } catch (err) { toast(err.message, true); }
  };
})();
