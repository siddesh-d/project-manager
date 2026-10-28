// Add/edit project forms and uploads (split from ui.js)

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

