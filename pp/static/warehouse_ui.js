(() => {
  const icons = {
    dashboard: '<svg viewBox="0 0 24 24"><path d="M4 13h6V4H4v9Zm10 7h6V11h-6v9ZM4 20h6v-3H4v3Zm10-13h6V4h-6v3Z"/></svg>',
    workers: '<svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm13 10v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    offboardings: '<svg viewBox="0 0 24 24"><path d="M9 11 12 14 22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
    admin: '<svg viewBox="0 0 24 24"><path d="M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5ZM19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.12.37.33.7.6 1 .3.27.69.41 1.1.4H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51.6Z"/></svg>',
    audit: '<svg viewBox="0 0 24 24"><path d="M3 3v5h5M3.5 9a9 9 0 1 1 .5 7M12 7v5l3 2"/></svg>'
  };

  const navLabels = {
    dashboard: 'Control Tower',
    workers: 'Personal',
    offboardings: 'Abmeldungen',
    admin: 'System',
    audit: 'Audit'
  };

  function todayLabel() {
    const now = new Date();
    return {
      date: new Intl.DateTimeFormat('de-DE', { weekday: 'short', day: '2-digit', month: 'short' }).format(now),
      week: `KW ${getWeek(now)}`
    };
  }

  function getWeek(date) {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    const day = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - day);
    const start = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    return Math.ceil((((d - start) / 86400000) + 1) / 7);
  }

  function enhanceShell() {
    $$('#mainNav button').forEach(button => {
      const view = button.dataset.view;
      if (!view || !icons[view]) return;
      button.innerHTML = `<span class="nav-icon">${icons[view]}</span><span class="nav-label">${navLabels[view]}</span>`;
    });

    const topbar = $('.topbar');
    if (topbar && !$('.topbar-actions', topbar)) {
      const currentContext = $('#contextBadge');
      const date = todayLabel();
      const actions = document.createElement('div');
      actions.className = 'topbar-actions';
      actions.innerHTML = `<div class="ops-date"><strong>${esc(date.date)}</strong><span>${esc(date.week)} · Operations</span></div><div id="warehouseQuickAction"></div>`;
      if (currentContext) actions.appendChild(currentContext);
      topbar.appendChild(actions);
    }
    updateHeader('dashboard');
  }

  function updateHeader(view) {
    const titleMap = {
      dashboard: ['PEOPLE OPERATIONS', 'Control Tower'],
      workers: ['WORKFORCE ROSTER', state.me?.role === 'admin' ? 'Personalbestand' : 'Mein Personal'],
      offboardings: ['WORKFORCE FLOW', 'Abmeldungen'],
      admin: ['SYSTEM CONTROL', 'Verwaltung'],
      audit: ['TRACEABILITY', 'Aktivitäten']
    };
    const [eyebrow, title] = titleMap[view] || ['PERSONALPLANER', 'PP'];
    if ($('#eyebrow')) $('#eyebrow').textContent = eyebrow;
    if ($('#viewTitle')) $('#viewTitle').textContent = title;
    const slot = $('#warehouseQuickAction');
    if (!slot) return;
    if (view === 'dashboard' && state.me?.role === 'admin') {
      slot.innerHTML = '<button class="accent-action" onclick="openWorkerCreate()">+ Personal</button>';
    } else if (view === 'dashboard') {
      slot.innerHTML = '<button class="accent-action" onclick="setView(\'workers\')">Mein Team</button>';
    } else if (view === 'workers' && state.me?.role === 'admin') {
      slot.innerHTML = '<button class="accent-action" onclick="openWorkerCreate()">+ Zeitarbeiter</button>';
    } else {
      slot.innerHTML = '';
    }
  }

  const originalShowApp = window.showApp;
  window.showApp = function warehouseShowApp() {
    originalShowApp();
    enhanceShell();
  };

  const originalSetView = window.setView;
  window.setView = function warehouseSetView(view) {
    originalSetView(view);
    updateHeader(view);
  };

  function initials(worker) {
    return `${String(worker.first_name || '').slice(0,1)}${String(worker.last_name || '').slice(0,1)}`.toUpperCase() || 'ZA';
  }

  function workerStatus(worker) {
    if (worker.offboarding) return `<span class="chip warning">Abmeldung ${fmtDate(worker.offboarding.effective_at)}</span>`;
    return statusChip(worker.worker_status || worker.status || 'active');
  }

  window.workerTable = function warehouseWorkerTable(rows) {
    if (!rows.length) return '<div class="card empty">Keine Personen entsprechen der aktuellen Auswahl.</div>';
    return `<div class="table-wrap"><table><thead><tr><th>Person</th><th>Einsatz</th><th>Zeitarbeitsfirma</th><th>Start</th><th>Status</th><th>Aktion</th></tr></thead><tbody>${rows.map(w => {
      const workerId = w.worker_id || w.id;
      const assigned = Boolean(w.department_name);
      return `<tr>
        <td><div class="roster-person"><div class="person-avatar">${esc(initials(w))}</div><div class="person-meta"><strong>${esc(w.first_name)} ${esc(w.last_name)}</strong><small>${esc(w.employee_code || 'ohne Kennnummer')}</small></div></div></td>
        <td>${assigned ? `<span class="assignment-tag">${esc(w.department_name)}</span>` : '<span class="chip warning">Nicht zugeteilt</span>'}</td>
        <td>${esc(w.agency_name || '—')}</td>
        <td>${fmtDate(w.assigned_from || w.start_date)}</td>
        <td>${workerStatus(w)}</td>
        <td><div class="inline-actions">${assigned ? `<button class="danger" onclick="openOffboarding(${workerId})">Abmelden</button>` : ''}${state.me.role === 'admin' && !assigned ? `<button class="primary" onclick="openAssign(${workerId})">Zuteilen</button>` : ''}${state.me.role === 'admin' ? `<button class="secondary" onclick="openWorkerEdit(${workerId})">Bearbeiten</button>` : ''}</div></td>
      </tr>`;
    }).join('')}</tbody></table></div>`;
  };

  function isUpcoming(dateValue, days = 7) {
    if (!dateValue) return false;
    const target = new Date(`${String(dateValue).slice(0,10)}T12:00:00`);
    const now = new Date(); now.setHours(0,0,0,0);
    const max = new Date(now); max.setDate(max.getDate() + days);
    return target >= now && target <= max;
  }

  window.renderDashboard = function warehouseDashboard() {
    const d = state.dashboard || { counts: {}, workers: [] };
    const c = d.counts || {};
    const failed = state.offboardings.filter(o => o.status === 'mail_failed').length;
    const upcoming = state.offboardings.filter(o => o.status !== 'cancelled' && isUpcoming(o.effective_at, 7)).length;
    const unassigned = state.me.role === 'admin' ? Number(c.unassigned || 0) : 0;
    const attentionTotal = failed + upcoming + unassigned;
    const context = state.me.role === 'admin' ? (state.settings.company_site || state.settings.company_name || 'Gesamtbetrieb') : (state.me.department?.name || 'Meine Abteilung');
    const provider = state.preferences.mail_ready ? state.preferences.mail_provider_name : 'Mail nicht bereit';

    $('#view-dashboard').innerHTML = `
      <div class="ops-hero">
        <div class="ops-hero-main">
          <div class="ops-kicker">LIVE WORKFORCE · ${esc(context)}</div>
          <h2>${esc(c.workers || 0)} <span>im Einsatz</span></h2>
          <p>Direkte Sicht auf den aktuellen Personaleinsatz. PP priorisiert Abweichungen und Entscheidungen, damit im operativen Alltag zuerst das sichtbar ist, was wirklich Handlung braucht.</p>
          <div class="ops-hero-actions">
            <button class="accent-action" onclick="setView('workers')">Personal öffnen</button>
            <button class="ghost" style="color:white;border-color:rgba(255,255,255,.2)" onclick="setView('offboardings')">Abmeldungen prüfen</button>
          </div>
        </div>
        <div class="ops-hero-side">
          <div class="metric-label">Attention Queue</div>
          <div class="metric-big">${attentionTotal}</div>
          <div class="metric-note">${attentionTotal ? 'Vorgänge benötigen oder erreichen zeitnah Aufmerksamkeit.' : 'Keine akuten Vorgänge. Betrieb ist im grünen Bereich.'}</div>
          <div class="chip ${state.preferences.mail_ready ? 'success' : 'warning'}">${esc(provider)}</div>
        </div>
      </div>

      <div class="attention-strip">
        <div class="attention-item ${failed ? 'danger' : ''}" onclick="setView('offboardings')"><span class="attention-dot"></span><div><strong>Mailzustellung</strong><span>${failed ? 'Fehler müssen erneut gesendet werden' : 'Keine Versandfehler'}</span></div><b>${failed}</b></div>
        <div class="attention-item ${upcoming ? 'warning' : ''}" onclick="setView('offboardings')"><span class="attention-dot"></span><div><strong>Nächste 7 Tage</strong><span>Wirksame Abmeldungen im Zeitfenster</span></div><b>${upcoming}</b></div>
        <div class="attention-item ${unassigned ? 'warning' : ''}" onclick="setView('workers')"><span class="attention-dot"></span><div><strong>${state.me.role === 'admin' ? 'Ohne Einsatzbereich' : 'Eigene Abteilung'}</strong><span>${state.me.role === 'admin' ? 'Aktive Kräfte ohne Zuteilung' : esc(state.me.department?.name || 'Nicht zugeordnet')}</span></div><b>${state.me.role === 'admin' ? unassigned : (c.workers || 0)}</b></div>
      </div>

      <div class="grid cards">
        <div class="card stat"><div class="value">${c.workers || 0}</div><div class="label">Aktuell zugeteilt</div></div>
        <div class="card stat"><div class="value">${state.offboardings.length}</div><div class="label">Abmeldevorgänge</div></div>
        <div class="card stat"><div class="value">${c.departments || 0}</div><div class="label">${state.me.role === 'admin' ? 'Aktive Bereiche' : 'Eigener Bereich'}</div></div>
        <div class="card stat"><div class="value">${state.me.role === 'admin' ? unassigned : (state.preferences.mail_ready ? 'OK' : '!')}</div><div class="label">${state.me.role === 'admin' ? 'Unzugeteilt' : 'Kommunikation'}</div></div>
      </div>

      <div class="section-head"><div><h2>Heute im Einsatz</h2><p class="muted">Operative Besetzung, auf einen Blick.</p></div><button class="secondary" onclick="setView('workers')">Vollständiger Roster</button></div>
      ${workerTable((d.workers || []).slice(0, 8))}
    `;
  };

  function uniqueAgencies() {
    const source = state.me.role === 'admin' && state.agencies.length ? state.agencies : state.workers.map(w => ({ id: w.agency_id, name: w.agency_name }));
    const seen = new Set();
    return source.filter(a => a && a.name && !seen.has(String(a.id ?? a.name)) && seen.add(String(a.id ?? a.name)));
  }

  window.filterWarehouseWorkers = function filterWarehouseWorkers() {
    const query = String($('#workerSearch')?.value || '').trim().toLowerCase();
    const department = String($('#workerDepartmentFilter')?.value || '');
    const agency = String($('#workerAgencyFilter')?.value || '');
    const assignment = String($('#workerAssignmentFilter')?.value || 'all');
    const rows = state.workers.filter(w => {
      const hay = `${w.first_name || ''} ${w.last_name || ''} ${w.employee_code || ''} ${w.agency_name || ''} ${w.department_name || ''}`.toLowerCase();
      if (query && !hay.includes(query)) return false;
      if (department && String(w.department_id || '') !== department) return false;
      if (agency && String(w.agency_id || '') !== agency) return false;
      const assigned = Boolean(w.department_name);
      if (assignment === 'assigned' && !assigned) return false;
      if (assignment === 'unassigned' && assigned) return false;
      if (assignment === 'offboarding' && !w.offboarding) return false;
      return true;
    });
    if ($('#workerRoster')) $('#workerRoster').innerHTML = workerTable(rows);
    if ($('#workerResultCount')) $('#workerResultCount').textContent = `${rows.length} von ${state.workers.length}`;
  };

  window.renderWorkers = function warehouseWorkers() {
    const agencies = uniqueAgencies();
    $('#view-workers').innerHTML = `
      <div class="section-head"><div><h2>${state.me.role === 'admin' ? 'Workforce Roster' : 'Mein Einsatzteam'}</h2><p class="muted">Suchen, filtern und direkt handeln – ohne zwischen Unterseiten zu springen.</p></div><div class="toolbar"><span id="workerResultCount" class="chip">${state.workers.length} Personen</span>${state.me.role === 'admin' ? '<button class="primary" onclick="openWorkerCreate()">+ Zeitarbeiter</button>' : ''}</div></div>
      <div class="roster-toolbar">
        <div class="search-control"><input id="workerSearch" placeholder="Name, Kennnummer, Firma oder Bereich …" oninput="filterWarehouseWorkers()"></div>
        ${state.me.role === 'admin' ? `<select id="workerDepartmentFilter" onchange="filterWarehouseWorkers()"><option value="">Alle Bereiche</option>${state.departments.filter(d => d.active).map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select>` : '<div></div>'}
        <select id="workerAgencyFilter" onchange="filterWarehouseWorkers()"><option value="">Alle Zeitarbeitsfirmen</option>${agencies.map(a => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('')}</select>
        <select id="workerAssignmentFilter" onchange="filterWarehouseWorkers()"><option value="all">Alle Status</option><option value="assigned">Im Einsatz</option>${state.me.role === 'admin' ? '<option value="unassigned">Nicht zugeteilt</option>' : ''}<option value="offboarding">Abmeldung geplant</option></select>
      </div>
      <div id="workerRoster">${workerTable(state.workers)}</div>
    `;
  };

  window.offboardingTable = function warehouseOffboardingTable(rows) {
    if (!rows.length) return '<div class="card empty">Keine Abmeldungen in dieser Auswahl.</div>';
    return `<div class="table-wrap"><table><thead><tr><th>Person</th><th>Bereich</th><th>Wirksam</th><th>Grund</th><th>Ersatz</th><th>Kommunikation</th><th></th></tr></thead><tbody>${rows.map(o => `<tr>
      <td><div class="roster-person"><div class="person-avatar">${esc(`${String(o.first_name || '').slice(0,1)}${String(o.last_name || '').slice(0,1)}`.toUpperCase())}</div><div class="person-meta"><strong>${esc(o.first_name || `#${o.worker_id}`)} ${esc(o.last_name || '')}</strong><small>${esc(o.agency_name || '')}</small></div></div></td>
      <td><span class="assignment-tag">${esc(o.department_name || '—')}</span></td>
      <td>${fmtDate(o.effective_at)}</td>
      <td>${esc(o.reason_label || o.reason_text || '—')}</td>
      <td>${o.replacement_required ? '<span class="chip warning">Ersatz</span>' : '<span class="chip">Nein</span>'}</td>
      <td>${statusChip(o.status)}</td>
      <td>${o.status === 'mail_failed' ? `<button class="secondary" onclick="retryOffboarding(${o.id})">Erneut senden</button>` : ''}</td>
    </tr>`).join('')}</tbody></table></div>`;
  };

  window.filterWarehouseOffboardings = function filterWarehouseOffboardings() {
    const query = String($('#offboardingSearch')?.value || '').trim().toLowerCase();
    const status = String($('#offboardingStatusFilter')?.value || '');
    const rows = state.offboardings.filter(o => {
      const hay = `${o.first_name || ''} ${o.last_name || ''} ${o.agency_name || ''} ${o.department_name || ''} ${o.reason_label || ''}`.toLowerCase();
      if (query && !hay.includes(query)) return false;
      if (status && o.status !== status) return false;
      return true;
    });
    if ($('#offboardingRoster')) $('#offboardingRoster').innerHTML = offboardingTable(rows);
  };

  window.renderOffboardings = function warehouseOffboardings() {
    const sent = state.offboardings.filter(o => o.status === 'sent').length;
    const failed = state.offboardings.filter(o => o.status === 'mail_failed').length;
    const pending = state.offboardings.filter(o => o.status === 'pending').length;
    const upcoming = state.offboardings.filter(o => o.status !== 'cancelled' && isUpcoming(o.effective_at, 7)).length;
    $('#view-offboardings').innerHTML = `
      <div class="section-head"><div><h2>Abmelde-Flow</h2><p class="muted">Zeitpunkt, Ersatzbedarf und Kommunikationsstatus bleiben als ein Vorgang zusammen.</p></div></div>
      <div class="status-board">
        <div class="status-tile"><strong>${state.offboardings.length}</strong><span>Gesamt</span></div>
        <div class="status-tile"><strong>${upcoming}</strong><span>Nächste 7 Tage</span></div>
        <div class="status-tile"><strong>${sent}</strong><span>Versendet</span></div>
        <div class="status-tile"><strong>${failed + pending}</strong><span>Aufmerksamkeit</span></div>
      </div>
      <div class="roster-toolbar">
        <div class="search-control"><input id="offboardingSearch" placeholder="Person, Firma, Bereich oder Grund …" oninput="filterWarehouseOffboardings()"></div>
        <select id="offboardingStatusFilter" onchange="filterWarehouseOffboardings()"><option value="">Alle Kommunikationsstatus</option><option value="sent">Versendet</option><option value="mail_failed">Mail fehlgeschlagen</option><option value="pending">Ausstehend</option><option value="cancelled">Storniert</option></select>
      </div>
      <div id="offboardingRoster">${offboardingTable(state.offboardings)}</div>
    `;
  };

  const originalSetAdminTab = window.setAdminTab;
  window.setAdminTab = function warehouseAdminTab(tab) {
    originalSetAdminTab(tab);
  };

  const adminGroups = [
    ['Betrieb', [['system','Unternehmen'], ['departments','Abteilungen'], ['agencies','Zeitarbeitsfirmen']]],
    ['Kommunikation', [['mail','E-Mail & Microsoft 365']]],
    ['Regeln & Datenmodell', [['workflow','Abmeldeprozess'], ['reasons','Abmeldegründe'], ['fields','Zusatzfelder']]],
    ['Zugriff & Governance', [['users','Bereichsleiter'], ['security','Sicherheit & Daten']]]
  ];

  function adminContent(tab) {
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

  window.renderAdmin = function warehouseAdmin() {
    if (state.me.role !== 'admin') return;
    const rail = adminGroups.map(([group, tabs]) => `<div class="admin-rail-group">${esc(group)}</div>${tabs.map(([key,label]) => `<button class="${adminTab === key ? 'active' : ''}" onclick="setAdminTab('${key}')">${esc(label)}</button>`).join('')}`).join('');
    $('#view-admin').innerHTML = `<div class="admin-workspace"><aside class="admin-rail">${rail}</aside><div id="adminPane" class="admin-pane">${adminContent(adminTab)}</div></div>`;
    if (adminTab === 'mail') toggleMailProvider();
  };

  function actionLabel(action) {
    const labels = {
      login: 'Anmeldung',
      worker_created: 'Zeitarbeiter angelegt',
      worker_updated: 'Personaldaten geändert',
      worker_assigned: 'Personal zugeteilt',
      worker_offboarding_requested: 'Abmeldung ausgelöst',
      offboarding_mail_retried: 'Abmelde-Mail erneut gesendet',
      department_created: 'Abteilung angelegt',
      department_updated: 'Abteilung geändert',
      agency_created: 'Zeitarbeitsfirma angelegt',
      agency_updated: 'Zeitarbeitsfirma geändert',
      user_created: 'Zugang angelegt',
      user_updated: 'Zugang geändert',
      system_settings_updated: 'Systemeinstellungen geändert',
      microsoft365_connected: 'Microsoft 365 verbunden',
      microsoft365_disconnected: 'Microsoft 365 getrennt'
    };
    return labels[action] || action.replaceAll('_',' ');
  }

  window.renderAudit = async function warehouseAudit() {
    if (state.me.role !== 'admin') return;
    const rows = await api('/api/audit');
    $('#view-audit').innerHTML = `<div class="section-head"><div><h2>Audit Trail</h2><p class="muted">Chronologische Nachvollziehbarkeit aller relevanten Personal- und Systemaktionen.</p></div><span class="chip">${rows.length} Ereignisse</span></div><div class="card"><div class="audit-timeline">${rows.map(a => `<div class="audit-event"><strong>${esc(actionLabel(a.action))}</strong><span>${esc(a.user_name || 'System')} · ${esc(a.created_at)} · ${esc(a.entity_type)}${a.entity_id ? ` #${a.entity_id}` : ''}</span></div>`).join('') || '<div class="empty">Noch keine Aktivitäten.</div>'}</div></div>`;
  };

  const query = new URLSearchParams(location.search);
  if (query.has('m365')) adminTab = 'mail';
})();
