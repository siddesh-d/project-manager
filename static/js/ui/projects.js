// Project registry modal and list (split from ui.js)

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

    const filesBtn = document.createElement('button');
    filesBtn.className = 'btn-ui btn-ui-cyan text-[9px] py-1 px-3 font-bold tracking-widest';
    filesBtn.textContent = 'FILES';
    filesBtn.addEventListener('click', () => window.openProjectFileEditor(proj.name));

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
    actions.appendChild(filesBtn);
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
  window.openStartServiceModal(name, true);
};

window.openStartServiceModal = function (name, fromProjects = false) {
  window.AppState.startServiceTarget = name;
  window.AppState.startFromProjects = fromProjects;
  window.AppState.startServiceTrigger = document.activeElement;
  document.getElementById('start-service-target').textContent = name;
  document.getElementById('start-service-cluster').checked = false;
  const input = document.getElementById('start-service-instances');
  input.value = '1';
  input.disabled = true;
  document.getElementById('start-service-modal').classList.remove('hidden');
  document.getElementById('start-service-cluster').focus();
};

window.closeStartServiceModal = function () {
  document.getElementById('start-service-modal').classList.add('hidden');
  window.AppState.startServiceTarget = null;
  window.AppState.startServiceTrigger?.focus();
};

window.confirmStartService = function (event) {
  event.preventDefault();
  const name = window.AppState.startServiceTarget;
  if (!name) return;
  const cluster = document.getElementById('start-service-cluster').checked;
  const input = document.getElementById('start-service-instances');
  const instances = Number(input.value);
  input.setCustomValidity(cluster && (!Number.isSafeInteger(instances) || instances < 1)
    ? 'Enter a positive integer.' : '');
  if (cluster && !input.reportValidity()) return;
  const instanceArgs = cluster ? ` --instances ${instances}` : '';
  window.runServiceOperation('start', name, `start ${name}${instanceArgs}`);
  const fromProjects = window.AppState.startFromProjects;
  window.closeStartServiceModal();
  if (fromProjects) window.toggleProjectsModal();
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

