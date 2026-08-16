// ============================================================================
// MAIN APPLICATION & SOCKET ROUTING (main.js)
// ============================================================================

window.AppState = window.AppState || {};
window.AppState.cpuHistory = window.AppState.cpuHistory || [];
window.AppState.memHistory = window.AppState.memHistory || [];
window.AppState.coreStructureSignature = window.AppState.coreStructureSignature || '';

window.getCurrentUserRole = function () {
  const currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  const rawRole = String((currentUser && currentUser.role) || '').trim();
  return (rawRole || '').replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
};

window.userMayMutateServices = function () {
  const role = window.getCurrentUserRole();
  return role === 'platform_admin' || role === 'tenant_admin';
};

window.applyTheme = function (themeName) {
  const normalized = (themeName === 'light') ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', normalized);
  if (window.AppState && window.AppState.settings) {
    window.AppState.settings.theme = normalized;
  }
};

window.toggleTheme = function () {
  const current = (window.AppState && window.AppState.settings && window.AppState.settings.theme) || 'dark';
  const nextTheme = current === 'dark' ? 'light' : 'dark';
  if (typeof window.setSetting === 'function') {
    window.setSetting('theme', nextTheme);
  } else {
    window.applyTheme(nextTheme);
  }
};

window.logoutCurrentUser = async function () {
  try {
    const response = await fetch('/api/logout', { method: 'POST' });
    if (response.ok) {
      window.location.href = '/';
      return;
    }
    window.logToTerminal && window.logToTerminal('AUTH', 'Logout failed.', 'text-red-500 font-bold');
  } catch (error) {
    window.logToTerminal && window.logToTerminal('AUTH', 'Logout failed.', 'text-red-500 font-bold');
  }
};

window.applyTheme((window.AppState && window.AppState.settings && window.AppState.settings.theme) || 'dark');

function getCoreStructureSignature(services) {
  return services
    .filter(s => !s.name.startsWith('amr-service-'))
    .map(s => `${s.name}|${s.status}|${s.port || ''}`)
    .join('||');
}

const PM2_FIELD_DEFS = {
  uptime: { label: 'UPTIME' },
  restarts: { label: '↺' },
  user: { label: 'USER' },
  watching: { label: 'WATCH', format: (value) => (value ? 'ON' : 'OFF') },
  pid: { label: 'PID' },
  namespace: { label: 'NS' },
  mode: { label: 'MODE' },
  version: { label: 'VERSION' },
};

function buildPm2MetadataRows(service, colorBase) {
  if (!service) return '';

  const rows = Object.entries(PM2_FIELD_DEFS)
    .filter(([key]) => key in service && service[key] !== undefined && service[key] !== null && service[key] !== '')
    .map(([key, def]) => {
      const value = def.format ? def.format(service[key]) : service[key];
      return `
        <div class="flex justify-between gap-2 text-[8px] text-${colorBase}-600" data-role="pm2-field" data-field="${key}">
          <span>${def.label}</span>
          <span class="text-${colorBase}-400 text-right">${String(value)}</span>
        </div>
      `;
    })
    .join('');

  if (!rows) return '';
  return `<div class="mt-2 pt-2 border-t border-${colorBase}-900/40 space-y-1" data-role="pm2-field-list">${rows}</div>`;
}

function syncCoreCardsInPlace(coreContainer, services) {
  const cards = Array.from(coreContainer.querySelectorAll('[data-core-card="1"]'));
  const coreServices = services.filter(s => !s.name.startsWith('amr-service-'));

  if (cards.length !== coreServices.length) return false;

  const cardByName = new Map();
  cards.forEach(card => {
    const name = card.getAttribute('data-service-name');
    if (name) cardByName.set(name, card);
  });

  for (const srv of coreServices) {
    const card = cardByName.get(srv.name);
    if (!card) return false;

    const isOnline = srv.status === 'online';
    const isRemoved = srv.status === 'removed';
    const colorBase = isOnline ? 'cyan' : 'red';
    const statusClass = isOnline ? `text-${colorBase}-300` : 'text-red-500 bg-red-950/30';
    const cpuWidth = Math.min((parseFloat(srv.cpu) || 0) * 2, 100);
    const isLogging = (window.AppState.activeLogService === srv.name);
    const logBtnText = isLogging ? 'STOP LOGS' : 'LOGS';
    const logBtnClass = isLogging
      ? `bg-${colorBase}-900/60 text-${colorBase}-300 border-${colorBase}-500 font-bold`
      : `bg-black hover:bg-${colorBase}-900/50 text-${colorBase}-600 border-${colorBase}-900 hover:border-${colorBase}-500`;

    if (isRemoved) {
      // Removed-state cards are structural outliers and should be rebuilt by caller.
      return false;
    }

    const statusEl = card.querySelector('[data-role="status-badge"]');
    if (statusEl) {
      statusEl.textContent = srv.status;
      statusEl.className = `text-[9px] ${statusClass} border border-${colorBase}-800/50 px-1.5 uppercase shrink-0`;
    }

    const cpuBarEl = card.querySelector('[data-role="cpu-bar"]');
    if (cpuBarEl) cpuBarEl.style.width = `${cpuWidth}%`;

    const cpuValEl = card.querySelector('[data-role="cpu-val"]');
    if (cpuValEl) cpuValEl.textContent = `${srv.cpu}%`;

    const memValEl = card.querySelector('[data-role="mem-val"]');
    if (memValEl) memValEl.textContent = srv.memory;

    const metadataEl = card.querySelector('[data-role="pm2-field-list"]');
    if (metadataEl) {
      metadataEl.outerHTML = buildPm2MetadataRows(srv, colorBase);
    }

    const logBtnEl = card.querySelector('[data-role="log-btn"]');
    if (logBtnEl) {
      logBtnEl.textContent = logBtnText;
      logBtnEl.className = `btn-ui flex-1 transition-all text-[9px] py-1 border ${logBtnClass}`;
    }
  }

  return true;
}

// Connect to the local server
const socketPath = (window.APP_CONFIG && window.APP_CONFIG.SOCKET_PATH) || '/jarvis.io';
const assistantLogLabel = (window.APP_CONFIG && window.APP_CONFIG.ASSISTANT_LOG_LABEL) || 'QUASON';
window.AppState.socket = io({ path: socketPath, upgrade: true, rememberUpgrade: true });
const socket = window.AppState.socket;

socket.on('connect', () => {
  if (typeof window.renderSettingsUI === 'function') window.renderSettingsUI();

  window.logToTerminal('SYS', 'Telemetry handshake verified. Link stable.', 'text-emerald-400');
  const wsBadge = document.getElementById('status-ws');
  if (wsBadge) {
    wsBadge.className = 'status-chip-up border px-2 py-0.5 font-bold';
    wsBadge.textContent = 'WS: CONN';
  }
});

socket.on('disconnect', () => {
  window.logToTerminal('SYS', 'WebSocket connection lost. Awaiting automatic reconnect...', 'text-red-500 font-bold');
  const wsBadge = document.getElementById('status-ws');
  if (wsBadge) {
    wsBadge.className = 'status-chip-down border px-2 py-0.5 font-bold animate-pulse';
    wsBadge.textContent = 'WS: DROP';
  }
});

// FORM BINDING
document.getElementById('command-form')?.addEventListener('submit', (e) => {
  e.preventDefault();
  const input = document.getElementById('command-input');
  if (!input) return;

  const cmd = input.value.trim();
  if (!cmd) return;

  window.logToTerminal('USER_INPUT', cmd, 'text-white font-bold');
  socket.emit('ui_command', { command: cmd });
  input.value = '';
});

// LOG LISTENERS
socket.on('log_stream', (data) => {
  window.logToTerminal(data.source || assistantLogLabel, data.message, data.color || 'text-cyan-200');
  if (data.source === assistantLogLabel && typeof window.speakBrowserResponse === 'function') {
    window.speakBrowserResponse(data.message);
  }
});

socket.on('service_log_chunk', (data) => {
  if (data.service !== window.AppState.activeLogService) return;
  const stream = document.getElementById('service-log-stream');
  if (!stream) return;

  const entry = document.createElement('div');
  let color = 'text-cyan-300';
  const textLower = data.log.toLowerCase();

  if (textLower.includes('error') || textLower.includes('fail') || textLower.includes('exception')) color = 'text-red-400 font-bold bg-red-950/20';
  else if (textLower.includes('warn')) color = 'text-amber-300';
  else if (textLower.includes('info') || textLower.includes('success')) color = 'text-emerald-300';
  else if (textLower.includes('debug')) color = 'text-cyan-600';

  entry.className = `border-b border-cyan-900/20 py-0.5 last:border-0 ${color}`;
  entry.textContent = data.log;
  stream.appendChild(entry);
  stream.scrollTop = stream.scrollHeight;
});

// TELEMETRY ENGINE
socket.on('pm2_telemetry', (data) => {
  const services = data.services || [];
  const host = data.host;
  const coreContainer = document.getElementById('core-services-container');
  const amrContainer = document.getElementById('amr-services-container');
  if (!coreContainer || !amrContainer) return;

  // Clear AMR container immediately
  amrContainer.innerHTML = '';

  let coreCount = 0, coreOnline = 0, amrTotal = 0, amrOnline = 0, aggCpu = 0, aggMem = 0;
  let coreCardsElements = [];

  const coreStructureSignature = getCoreStructureSignature(services);
  const hasCoreStructureChanged = window.AppState.coreStructureSignature !== coreStructureSignature;
  const openMoreMenu = coreContainer.querySelector('details[data-more-menu][open]');
  const openMoreService = openMoreMenu ? openMoreMenu.getAttribute('data-service-name') : null;

  services.forEach(srv => {
    const isRemoved = srv.status === 'removed';
    const isOnline = srv.status === 'online';
    const isAMR = srv.name.startsWith('amr-service-');

    let colorBase = isOnline ? (isAMR ? 'emerald' : 'cyan') : 'red';
    let statusClass = isOnline ? `text-${colorBase}-300` : 'text-red-500 bg-red-950/30';

    if (!isRemoved) {
      aggCpu += parseFloat(srv.cpu) || 0;
      aggMem += parseInt(srv.memory.replace('MB', '')) || 0;
    }

    let displayName = srv.name;
    let subText = `PORT // ${srv.port || 'UNK'}`;

    if (isAMR) {
      const parts = srv.name.replace('amr-service-', '').split('-');
      displayName = parts[0] || 'UNK';
      subText = `SERIAL: ${parts[1] || 'UNK'}`;
      if (!isRemoved) { amrTotal++; if (isOnline) amrOnline++; }
    } else {
      coreCount++;
      if (isOnline) coreOnline++;
    }

    const card = document.createElement('div');

    if (isRemoved) {
      card.className = `flex flex-col p-2 bg-red-950/10 border border-red-900/40 border-dashed mb-1 opacity-80 shrink-0`;
      card.innerHTML = `
                <div class="flex justify-between items-start mb-1">
                    <span class="text-[12px] font-bold text-zinc-500 uppercase tracking-wide truncate pr-2">${displayName} <span class="text-red-500/70 ml-1 text-[9px] tracking-widest">(NOT ACTIVE)</span></span>
                    <span class="text-[9px] text-red-500 bg-red-950/30 border border-red-800/50 px-1.5 uppercase shrink-0">REMOVED</span>
                </div>
                <div class="text-[9px] text-zinc-500/80 mb-3 italic leading-relaxed">This service was previously removed. You can restore it or clear its old logs.</div>
                <div class="flex gap-1 pt-2 border-t border-red-900/30">
                  <button onclick="serviceAction('start', '${srv.name}')" class="btn-ui btn-ui-emerald flex-[2] text-[9px] py-1 font-bold tracking-widest">RESTORE SERVICE</button>
                  <button onclick="serviceAction('flush', '${srv.name}')" class="btn-ui btn-ui-zinc flex-1 text-[9px] py-1">CLEAR LOGS</button>
                </div>
            `;
      if (isAMR) amrContainer.appendChild(card);
      else coreCardsElements.push(card);
      return;
    }

    const cpuWidth = Math.min(srv.cpu * 2, 100);
    const isLogging = (window.AppState.activeLogService === srv.name);
    const logBtnText = isLogging ? 'STOP LOGS' : 'LOGS';
    const logBtnClass = isLogging
      ? `bg-${colorBase}-900/60 text-${colorBase}-300 border-${colorBase}-500 font-bold`
      : `bg-black hover:bg-${colorBase}-900/50 text-${colorBase}-600 border-${colorBase}-900 hover:border-${colorBase}-500`;

    const canMutateServices = window.userMayMutateServices();
    const moreItemsHTML = canMutateServices
      ? (isOnline
        ? `<button onclick="promptStopService('${srv.name}')" class="btn-ui btn-ui-amber text-left text-[9px] py-1 px-2">STOP</button><button onclick="serviceAction('flush', '${srv.name}')" class="btn-ui btn-ui-zinc text-left text-[9px] py-1 px-2">CLEAR LOGS</button><button onclick="promptRemoveService('${srv.name}')" class="btn-ui btn-ui-red text-left text-[9px] py-1 px-2">REMOVE</button>`
        : `<button onclick="serviceAction('flush', '${srv.name}')" class="btn-ui btn-ui-zinc text-left text-[9px] py-1 px-2">CLEAR LOGS</button><button onclick="promptRemoveService('${srv.name}')" class="btn-ui btn-ui-red text-left text-[9px] py-1 px-2">REMOVE</button>`)
      : `<button onclick="serviceAction('flush', '${srv.name}')" class="btn-ui btn-ui-zinc text-left text-[9px] py-1 px-2">VIEW LOGS</button>`;

    const moreMenuHTML = `<details class="group relative" data-more-menu data-service-name="${srv.name}"><summary class="btn-ui btn-ui-zinc list-none select-none p-1" title="More Actions"><svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg></summary><div class="absolute right-0 mt-1 min-w-[132px] z-20 bg-black border border-cyan-900/60 shadow-[0_8px_24px_rgba(0,0,0,0.45)] p-1 flex flex-col gap-1">${moreItemsHTML}</div></details>`;

    const controlsHTML = canMutateServices
      ? (isOnline
        ? `<div class="flex gap-1"><button onclick="serviceAction('restart', '${srv.name}')" class="btn-ui btn-ui-cyan flex-1 text-[9px] py-1 font-bold tracking-widest">RESTART</button><button data-role="log-btn" onclick="serviceAction('log', '${srv.name}')" class="btn-ui flex-1 transition-all text-[9px] py-1 border ${logBtnClass}">${logBtnText}</button></div>`
        : `<div class="flex gap-1"><button onclick="serviceAction('restart', '${srv.name}')" class="btn-ui btn-ui-emerald flex-1 text-[9px] py-1 font-bold tracking-widest">RESTART</button><button data-role="log-btn" onclick="serviceAction('log', '${srv.name}')" class="btn-ui flex-1 transition-all text-[9px] py-1 border ${logBtnClass}">${logBtnText}</button></div>`)
      : `<div class="flex gap-1"><button data-role="log-btn" onclick="serviceAction('log', '${srv.name}')" class="btn-ui flex-1 transition-all text-[9px] py-1 border ${logBtnClass}">${logBtnText}</button></div>`;

    card.className = `flex flex-col p-2 bg-${colorBase}-950/10 border border-${colorBase}-900/40 mb-1 hover:border-${colorBase}-500/50 transition-colors shrink-0`;
    card.setAttribute('data-core-card', '1');
    card.setAttribute('data-service-name', srv.name);
    const metadataHTML = buildPm2MetadataRows(srv, colorBase);
    card.innerHTML = `
            <div class="flex justify-between items-start mb-1">
          <span class="text-[12px] font-bold text-${colorBase}-400 uppercase tracking-wide truncate pr-2">${displayName}</span>
          <div class="flex items-center gap-1 shrink-0">
            <span data-role="status-badge" class="text-[9px] ${statusClass} border border-${colorBase}-800/50 px-1.5 uppercase shrink-0">${srv.status}</span>
            ${moreMenuHTML}
          </div>
            </div>
            <div class="text-[9px] text-${colorBase}-600/80 mb-2">${subText}</div>
            <div class="flex items-center gap-2 text-[9px] text-${colorBase}-500">
                <span class="w-8">CPU</span>
                <div class="flex-1 h-1.5 bg-${colorBase}-950 border border-${colorBase}-900 relative">
            <div data-role="cpu-bar" class="absolute left-0 top-0 h-full bg-${colorBase}-500 transition-all" style="width: ${cpuWidth}%"></div>
                </div>
          <span data-role="cpu-val" class="w-8 text-right">${srv.cpu}%</span>
            </div>
            <div class="flex justify-between mt-1 text-[9px] text-${colorBase}-600">
                <span>MEM_USAGE</span>
          <span data-role="mem-val" class="text-${colorBase}-400">${srv.memory}</span>
            </div>
            ${metadataHTML}
            <div class="mt-2 pt-2 border-t border-${colorBase}-900/40 flex flex-col">
                ${controlsHTML}
            </div>
        `;

    if (isAMR) amrContainer.appendChild(card);
    else coreCardsElements.push(card);
  });

  if (coreCardsElements.length === 0) {
    coreContainer.innerHTML = `
            <div class="flex flex-col items-center justify-center p-6 text-center h-full border border-dashed border-cyan-900/40 bg-cyan-950/20 gap-3">
                <div class="text-cyan-700/80 mb-1">
                   <svg class="w-8 h-8 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"></path></svg>
                </div>
                <h3 class="text-xs font-bold tracking-[0.2em] text-cyan-500 uppercase">No Core Services Available</h3>
                <p class="text-[9px] text-cyan-600 leading-relaxed max-w-[90%]">All Core PM2 services have been removed or are currently unavailable.<br><br>Start or restore the default Core Infrastructure services required for system operation.</p>
                <button onclick="socket.emit('ui_command', { command: 'start all' })" class="btn-ui btn-ui-cyan mt-3 px-5 py-2 text-[10px] font-bold tracking-[0.2em]">START ALL CORE SERVICES</button>
            </div>
        `;
    window.AppState.coreStructureSignature = coreStructureSignature;
  } else {
    const canSyncInPlace = !hasCoreStructureChanged && syncCoreCardsInPlace(coreContainer, services);

    if (!canSyncInPlace) {
      coreContainer.innerHTML = '';
      coreCardsElements.forEach(card => coreContainer.appendChild(card));

      if (openMoreService) {
        const detailsToReopen = coreContainer.querySelector(`details[data-more-menu][data-service-name="${openMoreService}"]`);
        if (detailsToReopen) detailsToReopen.setAttribute('open', 'open');
      }
    }

    window.AppState.coreStructureSignature = coreStructureSignature;
  }

  const amrHeader = document.getElementById('amr-count-header');
  if (amrHeader) amrHeader.textContent = `(${amrTotal})`;

  if (amrTotal !== window.AppState.prevAmrTotal) {
    if (amrTotal === 0 && window.AppState.isAmrPanelOpen) window.toggleAmrPanel(false);
    else if (amrTotal > 0 && !window.AppState.isAmrPanelOpen) window.toggleAmrPanel(true);
    window.AppState.prevAmrTotal = amrTotal;
  }

  if (amrTotal === 0 && window.AppState.isAmrPanelOpen) {
    amrContainer.innerHTML = `
            <div class="flex flex-col items-center justify-center p-4 text-center h-full border border-dashed border-emerald-900/30 bg-emerald-950/5">
                <span class="text-[9px] tracking-widest text-emerald-700 uppercase">No Virtual AMRs Active</span>
            </div>
        `;
  }

  window.setCircleData('circ-cpu', 'val-cpu', Math.round(aggCpu), 100, '%', 'text-cyan-400');
  window.setCircleData('circ-mem', 'val-mem', aggMem, 4096, 'M', 'text-cyan-400');

  // SYSTEM METRICS FIX: Fallback gracefully to aggregated PM2 data if Python host poller is unavailable
  const MAX_SAMPLES = 90;
  let plotCpu = (host && host.cpu !== undefined) ? host.cpu : aggCpu;
  let plotMem = (host && host.ram !== undefined) ? host.ram : Math.min((aggMem / 4096) * 100, 100);

  window.AppState.cpuHistory.push(plotCpu);
  window.AppState.memHistory.push(plotMem);

  if (window.AppState.cpuHistory.length > MAX_SAMPLES) window.AppState.cpuHistory.shift();
  if (window.AppState.memHistory.length > MAX_SAMPLES) window.AppState.memHistory.shift();

  const cpuValEl = document.getElementById('metric-cpu-val');
  if (cpuValEl) cpuValEl.textContent = `${plotCpu.toFixed(1)}%`;
  const memValEl = document.getElementById('metric-mem-val');
  if (memValEl) memValEl.textContent = `${plotMem.toFixed(1)}%`;

  window.drawMetricGraph('chart-cpu', window.AppState.cpuHistory, 100, '34, 211, 238');
  window.drawMetricGraph('chart-mem', window.AppState.memHistory, 100, '52, 211, 153');

  const coreColor = (coreOnline === coreCount && coreCount > 0) ? "text-cyan-400" : "text-red-500";
  window.setCircleData('circ-core', 'val-core', coreOnline, coreCount, `/${coreCount}`, coreColor);

  const amrColor = (amrOnline === amrTotal && amrTotal > 0) ? "text-emerald-400" : "text-red-500";
  window.setCircleData('circ-amr', 'val-amr', amrOnline, amrTotal, `/${amrTotal}`, amrColor);

  const healthEl = document.getElementById('stat-sys-health');
  if (healthEl) {
    if (coreCount === 0 && amrTotal === 0) {
      healthEl.textContent = "AWAITING TELEMETRY";
      healthEl.className = "font-bold tracking-widest text-cyan-600";
    } else if (coreOnline < coreCount || amrOnline < amrTotal) {
      healthEl.textContent = "SYSTEM DEGRADED";
      healthEl.className = "font-bold tracking-widest text-red-500";
    } else {
      healthEl.textContent = "SYSTEM OPTIMAL";
      healthEl.className = "font-bold tracking-widest text-emerald-400";
    }
  }
});

socket.on('log_stream_intent', (data) => {
  if (data && data.service) {
    window.toggleLogs(data.service);
  }
});

// --- PROJECT REGISTRY LISTENERS ---
socket.on('projects_list', (projects) => {
  window.renderProjectsList(projects);
});

socket.on('folder_listing', (data) => {
  window.renderFolderListing(data);
});

socket.on('project_preferences', (prefs) => {
  if (typeof window.renderProjectPreferences === 'function') {
    window.renderProjectPreferences(prefs || {});
  }
});

socket.on('project_op_result', (result) => {
  if (!result) return;
  if (result.action === 'add') {
    if (result.ok) {
      window.closeAddProjectForm();
      window.logToTerminal('PROJECTS', 'Project registered. New service card will appear shortly.', 'text-emerald-400 font-bold');
    } else {
      window.showProjectFormError((result.error || 'UNKNOWN ERROR').toUpperCase());
    }
  } else if (result.action === 'remove' && !result.ok) {
    window.logToTerminal('PROJECTS', result.error || 'Remove failed.', 'text-red-400 font-bold');
  } else if (result.action === 'set_core_path') {
    if (result.ok) {
      window.showCorePathError(null);
      window.logToTerminal('PROJECTS', 'Core Project Path updated successfully.', 'text-emerald-400 font-bold');
    } else {
      window.showCorePathError((result.error || 'FAILED TO SET CORE PROJECT PATH').toUpperCase());
    }
  } else if (result.action === 'update') {
    if (result.ok) {
      window.closeEditProjectForm();
      window.logToTerminal('PROJECTS', 'Project updated successfully.', 'text-emerald-400 font-bold');
    } else {
      const errEl = document.getElementById('edit-proj-error');
      if (errEl) {
        errEl.textContent = (result.error || 'PROJECT UPDATE FAILED').toUpperCase();
        errEl.classList.remove('hidden');
      }
    }
  } else if (result.action === 'move_core') {
    if (result.ok) {
      window.logToTerminal('PROJECTS', 'Project moved to Core Project Path.', 'text-emerald-400 font-bold');
    } else {
      window.logToTerminal('PROJECTS', (result.error || 'Move failed.'), 'text-red-400 font-bold');
    }
  } else if (result.action === 'delete_core') {
    if (result.ok) {
      window.logToTerminal('PROJECTS', 'Project deleted from Core Project Path and registry.', 'text-emerald-400 font-bold');
    } else {
      window.logToTerminal('PROJECTS', (result.error || 'Delete failed.'), 'text-red-400 font-bold');
    }
  }
});

socket.on('project_start_result', (result) => {
  if (!result) return;

  const serviceName = (result.target || 'service').toString();
  if (result.ok) {
    window.logToTerminal('PROJECTS', `Start succeeded for ${serviceName}.`, 'text-emerald-400 font-bold');
  } else {
    const msg = (result.message || 'Startup failed.').toString();
    window.logToTerminal('PROJECTS', `Start failed for ${serviceName}: ${msg}`, 'text-red-400 font-bold');
  }

  window.AppState.socket?.emit('get_projects');
});

// --- LISTEN FOR JARVIS VOICE EMISSIONS FROM BACKEND ---
socket.on('jarvis_speech', (data) => {
  if (data && data.text) {
    if (typeof window.logToTerminal === 'function') {
      window.logToTerminal(assistantLogLabel, data.text, 'text-emerald-400 font-bold');
    }
    if (typeof window.speakBrowserResponse === 'function') {
      window.speakBrowserResponse(data.text);
    }
  }
});

// --- PRIME SYSTEM METRICS GRAPHS ON LOAD ---
window.drawMetricGraph('chart-cpu', window.AppState.cpuHistory, 100, '34, 211, 238');
window.drawMetricGraph('chart-mem', window.AppState.memHistory, 100, '52, 211, 153');