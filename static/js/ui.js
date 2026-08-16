// ============================================================================
// UI RENDERING & DOM MANIPULATION (ui.js)
// ============================================================================

// --- CLOCK & UPTIME ---
function updateClock() {
  const now = new Date();
  const clockEl = document.getElementById('digital-clock');
  if (clockEl) clockEl.textContent = now.toLocaleTimeString('en-US', { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

setInterval(() => {
  window.AppState.sessionSeconds++;
  const h = Math.floor(window.AppState.sessionSeconds / 3600).toString().padStart(2, '0');
  const m = Math.floor((window.AppState.sessionSeconds % 3600) / 60).toString().padStart(2, '0');
  const s = (window.AppState.sessionSeconds % 60).toString().padStart(2, '0');
  const uptimeEl = document.getElementById('sys-uptime');
  if (uptimeEl) uptimeEl.textContent = `${h}:${m}:${s}`;
}, 1000);

// --- TERMINAL LOGGER ---
window.logToTerminal = function (source, message, colorClass) {
  const stream = document.getElementById('terminal-stream');
  if (!stream) return;
  const entry = document.createElement('div');
  entry.className = `break-all ${colorClass} py-0.5 border-b border-cyan-900/20 last:border-0`;
  entry.innerHTML = `<span class="opacity-50 mr-2 text-[10px]">▪</span><span class="text-cyan-700 w-20 inline-block font-bold">[${source}]</span> ${message}`;
  stream.appendChild(entry);
  stream.scrollTop = stream.scrollHeight;
};

// --- MODALS & PANELS ---

// 1. REMOVE MODAL
window.promptRemoveService = function (serviceName) {
  window.AppState.serviceToRemove = serviceName;
  const target = document.getElementById('remove-target-name');
  if (target) target.textContent = serviceName;
  document.getElementById('remove-modal')?.classList.remove('hidden');
};

window.closeRemoveModal = function () {
  window.AppState.serviceToRemove = null;
  document.getElementById('remove-modal')?.classList.add('hidden');
};

window.confirmRemoveService = function () {
  if (window.AppState.serviceToRemove && window.AppState.socket) {
    window.logToTerminal('UI_OVERRIDE', `Initiating REMOVE sequence for ${window.AppState.serviceToRemove}`, 'text-red-500 font-bold');
    window.AppState.socket.emit('ui_command', { command: `delete ${window.AppState.serviceToRemove}` });
    window.closeRemoveModal();
  }
};

// 2. STOP MODAL (ISSUE 2 FIX)
window.promptStopService = function (serviceName) {
  window.AppState.serviceToStop = serviceName;
  const target = document.getElementById('stop-target-name');
  if (target) target.textContent = serviceName;
  document.getElementById('stop-modal')?.classList.remove('hidden');
};

window.closeStopModal = function () {
  window.AppState.serviceToStop = null;
  document.getElementById('stop-modal')?.classList.add('hidden');
};

window.confirmStopService = function () {
  if (window.AppState.serviceToStop && window.AppState.socket) {
    window.logToTerminal('UI_OVERRIDE', `Initiating STOP sequence for ${window.AppState.serviceToStop}`, 'text-amber-500 font-bold');
    window.AppState.socket.emit('ui_command', { command: `stop ${window.AppState.serviceToStop}` });
    window.closeStopModal();
  }
};

window.openShutdownModal = function () {
  document.getElementById('shutdown-modal')?.classList.remove('hidden');
};

window.closeShutdownModal = function () {
  document.getElementById('shutdown-modal')?.classList.add('hidden');
};

window.confirmShutdown = function () {
  window.logToTerminal('UI_OVERRIDE', 'SYSTEM SHUTDOWN initiated. Terminating core application...', 'text-red-500 font-bold');
  // volatile = not buffered; disconnect immediately so socket.io never replays this event on reconnect
  window.AppState.socket?.volatile.emit('shutdown_app');
  window.AppState.socket?.disconnect();
  window.closeShutdownModal();
};

window.toggleLogPanel = function () {
  window.AppState.isLogPanelOpen = !window.AppState.isLogPanelOpen;
  const panel = document.getElementById('dedicated-log-panel');
  const icon = document.getElementById('log-toggle-icon');
  if (panel) {
    panel.classList.toggle('hidden', !window.AppState.isLogPanelOpen);
    panel.classList.toggle('flex', window.AppState.isLogPanelOpen);
  }
  if (icon) icon.textContent = window.AppState.isLogPanelOpen ? '[-]' : '[+]';
};

window.toggleAmrPanel = function (forceState = null) {
  window.AppState.isAmrPanelOpen = forceState !== null ? forceState : !window.AppState.isAmrPanelOpen;
  document.getElementById('amr-services-container')?.classList.toggle('hidden', !window.AppState.isAmrPanelOpen);
  document.getElementById('amr-panel')?.classList.toggle('flex-1', window.AppState.isAmrPanelOpen);
  const icon = document.getElementById('amr-toggle-icon');
  if (icon) icon.textContent = window.AppState.isAmrPanelOpen ? '[-]' : '[+]';
};

window.toggleConsolePanel = function (forceState = null) {
  window.AppState.isConsolePanelOpen = forceState !== null ? forceState : !window.AppState.isConsolePanelOpen;
  const open = window.AppState.isConsolePanelOpen;
  // The command form stays visible in both states; only the event stream collapses
  document.getElementById('terminal-stream')?.classList.toggle('hidden', !open);
  document.getElementById('console-panel')?.classList.toggle('flex-1', open);
  const icon = document.getElementById('console-toggle-icon');
  if (icon) icon.textContent = open ? '[-]' : '[+]';
};

window.drawMetricGraph = function (canvasId, history, maxValue, strokeRgb) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  // Match the canvas buffer to its CSS box so panel resize/collapse reflows correctly
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (w === 0 || h === 0) return;
  canvas.width = w;
  canvas.height = h;

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, h);

  // Faint horizontal grid lines
  ctx.strokeStyle = `rgba(${strokeRgb}, 0.12)`;
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const y = (h / 4) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  if (!history || history.length === 0) return;
  // A single sample still renders as a flat line so the graph is visible from the first tick
  const points = history.length === 1 ? [history[0], history[0]] : history;

  const stepX = w / (points.length - 1);
  const pad = 2;
  const toY = (v) => h - pad - (Math.min(v, maxValue) / maxValue) * (h - pad * 2);

  // Filled area under the line
  ctx.beginPath();
  ctx.moveTo(0, h);
  points.forEach((v, i) => ctx.lineTo(i * stepX, toY(v)));
  ctx.lineTo((points.length - 1) * stepX, h);
  ctx.closePath();
  ctx.fillStyle = `rgba(${strokeRgb}, 0.10)`;
  ctx.fill();

  // Polyline
  ctx.beginPath();
  points.forEach((v, i) => {
    const x = i * stepX, y = toY(v);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.strokeStyle = `rgba(${strokeRgb}, 0.9)`;
  ctx.lineWidth = 1.5;
  ctx.stroke();
};

window.toggleSettingsModal = function () {
  if (typeof window.renderSettingsUI === 'function') window.renderSettingsUI();
  document.getElementById('settings-modal')?.classList.toggle('hidden');
};

function normalizeRoleName(role) {
  return String(role || '').trim().replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
}

window.applyRoleBasedAccess = function () {
  const currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  const normalizedRole = normalizeRoleName(currentUser && currentUser.role);
  const isPlatformAdmin = normalizedRole === 'platform_admin' || normalizedRole === 'admin';
  const isTenantUser = !!(currentUser && currentUser.tenant_id) && !isPlatformAdmin;
  const isTenantAdmin = normalizedRole === 'tenant_admin' || normalizedRole === 'tenant_user_admin';

  const tenantButton = document.getElementById('tenant-registration-button');
  if (tenantButton) {
    tenantButton.style.display = isPlatformAdmin ? '' : 'none';
    tenantButton.disabled = !isPlatformAdmin;
  }

  const coreInput = document.getElementById('core-project-path');
  const coreBrowseButton = document.getElementById('core-project-browse-button');
  const coreSaveButton = document.getElementById('core-project-save-button');
  const coreActions = document.getElementById('core-project-path-actions');
  const canManageCorePath = isPlatformAdmin;

  if (coreInput) {
    coreInput.readOnly = !canManageCorePath;
    coreInput.disabled = !canManageCorePath;
    coreInput.classList.toggle('opacity-60', !canManageCorePath);
    coreInput.title = canManageCorePath ? 'Platform admin can manage the core project path.' : 'Tenant users must use the platform-assigned core project path.';
  }
  if (coreActions) {
    coreActions.hidden = !canManageCorePath;
    coreActions.style.display = canManageCorePath ? '' : 'none';
    coreActions.style.pointerEvents = canManageCorePath ? 'auto' : 'none';
    coreActions.setAttribute('aria-hidden', String(!canManageCorePath));
  }
  if (coreBrowseButton) {
    coreBrowseButton.disabled = !canManageCorePath;
    coreBrowseButton.hidden = !canManageCorePath;
    coreBrowseButton.setAttribute('aria-disabled', String(!canManageCorePath));
    coreBrowseButton.style.pointerEvents = canManageCorePath ? 'auto' : 'none';
    coreBrowseButton.classList.toggle('opacity-50', !canManageCorePath);
    coreBrowseButton.style.display = canManageCorePath ? '' : 'none';
  }
  if (coreSaveButton) {
    coreSaveButton.disabled = !canManageCorePath;
    coreSaveButton.hidden = !canManageCorePath;
    coreSaveButton.setAttribute('aria-disabled', String(!canManageCorePath));
    coreSaveButton.style.pointerEvents = canManageCorePath ? 'auto' : 'none';
    coreSaveButton.classList.toggle('opacity-50', !canManageCorePath);
    coreSaveButton.style.display = canManageCorePath ? '' : 'none';
  }

  const sourceMode = document.getElementById('proj-source-mode');
  if (sourceMode) {
    const hostOption = Array.from(sourceMode.options).find((opt) => opt.value === 'host');
    if (hostOption) {
      hostOption.disabled = isTenantUser;
      hostOption.hidden = isTenantUser;
    }
    if (isTenantUser || isTenantAdmin) {
      sourceMode.value = 'upload';
    }
  }

  const saveMode = document.getElementById('proj-save-mode');
  if (saveMode) {
    const customOption = Array.from(saveMode.options).find((opt) => opt.value === 'custom');
    if (customOption) customOption.disabled = isTenantUser || isTenantAdmin;
    const currentOption = Array.from(saveMode.options).find((opt) => opt.value === 'current');
    if (currentOption) currentOption.disabled = isTenantUser || isTenantAdmin;
    if (isTenantUser || isTenantAdmin) {
      saveMode.value = 'core';
    }
  }

  const addProjectButton = document.getElementById('btn-open-add-project');
  if (addProjectButton) {
    addProjectButton.style.display = (isPlatformAdmin || isTenantAdmin) ? '' : 'none';
    addProjectButton.disabled = !(isPlatformAdmin || isTenantAdmin);
  }

  const projPathRow = document.getElementById('proj-path-row');
  if (projPathRow) {
    const showPathRow = isPlatformAdmin && (sourceMode && sourceMode.value === 'host');
    projPathRow.classList.toggle('hidden', !showPathRow);
    projPathRow.classList.toggle('flex', showPathRow);
  }

  window.onProjectSourceModeChanged?.();
};

window.refreshCurrentUserSession = async function () {
  try {
    const response = await fetch('/api/session', { cache: 'no-store' });
    if (!response.ok) {
      window.AppState = window.AppState || {};
      window.AppState.currentUser = null;
      window.applyRoleBasedAccess();
      return;
    }
    const payload = await response.json();
    window.AppState = window.AppState || {};
    window.AppState.currentUser = payload && payload.user ? payload.user : null;
    window.applyRoleBasedAccess();
    if (window.AppState.currentUser && window.AppState.currentUser.role) {
      const normalized = String(window.AppState.currentUser.role).replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
      if (normalized === 'platform_admin' || normalized === 'admin') {
        window.loadTenantDirectory?.();
      }
    }
  } catch (error) {
    window.AppState = window.AppState || {};
    window.AppState.currentUser = null;
    window.applyRoleBasedAccess();
  }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.refreshCurrentUserSession();
  }, { once: true });
} else {
  window.refreshCurrentUserSession();
}

window.openTenantRegistrationModal = function () {
  const modal = document.getElementById('tenant-registration-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  const err = document.getElementById('tenant-registration-error');
  if (err) {
    err.classList.add('hidden');
    err.textContent = '';
  }
};

window.closeTenantRegistrationModal = function () {
  const modal = document.getElementById('tenant-registration-modal');
  if (!modal) return;
  modal.classList.add('hidden');
  const form = {
    tenantName: document.getElementById('tenant-name'),
    adminUsername: document.getElementById('tenant-admin-username'),
    adminPassword: document.getElementById('tenant-admin-password'),
    coreProjectPath: document.getElementById('tenant-core-project-path')
  };
  Object.values(form).forEach((field) => {
    if (field) field.value = '';
  });
};

window.submitTenantRegistration = async function () {
  const currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  const currentRole = String((currentUser && currentUser.role) || '').trim().replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
  if (currentRole !== 'platform_admin' && currentRole !== 'admin') {
    const err = document.getElementById('tenant-registration-error');
    if (err) {
      err.textContent = 'ACCESS DENIED: ONLY PLATFORM ADMINS CAN REGISTER TENANTS.';
      err.classList.remove('hidden');
    }
    return;
  }

  const tenantName = document.getElementById('tenant-name')?.value?.trim() || '';
  const adminUsername = document.getElementById('tenant-admin-username')?.value?.trim() || '';
  const adminPassword = document.getElementById('tenant-admin-password')?.value || '';
  const coreProjectPath = document.getElementById('tenant-core-project-path')?.value?.trim() || '';
  const err = document.getElementById('tenant-registration-error');

  if (!tenantName || !adminUsername || !adminPassword) {
    if (err) {
      err.textContent = 'TENANT NAME, ADMIN USERNAME, AND PASSWORD ARE REQUIRED.';
      err.classList.remove('hidden');
    }
    return;
  }

  try {
    const response = await fetch('/api/tenants/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tenant_name: tenantName,
        admin_username: adminUsername,
        admin_password: adminPassword,
        core_project_path: coreProjectPath,
      }),
    });

    const result = await response.json();
    if (!response.ok || !result.ok) {
      if (err) {
        err.textContent = result.error || 'TENANT REGISTRATION FAILED.';
        err.classList.remove('hidden');
      }
      return;
    }

    if (err) {
      err.textContent = 'TENANT CREATED SUCCESSFULLY.';
      err.classList.remove('hidden');
      err.classList.add('text-emerald-400');
      err.classList.remove('text-red-400');
    }
    window.closeTenantRegistrationModal();
    window.loadTenantDirectory?.();
    window.logToTerminal && window.logToTerminal('TENANTS', `Registered tenant: ${tenantName}`, 'text-emerald-400');
  } catch (error) {
    if (err) {
      err.textContent = 'TENANT REGISTRATION REQUEST FAILED.';
      err.classList.remove('hidden');
    }
  }
};

window.loadTenantDirectory = async function () {
  const currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  const currentRole = String((currentUser && currentUser.role) || '').trim().replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
  if (currentRole !== 'platform_admin' && currentRole !== 'admin') {
    return;
  }

  const listEl = document.getElementById('tenant-directory-list');
  if (!listEl) return;

  try {
    const response = await fetch('/api/tenants', { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      listEl.innerHTML = '<div class="text-red-400 text-[10px] uppercase tracking-widest">Tenant directory unavailable.</div>';
      return;
    }

    const tenants = Array.isArray(payload.tenants) ? payload.tenants : [];
    if (!tenants.length) {
      listEl.innerHTML = '<div class="text-cyan-600 text-[10px] uppercase tracking-widest">No tenants registered.</div>';
      return;
    }

    listEl.innerHTML = tenants.map((tenant) => {
      const id = tenant.id || 'unknown';
      const name = tenant.name || id;
      const userCount = Array.isArray(tenant.users) ? tenant.users.length : tenant.user_count || 0;
      const status = tenant.status || 'active';
      return `
        <div class="border border-cyan-900/50 bg-black/20 p-2 rounded-sm">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-[10px] font-bold text-cyan-300 uppercase tracking-[0.2em]">${name}</div>
              <div class="text-[8px] text-cyan-600 tracking-widest">ID: ${id} · ${userCount} USERS · ${status}</div>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="window.openTenantUsers('${id}')" class="btn-ui btn-ui-cyan px-3 py-1 text-[9px] font-bold tracking-widest">OPEN</button>
              <button onclick="window.deleteTenant('${id}')" class="btn-ui btn-ui-red px-3 py-1 text-[9px] font-bold tracking-widest">DELETE</button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  } catch (error) {
    listEl.innerHTML = '<div class="text-red-400 text-[10px] uppercase tracking-widest">Tenant directory unavailable.</div>';
  }
};

window.deleteTenant = async function (tenantId) {
  if (!tenantId || !window.confirm('Delete this tenant and all tenant users?')) {
    return;
  }

  try {
    const response = await fetch(`/api/tenants/${tenantId}`, { method: 'DELETE', cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      alert(payload.error || 'Unable to delete tenant.');
      return;
    }
    alert('Tenant deleted successfully.');
    window.loadTenantDirectory?.();
    const listEl = document.getElementById('tenant-user-list');
    if (listEl) listEl.innerHTML = '<div class="text-cyan-600 text-[10px] uppercase tracking-widest">No tenant selected.</div>';
  } catch (error) {
    alert('Unable to delete tenant.');
  }
};

window.deleteTenantUser = async function (tenantId, userId, username) {
  if (!tenantId || !userId || !window.confirm(`Delete tenant user ${username || userId}?`)) {
    return;
  }

  try {
    const response = await fetch(`/api/tenants/${tenantId}/users/${userId}`, { method: 'DELETE', cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      alert(payload.error || 'Unable to delete tenant user.');
      return;
    }
    alert('Tenant user deleted successfully.');
    window.openTenantUsers?.(tenantId);
  } catch (error) {
    alert('Unable to delete tenant user.');
  }
};

window.openTenantUsers = async function (tenantId) {
  const listEl = document.getElementById('tenant-user-list');
  const heading = document.getElementById('tenant-user-list-heading');
  if (!listEl || !heading) return;

  try {
    const response = await fetch(`/api/tenants/${tenantId}`, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok || !payload.ok || !payload.tenant) {
      listEl.innerHTML = '<div class="text-red-400 text-[10px] uppercase tracking-widest">Unable to load tenant users.</div>';
      return;
    }

    const tenant = payload.tenant;
    heading.textContent = `${tenant.name || tenant.id || 'Tenant'} users`;
    const users = Array.isArray(tenant.users) ? tenant.users : [];

    if (!users.length) {
      listEl.innerHTML = '<div class="text-cyan-600 text-[10px] uppercase tracking-widest">No tenant users found.</div>';
      return;
    }

    listEl.innerHTML = `
      <div class="overflow-hidden border border-cyan-900/50">
        <table class="w-full text-left text-[9px] text-cyan-300">
          <thead class="bg-cyan-950/50 text-cyan-500 uppercase tracking-widest">
            <tr>
              <th class="p-2">Name</th>
              <th class="p-2">Role</th>
              <th class="p-2">Status</th>
              <th class="p-2">Email</th>
              <th class="p-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            ${users.map((user) => {
      const role = String(user.role || 'tenant_user').replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
      const displayRole = role === 'tenant_admin' ? 'Tenant User Admin' : role === 'tenant_view_user' ? 'Tenant View User' : role === 'platform_admin' ? 'Platform Admin' : 'Tenant View User';
      const email = user.email || user.username || '—';
      const status = user.status || 'active';
      const userId = user.id || user.username || '';
      const username = user.username || user.id || 'Unknown user';
      return `
                <tr class="border-t border-cyan-900/40">
                  <td class="p-2">${username}</td>
                  <td class="p-2">${displayRole}</td>
                  <td class="p-2">${status}</td>
                  <td class="p-2">${email}</td>
                  <td class="p-2 text-right">
                    <button onclick="window.deleteTenantUser('${tenantId}', '${userId}', '${username.replace(/'/g, "\\'")}')" class="btn-ui btn-ui-red px-2 py-1 text-[8px] font-bold tracking-widest">DELETE</button>
                  </td>
                </tr>
              `;
    }).join('')}
          </tbody>
        </table>
      </div>
    `;
  } catch (error) {
    listEl.innerHTML = '<div class="text-red-400 text-[10px] uppercase tracking-widest">Unable to load tenant users.</div>';
  }
};

// --- PROJECT REGISTRY MODAL ---
window.toggleProjectsModal = function () {
  const modal = document.getElementById('projects-modal');
  if (!modal) return;
  const opening = modal.classList.contains('hidden');
  modal.classList.toggle('hidden');
  if (opening) {
    window.closeAddProjectForm();
    window.closeEditProjectForm();
    window.AppState.socket?.emit('get_projects');
  }
};

window.renderProjectPreferences = function (prefs) {
  const path = (prefs && prefs.core_project_path) || '';
  window.AppState.coreProjectPath = path;

  const coreInput = document.getElementById('core-project-path');
  if (coreInput) coreInput.value = path;
};

window.showCorePathError = function (message) {
  const errEl = document.getElementById('core-path-error');
  if (!errEl) return;
  if (message) {
    errEl.textContent = message;
    errEl.classList.remove('hidden');
  } else {
    errEl.textContent = '';
    errEl.classList.add('hidden');
  }
};

window.saveCoreProjectPath = function () {
  const corePath = document.getElementById('core-project-path')?.value.trim() || '';
  if (!corePath) {
    window.showCorePathError('CORE PROJECT PATH IS REQUIRED.');
    return;
  }

  window.showCorePathError(null);
  window.AppState.socket?.emit('set_core_project_path', { path: corePath });
};

function normalizePathForCompare(path) {
  return String(path || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}

window.renderProjectsList = function (projects) {
  window.AppState.projects = projects || [];
  const container = document.getElementById('projects-list');
  if (!container) return;
  container.innerHTML = '';

  if (!window.AppState.projects.length) {
    container.innerHTML = '<div class="text-cyan-800 italic text-center text-[10px] py-4">No projects registered. Add one below.</div>';
    return;
  }

  window.AppState.projects.forEach(proj => {
    const row = document.createElement('div');
    row.className = 'flex items-center justify-between gap-3 bg-cyan-950/20 p-3 border border-cyan-900/40 hover:border-cyan-500/50 transition-colors';

    const info = document.createElement('div');
    info.className = 'flex flex-col min-w-0';

    const title = document.createElement('span');
    title.className = 'text-[11px] font-bold text-cyan-300 uppercase tracking-wide truncate';
    title.textContent = `${proj.friendly_name} `;
    const nameTag = document.createElement('span');
    nameTag.className = 'text-cyan-600 text-[9px] tracking-widest';
    nameTag.textContent = `(${proj.name})`;
    title.appendChild(nameTag);

    const pathEl = document.createElement('span');
    pathEl.className = 'text-[9px] text-cyan-600/80 font-mono truncate mt-1';
    pathEl.textContent = proj.path;

    const statusEl = document.createElement('span');
    statusEl.className = proj.is_running
      ? 'text-[8px] text-amber-400 border border-amber-700/70 px-1 mt-1 tracking-widest font-bold w-fit'
      : 'text-[8px] text-emerald-400 border border-emerald-700/70 px-1 mt-1 tracking-widest font-bold w-fit';
    statusEl.textContent = proj.is_running ? 'RUNNING' : 'STOPPED';

    const locationEl = document.createElement('span');
    locationEl.className = 'text-[8px] text-cyan-700 tracking-widest mt-1';
    locationEl.textContent = proj.is_in_core_path ? 'LOCATION: CORE PATH' : 'LOCATION: CURRENT PATH';

    const typeEl = document.createElement('span');
    typeEl.className = 'text-[8px] text-cyan-700 tracking-widest mt-1';
    typeEl.textContent = `TYPE: ${String(proj.deployment_profile?.project_type || 'custom').toUpperCase()}`;

    const runtimeError = String(proj.runtime_state?.last_error || '').trim();
    const runtimeStage = String(proj.runtime_state?.last_error_stage || '').trim();
    let errorEl = null;
    if (runtimeError) {
      errorEl = document.createElement('span');
      errorEl.className = 'text-[8px] text-rose-400 tracking-wide mt-1 truncate';
      errorEl.title = runtimeError;
      errorEl.textContent = `ISSUE${runtimeStage ? ` (${runtimeStage.toUpperCase()})` : ''}: ${runtimeError}`;
    }

    info.appendChild(title);
    info.appendChild(pathEl);
    info.appendChild(statusEl);
    info.appendChild(locationEl);
    info.appendChild(typeEl);
    if (errorEl) info.appendChild(errorEl);

    const actions = document.createElement('div');
    actions.className = 'flex gap-1 shrink-0';

    const runBtn = document.createElement('button');
    runBtn.className = 'btn-ui btn-ui-emerald text-[9px] py-1 px-3 font-bold tracking-widest';
    runBtn.textContent = 'RUN';
    runBtn.addEventListener('click', () => window.runProject(proj.name));

    const editBtn = document.createElement('button');
    editBtn.className = 'btn-ui btn-ui-cyan text-[9px] py-1 px-3 font-bold tracking-widest';
    editBtn.textContent = 'EDIT';
    editBtn.addEventListener('click', () => window.openEditProjectForm(proj));

    const moveBtn = document.createElement('button');
    moveBtn.className = 'btn-ui btn-ui-zinc text-[9px] py-1 px-3 font-bold tracking-widest';
    moveBtn.textContent = 'MOVE CORE';
    moveBtn.disabled = !window.AppState.coreProjectPath || proj.is_in_core_path || proj.is_running;
    if (moveBtn.disabled) moveBtn.classList.add('opacity-50', 'cursor-not-allowed');
    moveBtn.addEventListener('click', () => {
      if (moveBtn.disabled) return;
      window.moveProjectToCore(proj.name);
    });

    const removeBtn = document.createElement('button');
    removeBtn.className = 'btn-ui btn-ui-red text-[9px] py-1 px-3 font-bold tracking-widest';
    removeBtn.textContent = 'REMOVE';
    removeBtn.addEventListener('click', () => window.removeProjectFromRegistry(proj.name));

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'btn-ui btn-ui-red text-[9px] py-1 px-3 font-bold tracking-widest';
    deleteBtn.textContent = 'DELETE';
    deleteBtn.disabled = !proj.is_in_core_path || proj.is_running;
    if (deleteBtn.disabled) deleteBtn.classList.add('opacity-50', 'cursor-not-allowed');
    deleteBtn.addEventListener('click', () => {
      if (deleteBtn.disabled) return;
      window.deleteProjectFromCore(proj);
    });

    actions.appendChild(runBtn);
    actions.appendChild(editBtn);
    actions.appendChild(moveBtn);
    actions.appendChild(removeBtn);
    actions.appendChild(deleteBtn);
    row.appendChild(info);
    row.appendChild(actions);
    container.appendChild(row);
  });
};

window.moveProjectToCore = function (name) {
  window.logToTerminal('PROJECTS', `Moving project '${name}' to Core Project Path`, 'text-cyan-400');
  window.AppState.socket?.emit('move_project_to_core', { name: name });
};

window.runProject = function (name) {
  window.logToTerminal('UI_OVERRIDE', `Initiating START sequence for project ${name}`, 'text-emerald-400 font-bold');
  window.AppState.socket?.emit('ui_command', { command: `start ${name}` });
  window.toggleProjectsModal();
};

window.removeProjectFromRegistry = function (name) {
  window.logToTerminal('UI_OVERRIDE', `Removing project ${name} from registry`, 'text-red-500 font-bold');
  window.AppState.socket?.emit('remove_project', { name: name });
};

window.deleteProjectFromCore = function (project) {
  const proj = project || {};
  const name = String(proj.name || '').trim();
  if (!name) return;

  const friendlyName = String(proj.friendly_name || name).trim();
  const projectPath = String(proj.path || '').trim();

  const confirmation = window.confirm(
    `Delete project "${friendlyName}" (${name}) from Core Project Path?\n\nThis will permanently delete:\n1) The project registry entry\n2) Project files at:\n${projectPath}`
  );
  if (!confirmation) return;

  window.logToTerminal('UI_OVERRIDE', `Deleting project ${name} and core files`, 'text-red-500 font-bold');
  window.AppState.socket?.emit('delete_project_from_core', { name: name });
};

window.openAddProjectForm = async function () {
  let currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  if (!currentUser && typeof window.refreshCurrentUserSession === 'function') {
    await window.refreshCurrentUserSession();
    currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  }

  const role = normalizeRoleName(currentUser && currentUser.role);
  const isPlatformAdmin = role === 'platform_admin' || role === 'admin';
  const isTenantAdmin = role === 'tenant_admin' || role === 'tenant_user_admin';
  if (!isPlatformAdmin && !isTenantAdmin) {
    return;
  }

  window.closeEditProjectForm();
  const form = document.getElementById('add-project-form');
  if (form) {
    form.classList.remove('hidden');
    form.classList.add('flex');
  }
  document.getElementById('btn-open-add-project')?.classList.add('hidden');
  const sourceMode = document.getElementById('proj-source-mode');
  if (sourceMode) sourceMode.value = isPlatformAdmin ? 'host' : 'upload';
  const saveMode = document.getElementById('proj-save-mode');
  if (saveMode) saveMode.value = isPlatformAdmin ? 'current' : 'core';
  window.onProjectSourceModeChanged();
  window.onProjectSaveModeChanged();
  window.showProjectFormError(null);
};

window.closeAddProjectForm = function () {
  const form = document.getElementById('add-project-form');
  if (form) {
    form.classList.add('hidden');
    form.classList.remove('flex');
  }
  document.getElementById('btn-open-add-project')?.classList.remove('hidden');
  ['proj-name', 'proj-friendly', 'proj-path', 'proj-custom-start'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  window.clearUploadSelection();
  const dest = document.getElementById('proj-destination-path');
  if (dest) dest.value = '';
  window.AppState.folderListing = null;
  document.getElementById('proj-folder-preview')?.classList.add('hidden');
  window.showProjectFormError(null);
};

function normalizeUploadRelPath(path) {
  return String(path || '').replace(/\\/g, '/').replace(/^\/+/, '').trim();
}

function updateUploadSummary() {
  const summary = document.getElementById('proj-upload-summary');
  if (!summary) return;

  const map = window.AppState.uploadSelectionMap || {};
  const relPaths = Object.keys(map);
  if (!relPaths.length) {
    summary.textContent = 'NO FILES OR FOLDERS SELECTED';
    return;
  }

  const folderRoots = new Set();
  let singleFiles = 0;
  relPaths.forEach(rel => {
    const parts = rel.split('/').filter(Boolean);
    if (parts.length > 1) folderRoots.add(parts[0]);
    else singleFiles += 1;
  });

  summary.textContent = `${relPaths.length} ITEMS • ${folderRoots.size} FOLDERS • ${singleFiles} FILES`;
}

function addUploadFiles(fileList, mode) {
  if (!fileList || !fileList.length) return;

  if (!window.AppState.uploadSelectionMap || typeof window.AppState.uploadSelectionMap !== 'object') {
    window.AppState.uploadSelectionMap = {};
  }

  Array.from(fileList).forEach(file => {
    const rel = mode === 'folder'
      ? normalizeUploadRelPath(file.webkitRelativePath || file.name)
      : normalizeUploadRelPath(file.name);

    if (!rel) return;

    // Avoid uploading heavy dependency folders by default.
    if (/(^|\/)node_modules(\/|$)/i.test(rel)) return;

    window.AppState.uploadSelectionMap[rel] = file;
  });

  updateUploadSummary();
}

window.clearUploadSelection = function () {
  window.AppState.uploadSelectionMap = {};

  const folderInput = document.getElementById('proj-upload-folders');
  if (folderInput) folderInput.value = '';

  const filesInput = document.getElementById('proj-upload-files');
  if (filesInput) filesInput.value = '';

  updateUploadSummary();
};

window.onProjectSourceModeChanged = function () {
  const currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  const role = normalizeRoleName(currentUser && currentUser.role);
  const isPlatformAdmin = role === 'platform_admin' || role === 'admin';
  const isTenantUser = !!(currentUser && currentUser.tenant_id) && !isPlatformAdmin;
  const tenantAdminMode = role === 'tenant_admin' || role === 'tenant_user_admin';
  const mode = (isTenantUser || tenantAdminMode) ? 'upload' : (document.getElementById('proj-source-mode')?.value || 'host');
  const hostBox = document.getElementById('proj-source-host');
  const uploadBox = document.getElementById('proj-source-upload');
  const pathRow = document.getElementById('proj-path-row');
  const saveMode = document.getElementById('proj-save-mode');

  if ((isTenantUser || tenantAdminMode) && document.getElementById('proj-source-mode')) {
    document.getElementById('proj-source-mode').value = 'upload';
  }

  if (hostBox) {
    hostBox.classList.toggle('hidden', mode !== 'host');
    hostBox.classList.toggle('flex', mode === 'host');
  }
  if (uploadBox) {
    uploadBox.classList.toggle('hidden', mode !== 'upload');
    uploadBox.classList.toggle('flex', mode === 'upload');
  }
  if (pathRow) {
    const showPathRow = isPlatformAdmin && mode === 'host';
    pathRow.classList.toggle('hidden', !showPathRow);
    pathRow.classList.toggle('flex', showPathRow);
  }

  if (saveMode) {
    const currentOption = Array.from(saveMode.options).find(opt => opt.value === 'current');
    if (currentOption) currentOption.disabled = (mode === 'upload' || isTenantUser || tenantAdminMode);
    const customOption = Array.from(saveMode.options).find(opt => opt.value === 'custom');
    if (customOption) customOption.disabled = isTenantUser || tenantAdminMode;
    if (isTenantUser || tenantAdminMode) {
      saveMode.value = 'core';
    } else if (mode === 'upload' && saveMode.value === 'current') {
      saveMode.value = window.AppState.coreProjectPath ? 'core' : 'custom';
    }
  }

  window.onProjectSaveModeChanged();
};

window.onUploadFolderSelected = function () {
  const input = document.getElementById('proj-upload-folders');
  addUploadFiles(input?.files, 'folder');
};

window.onUploadFilesSelected = function () {
  const input = document.getElementById('proj-upload-files');
  addUploadFiles(input?.files, 'file');
};

window.onProjectSaveModeChanged = function () {
  const mode = document.getElementById('proj-save-mode')?.value || 'current';
  const row = document.getElementById('proj-destination-row');
  if (!row) return;

  if (mode === 'custom') {
    row.classList.remove('hidden');
    row.classList.add('flex');
  } else {
    row.classList.add('hidden');
    row.classList.remove('flex');
  }
};

window.showProjectFormError = function (message) {
  const errEl = document.getElementById('proj-form-error');
  if (!errEl) return;
  if (message) {
    errEl.textContent = message;
    errEl.classList.remove('hidden');
  } else {
    errEl.textContent = '';
    errEl.classList.add('hidden');
  }
};

window.submitAddProject = function () {
  const sourceMode = document.getElementById('proj-source-mode')?.value || 'host';
  const name = document.getElementById('proj-name')?.value.trim() || '';
  const friendly = document.getElementById('proj-friendly')?.value.trim() || '';
  const path = document.getElementById('proj-path')?.value.trim() || '';
  const customStart = document.getElementById('proj-custom-start')?.value.trim() || '';
  const saveMode = document.getElementById('proj-save-mode')?.value || 'current';
  const destinationPath = document.getElementById('proj-destination-path')?.value.trim() || '';

  if (!/^[A-Za-z0-9._-]{1,40}$/.test(name)) {
    window.showProjectFormError('INVALID NAME: 1-40 CHARS, LETTERS / DIGITS / DOT / DASH / UNDERSCORE ONLY.');
    return;
  }
  if (sourceMode === 'host' && !path) {
    window.showProjectFormError('PROJECT FOLDER REQUIRED. USE BROWSE TO SELECT ONE.');
    return;
  }
  if (sourceMode === 'upload') {
    const selected = window.AppState.uploadSelectionMap || {};
    if (Object.keys(selected).length === 0) {
      window.showProjectFormError('SELECT AT LEAST ONE FOLDER OR FILE FOR UPLOAD.');
      return;
    }
    if (saveMode === 'current') {
      window.showProjectFormError('UPLOAD MODE REQUIRES CORE OR CUSTOM DESTINATION.');
      return;
    }
  }
  if (saveMode === 'core' && !window.AppState.coreProjectPath) {
    window.showProjectFormError('CORE PROJECT PATH IS NOT SET. CONFIGURE IT BEFORE USING MOVE TO CORE.');
    return;
  }
  if (saveMode === 'custom' && !destinationPath) {
    window.showProjectFormError('CUSTOM DESTINATION FOLDER REQUIRED FOR CUSTOM SAVE MODE.');
    return;
  }

  if (sourceMode === 'host' && (saveMode === 'custom' || saveMode === 'core')) {
    const sourceNorm = normalizePathForCompare(path);
    const baseNorm = normalizePathForCompare(saveMode === 'core' ? window.AppState.coreProjectPath : destinationPath);
    if (sourceNorm && baseNorm && sourceNorm.startsWith(baseNorm + '/')) {
      window.showProjectFormError('SOURCE ALREADY INSIDE DESTINATION. USE CURRENT LOCATION MODE.');
      return;
    }
  }

  window.showProjectFormError(null);

  if (sourceMode === 'upload') {
    const selectionMap = window.AppState.uploadSelectionMap || {};
    const entries = Object.entries(selectionMap);
    const formData = new FormData();
    formData.append('name', name);
    formData.append('friendly_name', friendly || name);
    formData.append('custom_start', customStart);
    formData.append('storage_mode', saveMode);
    if (destinationPath) formData.append('destination_path', destinationPath);

    entries.forEach(([relPath, file]) => {
      formData.append('project_files', file, relPath);
    });

    fetch('/api/upload_project', {
      method: 'POST',
      body: formData,
    })
      .then(res => res.json().catch(() => ({ ok: false, error: 'Invalid server response.' })))
      .then(payload => {
        if (payload.ok) {
          window.closeAddProjectForm();
          window.logToTerminal('PROJECTS', 'Project uploaded and registered successfully.', 'text-emerald-400 font-bold');
          window.AppState.socket?.emit('get_projects');
        } else {
          window.showProjectFormError((payload.error || 'UPLOAD FAILED').toUpperCase());
        }
      })
      .catch(err => {
        window.showProjectFormError((`Upload failed: ${err.message || err}`).toUpperCase());
      });
    return;
  }

  window.AppState.socket?.emit('add_project', {
    name: name,
    friendly_name: friendly || name,
    path: path,
    custom_start: customStart,
    storage_mode: saveMode,
    destination_path: destinationPath
  });
};

window.openEditProjectForm = function (project) {
  window.AppState.editingProject = project;

  const form = document.getElementById('edit-project-form');
  if (form) {
    form.classList.remove('hidden');
    form.classList.add('flex');
  }
  const addForm = document.getElementById('add-project-form');
  if (addForm) {
    addForm.classList.add('hidden');
    addForm.classList.remove('flex');
  }
  document.getElementById('btn-open-add-project')?.classList.add('hidden');

  const originalName = document.getElementById('edit-original-name');
  const nameInput = document.getElementById('edit-proj-name');
  const friendlyInput = document.getElementById('edit-proj-friendly');
  const pathInput = document.getElementById('edit-proj-path');
  const customStartInput = document.getElementById('edit-proj-custom-start');
  const warning = document.getElementById('edit-proj-warning');
  const error = document.getElementById('edit-proj-error');

  if (originalName) originalName.value = project.name || '';
  if (nameInput) nameInput.value = project.name || '';
  if (friendlyInput) friendlyInput.value = project.friendly_name || project.name || '';
  if (pathInput) pathInput.value = project.path || '';
  if (customStartInput) customStartInput.value = project.custom_start || '';

  const lockSensitive = !!project.is_running;
  if (nameInput) nameInput.disabled = lockSensitive;
  if (pathInput) pathInput.disabled = lockSensitive;
  if (customStartInput) customStartInput.disabled = lockSensitive;

  if (warning) {
    if (lockSensitive) {
      warning.textContent = 'PROJECT IS RUNNING: ONLY FRIENDLY NAME CAN BE EDITED.';
      warning.classList.remove('hidden');
    } else {
      warning.textContent = '';
      warning.classList.add('hidden');
    }
  }

  if (error) {
    error.textContent = '';
    error.classList.add('hidden');
  }
};

window.closeEditProjectForm = function () {
  const form = document.getElementById('edit-project-form');
  if (form) {
    form.classList.add('hidden');
    form.classList.remove('flex');
  }
  window.AppState.editingProject = null;
  document.getElementById('btn-open-add-project')?.classList.remove('hidden');
};

window.submitEditProject = function () {
  const editing = window.AppState.editingProject || {};
  const originalName = document.getElementById('edit-original-name')?.value.trim() || '';
  const newName = document.getElementById('edit-proj-name')?.value.trim() || '';
  const friendlyName = document.getElementById('edit-proj-friendly')?.value.trim() || '';
  const path = document.getElementById('edit-proj-path')?.value.trim() || '';
  const customStart = document.getElementById('edit-proj-custom-start')?.value.trim() || '';
  const error = document.getElementById('edit-proj-error');

  if (!originalName) return;

  if (!newName || !/^[A-Za-z0-9._-]{1,40}$/.test(newName)) {
    if (error) {
      error.textContent = 'INVALID NAME: 1-40 CHARS, LETTERS / DIGITS / DOT / DASH / UNDERSCORE ONLY.';
      error.classList.remove('hidden');
    }
    return;
  }

  if (!path) {
    if (error) {
      error.textContent = 'PROJECT PATH IS REQUIRED.';
      error.classList.remove('hidden');
    }
    return;
  }

  if (error) {
    error.textContent = '';
    error.classList.add('hidden');
  }

  window.AppState.socket?.emit('update_project', {
    name: originalName,
    new_name: editing.is_running ? originalName : newName,
    friendly_name: friendlyName || newName,
    path: editing.is_running ? null : path,
    custom_start: editing.is_running ? null : customStart
  });
};

// --- FOLDER NAVIGATOR ---
window.openFolderNavigator = function (targetInputId = 'proj-path') {
  const currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  const role = String((currentUser && currentUser.role) || '').trim().replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
  const isPlatformAdmin = role === 'platform_admin' || role === 'admin';
  const restrictedCorePathTarget = targetInputId === 'core-project-path' || targetInputId === 'tenant-core-project-path';

  if (restrictedCorePathTarget && !isPlatformAdmin) {
    return;
  }

  window.AppState.folderPath = null;
  window.AppState.folderSelectTarget = targetInputId;
  document.getElementById('folder-modal')?.classList.remove('hidden');
  window.AppState.socket?.emit('browse_folders', { path: null });
};

window.closeFolderNavigator = function () {
  document.getElementById('folder-modal')?.classList.add('hidden');
};

window.navigateFolder = function (path) {
  window.AppState.socket?.emit('browse_folders', { path: path });
};

window.navigateFolderUp = function () {
  const parent = window.AppState.folderParent;
  window.navigateFolder(parent || null);
};

window.renderFolderListing = function (data) {
  window.AppState.folderPath = data.path;
  window.AppState.folderParent = data.parent;
  window.AppState.folderListing = data;

  const pathEl = document.getElementById('folder-current-path');
  if (pathEl) pathEl.textContent = data.path || 'MY COMPUTER';

  const upBtn = document.getElementById('folder-up-btn');
  if (upBtn) upBtn.disabled = !data.path;

  const errEl = document.getElementById('folder-error');
  if (errEl) {
    if (data.error) {
      errEl.textContent = data.error.toUpperCase();
      errEl.classList.remove('hidden');
    } else {
      errEl.textContent = '';
      errEl.classList.add('hidden');
    }
  }

  const list = document.getElementById('folder-list');
  if (!list) return;
  list.innerHTML = '';

  const dirs = data.dirs || [];
  const files = data.files || [];

  if (!dirs.length && !files.length) {
    list.innerHTML = '<div class="text-cyan-800 italic text-center text-[10px] py-4 shrink-0">Empty folder.</div>';
    return;
  }

  dirs.forEach(dirPath => {
    // shrink-0 is required: flex column parents compress rows instead of scrolling
    const row = document.createElement('button');
    row.className = 'shrink-0 text-left text-[10px] text-cyan-300 hover:text-white font-mono tracking-wide px-2 py-1.5 border border-transparent hover:border-cyan-700 hover:bg-cyan-950/50 transition-all truncate cursor-pointer';
    const label = data.path ? dirPath.split(/[\\/]/).filter(Boolean).pop() : dirPath;
    row.textContent = `▸ ${label}`;
    row.title = dirPath;
    row.addEventListener('click', () => window.navigateFolder(dirPath));
    list.appendChild(row);
  });

  files.forEach(fileName => {
    const row = document.createElement('div');
    row.className = 'shrink-0 text-left text-[10px] text-cyan-700 font-mono tracking-wide px-2 py-1 truncate';
    row.textContent = `· ${fileName}`;
    row.title = fileName;
    list.appendChild(row);
  });
};

window.renderFolderPreview = function () {
  const listing = window.AppState.folderListing;
  const preview = document.getElementById('proj-folder-preview');
  if (!preview) return;

  if (!listing || !listing.path) {
    preview.classList.add('hidden');
    return;
  }

  const folderName = listing.path.split(/[\\/]/).filter(Boolean).pop() || listing.path;
  const nameEl = document.getElementById('proj-folder-name');
  if (nameEl) nameEl.textContent = folderName;

  const contents = document.getElementById('proj-folder-contents');
  if (contents) {
    contents.innerHTML = '';
    const dirs = (listing.dirs || []).map(d => `▸ ${d.split(/[\\/]/).filter(Boolean).pop()}`);
    const files = (listing.files || []).map(f => `· ${f}`);
    const entries = dirs.concat(files);

    if (!entries.length) {
      contents.innerHTML = '<div class="text-cyan-800 italic text-[9px] py-1">Empty folder.</div>';
    } else {
      const MAX_PREVIEW = 50;
      entries.slice(0, MAX_PREVIEW).forEach(label => {
        const row = document.createElement('div');
        row.className = 'text-[9px] text-cyan-500 font-mono truncate';
        row.textContent = label;
        contents.appendChild(row);
      });
      if (entries.length > MAX_PREVIEW) {
        const more = document.createElement('div');
        more.className = 'text-[9px] text-cyan-700 italic pt-1';
        more.textContent = `+ ${entries.length - MAX_PREVIEW} more items`;
        contents.appendChild(more);
      }
    }
  }

  preview.classList.remove('hidden');
};

window.selectCurrentFolder = function () {
  if (!window.AppState.folderPath) {
    return; // drive list level — nothing selectable yet
  }
  const targetId = window.AppState.folderSelectTarget || 'proj-path';
  const currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  const role = String((currentUser && currentUser.role) || '').trim().replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
  const isPlatformAdmin = role === 'platform_admin' || role === 'admin';
  const restrictedCorePathTarget = targetId === 'core-project-path' || targetId === 'tenant-core-project-path';

  if (restrictedCorePathTarget && !isPlatformAdmin) {
    window.closeFolderNavigator();
    return;
  }

  const pathInput = document.getElementById(targetId);
  if (pathInput) pathInput.value = window.AppState.folderPath;

  if (targetId === 'core-project-path' || targetId === 'tenant-core-project-path') {
    if (targetId === 'core-project-path') {
      window.showCorePathError(null);
    }
    window.closeFolderNavigator();
    return;
  }

  if (targetId === 'proj-path') {
    // Prefill names from the folder if the user hasn't typed any.
    const folderName = window.AppState.folderPath.split(/[\\/]/).filter(Boolean).pop() || '';
    const nameInput = document.getElementById('proj-name');
    if (nameInput && !nameInput.value.trim()) {
      nameInput.value = folderName.toLowerCase().replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
    }
    const friendlyInput = document.getElementById('proj-friendly');
    if (friendlyInput && !friendlyInput.value.trim()) {
      friendlyInput.value = folderName;
    }
  }

  window.renderFolderPreview();
  window.closeFolderNavigator();
};

// --- CIRCULAR WIDGETS ---
const CIRC_MAX = 150.7;
window.setCircleData = function (elementId, textId, value, max, formatStr, colorClass) {
  const percent = max === 0 ? 0 : Math.min(Math.max((value / max) * 100, 0), 100);
  const offset = CIRC_MAX - (percent / 100) * CIRC_MAX;
  const circ = document.getElementById(elementId);
  const txt = document.getElementById(textId);
  if (circ && txt) {
    circ.style.strokeDashoffset = offset;
    circ.className.baseVal = `${colorClass} circle-transition`;
    txt.textContent = `${value}${formatStr}`;
  }
};

// --- ACTION BUTTON ROUTERS ---
window.serviceAction = function (action, serviceName) {
  if (action === 'log') {
    window.toggleLogs(serviceName);
  } else if (action === 'flush') {
    window.logToTerminal('UI_OVERRIDE', `Clearing PM2 logs for ${serviceName}`, 'text-zinc-400 font-bold');
    window.AppState.socket?.emit('ui_command', { command: `flush ${serviceName}` });
  } else {
    window.logToTerminal('UI_OVERRIDE', `Initiating ${action.toUpperCase()} sequence for ${serviceName}`, 'text-amber-400 font-bold');
    window.AppState.socket?.emit('ui_command', { command: `${action} ${serviceName}` });
  }
};

window.restoreCoreServices = function () {
  window.logToTerminal('UI_OVERRIDE', `Initiating bulk START sequence for all Core Services`, 'text-amber-400 font-bold');
  window.AppState.socket?.emit('ui_command', { command: 'start all' });
};

window.toggleLogs = function (serviceName) {
  const statusEl = document.getElementById('log-connection-status');
  const logStream = document.getElementById('service-log-stream');
  const stopBtn = document.getElementById('stop-log-btn');

  if (window.AppState.activeLogService === serviceName) {
    window.AppState.socket?.emit('toggle_service_logs', { service: serviceName, action: 'stop' });
    window.AppState.activeLogService = null;
    if (statusEl) {
      statusEl.textContent = 'DISCONNECTED';
      statusEl.className = 'text-[9px] text-amber-500 uppercase px-1 border border-amber-600 tracking-widest';
    }
    if (stopBtn) stopBtn.classList.add('hidden');
    return;
  }

  if (window.AppState.activeLogService) {
    window.AppState.socket?.emit('toggle_service_logs', { service: window.AppState.activeLogService, action: 'stop' });
  }

  if (!window.AppState.isLogPanelOpen) window.toggleLogPanel();

  window.AppState.activeLogService = serviceName;
  if (logStream) logStream.innerHTML = '';
  if (statusEl) {
    statusEl.textContent = `STREAMING: ${serviceName}`;
    statusEl.className = 'text-[9px] text-emerald-400 uppercase px-1 border border-emerald-500 tracking-widest animate-pulse font-bold';
  }
  if (stopBtn) stopBtn.classList.remove('hidden');
  window.AppState.socket?.emit('toggle_service_logs', { service: serviceName, action: 'start' });
};

window.stopActiveLogStream = function () {
  const active = window.AppState.activeLogService;
  const statusEl = document.getElementById('log-connection-status');
  const stopBtn = document.getElementById('stop-log-btn');

  if (!active) return;

  window.AppState.socket?.emit('toggle_service_logs', { service: active, action: 'stop' });
  window.AppState.activeLogService = null;

  if (statusEl) {
    statusEl.textContent = 'DISCONNECTED';
    statusEl.className = 'text-[9px] text-amber-500 uppercase px-1 border border-amber-600 tracking-widest';
  }
  if (stopBtn) stopBtn.classList.add('hidden');
  window.logToTerminal('LOG-MGR', 'Stopped active log stream. Application runtime is unaffected.', 'text-amber-400');
};

window.renderSettingsUI = function () {
  const s = window.AppState.settings;

  if (typeof window.applyTheme === 'function') {
    window.applyTheme(s.theme || 'dark');
  }

  const btnB = document.getElementById('btn-eng-browser');
  const btnL = document.getElementById('btn-eng-legacy');
  if (btnB && btnL) {
    if (s.engine === 'browser') {
      btnB.className = "btn-ui btn-ui-emerald px-4 py-1.5 text-[9px] font-bold tracking-widest";
      btnL.className = "btn-ui btn-ui-cyan px-4 py-1.5 text-[9px] font-bold tracking-widest";
    } else {
      btnL.className = "btn-ui btn-ui-emerald px-4 py-1.5 text-[9px] font-bold tracking-widest";
      btnB.className = "btn-ui btn-ui-cyan px-4 py-1.5 text-[9px] font-bold tracking-widest";
    }
  }

  const btnThemeDark = document.getElementById('btn-theme-dark');
  const btnThemeLight = document.getElementById('btn-theme-light');
  if (btnThemeDark && btnThemeLight) {
    if ((s.theme || 'dark') === 'light') {
      btnThemeLight.className = "btn-ui btn-ui-emerald px-4 py-1.5 text-[9px] font-bold tracking-widest";
      btnThemeDark.className = "btn-ui btn-ui-cyan px-4 py-1.5 text-[9px] font-bold tracking-widest";
    } else {
      btnThemeDark.className = "btn-ui btn-ui-emerald px-4 py-1.5 text-[9px] font-bold tracking-widest";
      btnThemeLight.className = "btn-ui btn-ui-cyan px-4 py-1.5 text-[9px] font-bold tracking-widest";
    }
  }

  const updateBtn = (id, val, textOn = "ON", textOff = "OFF") => {
    const btn = document.getElementById(id);
    if (!btn) return;
    if (val) {
      btn.className = "btn-ui btn-ui-emerald px-5 py-1.5 text-[9px] font-bold tracking-widest";
      btn.textContent = textOn;
    } else {
      btn.className = "btn-ui btn-ui-cyan px-5 py-1.5 text-[9px] font-bold tracking-widest";
      btn.textContent = textOff;
    }
  };

  updateBtn('btn-set-mic', s.mic);
  updateBtn('btn-set-speaker', s.speaker);
  updateBtn('btn-set-autolisten', s.autolisten);

  const volSlide = document.getElementById('slide-volume');
  if (volSlide) {
    volSlide.value = s.volume;
    const lbl = document.getElementById('lbl-volume');
    if (lbl) lbl.textContent = `${Math.round(s.volume * 100)}%`;
  }

  const rateSlide = document.getElementById('slide-rate');
  if (rateSlide) {
    rateSlide.value = s.rate;
    const lbl = document.getElementById('lbl-rate');
    if (lbl) lbl.textContent = `${s.rate.toFixed(1)}x`;
  }

  const micBadge = document.getElementById('status-mic');
  if (micBadge) {
    micBadge.className = s.mic
      ? 'inline-flex items-center justify-center status-chip-up border px-2 py-0.5 font-bold'
      : 'inline-flex items-center justify-center status-chip-down border px-2 py-0.5 font-bold';
    micBadge.setAttribute('aria-label', s.mic ? 'Microphone is on' : 'Microphone is off');

    const micSlash = document.getElementById('status-mic-slash');
    if (micSlash) micSlash.classList.toggle('hidden', s.mic);
  }

  const audioBadge = document.getElementById('status-audio');
  if (audioBadge) {
    audioBadge.className = s.speaker
      ? 'inline-flex items-center justify-center status-chip-up border px-2 py-0.5 font-bold'
      : 'inline-flex items-center justify-center text-amber-400 border border-amber-600 px-2 py-0.5 bg-amber-950/30 font-bold';
    audioBadge.setAttribute('aria-label', s.speaker ? 'Speaker is on' : 'Speaker is muted');

    const audioWave = document.getElementById('status-audio-wave');
    if (audioWave) audioWave.classList.toggle('hidden', !s.speaker);

    const audioSlash = document.getElementById('status-audio-slash');
    if (audioSlash) audioSlash.classList.toggle('hidden', s.speaker);
  }
};