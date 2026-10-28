// Project file editor (split from ui.js)

window.closeProjectFileEditor = function () {
  const modal = document.getElementById('project-file-editor-modal');
  if (modal) modal.classList.add('hidden');
  window.AppState.fileEditorProject = null;
  window.AppState.fileEditorPath = '';
  window.AppState.fileEditorCurrentFile = '';
  const filePathEl = document.getElementById('project-file-editor-current-file');
  if (filePathEl) filePathEl.textContent = 'NO FILE SELECTED';
  const fileContent = document.getElementById('project-file-editor-content');
  if (fileContent) fileContent.value = '';
};

function showProjectFileEditorError(message) {
  const errEl = document.getElementById('project-file-editor-error');
  if (!errEl) return;
  if (message) {
    errEl.textContent = String(message || 'FILE EDITOR ERROR').toUpperCase();
    errEl.classList.remove('hidden');
  } else {
    errEl.textContent = '';
    errEl.classList.add('hidden');
  }
}

function renderProjectFileListing(payload) {
  const listEl = document.getElementById('project-file-editor-list');
  const currentPathEl = document.getElementById('project-file-editor-current-path');
  const upBtn = document.getElementById('project-file-editor-up-btn');
  if (!listEl || !currentPathEl || !upBtn) return;

  const relPath = String((payload && payload.path) || '').trim();
  window.AppState.fileEditorPath = relPath;
  currentPathEl.textContent = relPath || '/';
  upBtn.disabled = !relPath;

  listEl.innerHTML = '';
  const dirs = Array.isArray(payload && payload.dirs) ? payload.dirs : [];
  const files = Array.isArray(payload && payload.files) ? payload.files : [];

  if (!dirs.length && !files.length) {
    listEl.innerHTML = '<div class="text-cyan-800 italic text-center text-[10px] py-4">No files in this folder.</div>';
  }

  dirs.forEach((item) => {
    const entry = document.createElement('div');
    entry.className = 'flex items-center gap-1 min-w-0';
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'min-w-0 flex-1 text-left text-[10px] text-cyan-300 hover:text-white font-mono tracking-wide px-2 py-1.5 border border-transparent hover:border-cyan-700 hover:bg-cyan-950/50 transition-all truncate cursor-pointer';
    row.textContent = `▸ ${item.name}`;
    row.title = item.path;
    row.addEventListener('click', () => window.loadProjectFileListing(item.path));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn-ui btn-ui-red px-2 py-1 text-[9px] shrink-0';
    remove.textContent = 'DELETE';
    remove.title = `Delete folder ${item.path}`;
    remove.addEventListener('click', () => window.deleteProjectFolder(item.path));
    entry.append(row, remove);
    listEl.appendChild(entry);
  });

  files.forEach((item) => {
    const entry = document.createElement('div');
    entry.className = 'flex items-center gap-1 min-w-0';
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'min-w-0 flex-1 text-left text-[10px] text-cyan-500 hover:text-cyan-200 font-mono tracking-wide px-2 py-1.5 border border-transparent hover:border-cyan-700 hover:bg-cyan-950/50 transition-all truncate cursor-pointer';
    row.textContent = `· ${item.name}`;
    row.title = item.path;
    row.addEventListener('click', () => window.loadProjectFileContent(item.path));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn-ui btn-ui-red px-2 py-1 text-[9px] shrink-0';
    remove.textContent = 'DELETE';
    remove.title = `Delete file ${item.path}`;
    remove.addEventListener('click', () => window.deleteProjectFile(item.path));
    entry.append(row, remove);
    listEl.appendChild(entry);
  });
}

window.loadProjectFileListing = async function (relativePath = '') {
  const projectName = window.AppState.fileEditorProject;
  if (!projectName) return;

  showProjectFileEditorError(null);
  try {
    const query = encodeURIComponent(relativePath || '');
    const { payload, ok } = await window.fetchApi(`/api/projects/${encodeURIComponent(projectName)}/files?path=${query}`, { cache: 'no-store' });
    if (!ok) {
      showProjectFileEditorError(payload.error || 'Unable to load file listing.');
      return;
    }
    renderProjectFileListing(payload);
  } catch (error) {
    showProjectFileEditorError('Unable to load file listing.');
  }
};

window.loadProjectFileContent = async function (relativePath) {
  const projectName = window.AppState.fileEditorProject;
  if (!projectName) return;

  showProjectFileEditorError(null);
  try {
    const query = encodeURIComponent(relativePath || '');
    const { payload, ok } = await window.fetchApi(`/api/projects/${encodeURIComponent(projectName)}/file?path=${query}`, { cache: 'no-store' });
    if (!ok) {
      showProjectFileEditorError(payload.error || 'Unable to open file.');
      return;
    }

    window.AppState.fileEditorCurrentFile = payload.path || relativePath;
    const filePathEl = document.getElementById('project-file-editor-current-file');
    if (filePathEl) filePathEl.textContent = window.AppState.fileEditorCurrentFile;
    const editor = document.getElementById('project-file-editor-content');
    if (editor) editor.value = payload.content || '';
  } catch (error) {
    showProjectFileEditorError('Unable to open file.');
  }
};

window.saveProjectFileContent = async function () {
  const projectName = window.AppState.fileEditorProject;
  const filePath = window.AppState.fileEditorCurrentFile;
  const editor = document.getElementById('project-file-editor-content');
  if (!projectName || !filePath || !editor) {
    showProjectFileEditorError('Select a file before saving.');
    return;
  }

  showProjectFileEditorError(null);
  try {
    const response = await fetch(`/api/projects/${encodeURIComponent(projectName)}/file`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: filePath,
        content: editor.value,
      }),
    });

    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      showProjectFileEditorError(payload.error || 'Unable to save file.');
      return;
    }

    window.logToTerminal('PROJECTS', `Saved file ${filePath} in ${projectName}.`, 'text-emerald-400 font-bold');
  } catch (error) {
    showProjectFileEditorError('Unable to save file.');
  }
};

async function projectFileMutation(endpoint, method, payload, queryPath) {
  const projectName = window.AppState.fileEditorProject;
  if (!projectName) return false;
  showProjectFileEditorError(null);
  const query = queryPath ? `?path=${encodeURIComponent(queryPath)}` : '';
  try {
    const response = await fetch(`/api/projects/${encodeURIComponent(projectName)}/${endpoint}${query}`, {
      method,
      headers: payload ? { 'Content-Type': 'application/json' } : undefined,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      showProjectFileEditorError(result.error || 'Unable to update project files.');
      return false;
    }
    return true;
  } catch (error) {
    showProjectFileEditorError('Unable to update project files.');
    return false;
  }
}

window.createProjectFile = async function () {
  const name = window.prompt('New file name (relative to the current folder):');
  if (!name || !name.trim()) return;
  const relativePath = [window.AppState.fileEditorPath, name.trim()].filter(Boolean).join('/');
  if (!await projectFileMutation('file', 'POST', { path: relativePath, content: '' })) return;
  await window.loadProjectFileListing(window.AppState.fileEditorPath);
  await window.loadProjectFileContent(relativePath);
};

window.createProjectFolder = async function () {
  const name = window.prompt('New folder name (relative to the current folder):');
  if (!name || !name.trim()) return;
  const relativePath = [window.AppState.fileEditorPath, name.trim()].filter(Boolean).join('/');
  if (!await projectFileMutation('folder', 'POST', { path: relativePath })) return;
  await window.loadProjectFileListing(window.AppState.fileEditorPath);
};

window.selectProjectFilesToUpload = function () {
  document.getElementById('project-file-upload-input')?.click();
};

window.uploadProjectFiles = async function (files) {
  const projectName = window.AppState.fileEditorProject;
  const fileInput = document.getElementById('project-file-upload-input');
  if (!projectName || !files || !files.length) return;

  showProjectFileEditorError(null);
  const formData = new FormData();
  formData.append('path', window.AppState.fileEditorPath || '');
  Array.from(files).forEach(file => formData.append('project_files', file, file.name));

  try {
    const response = await fetch(`/api/projects/${encodeURIComponent(projectName)}/files`, {
      method: 'POST',
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      showProjectFileEditorError(payload.error || 'Unable to upload files.');
      return;
    }
    window.logToTerminal('PROJECTS', `Uploaded ${payload.files.length} file(s) to ${projectName}.`, 'text-emerald-400 font-bold');
    await window.loadProjectFileListing(window.AppState.fileEditorPath);
  } catch (error) {
    showProjectFileEditorError('Unable to upload files.');
  } finally {
    if (fileInput) fileInput.value = '';
  }
};

window.deleteProjectFile = async function (relativePath) {
  if (!window.confirm(`Permanently delete file "${relativePath}"?`)) return;
  if (!await projectFileMutation('file', 'DELETE', null, relativePath)) return;
  if (window.AppState.fileEditorCurrentFile === relativePath) {
    window.AppState.fileEditorCurrentFile = '';
    document.getElementById('project-file-editor-current-file').textContent = 'NO FILE SELECTED';
    document.getElementById('project-file-editor-content').value = '';
  }
  await window.loadProjectFileListing(window.AppState.fileEditorPath);
};

window.deleteProjectFolder = async function (relativePath) {
  if (!window.confirm(`Permanently delete folder "${relativePath}" and everything inside it?`)) return;
  if (!await projectFileMutation('folder', 'DELETE', null, relativePath)) return;
  const currentPath = String(window.AppState.fileEditorPath || '');
  if (currentPath === relativePath || currentPath.startsWith(`${relativePath}/`)) {
    const parent = relativePath.split('/').slice(0, -1).join('/');
    await window.loadProjectFileListing(parent);
  } else {
    await window.loadProjectFileListing(currentPath);
  }
};

window.openProjectFileEditor = async function (projectName) {
  const name = String(projectName || '').trim();
  if (!name) return;

  window.AppState.fileEditorProject = name;
  window.AppState.fileEditorPath = '';
  window.AppState.fileEditorCurrentFile = '';
  const modal = document.getElementById('project-file-editor-modal');
  const title = document.getElementById('project-file-editor-project');
  const filePathEl = document.getElementById('project-file-editor-current-file');
  const editor = document.getElementById('project-file-editor-content');
  if (title) title.textContent = name;
  if (filePathEl) filePathEl.textContent = 'NO FILE SELECTED';
  if (editor) editor.value = '';
  showProjectFileEditorError(null);
  if (modal) modal.classList.remove('hidden');
  await window.loadProjectFileListing('');
};

window.navigateProjectFileEditorUp = function () {
  const current = String(window.AppState.fileEditorPath || '').trim();
  if (!current) return;
  const parts = current.split('/').filter(Boolean);
  parts.pop();
  window.loadProjectFileListing(parts.join('/'));
};

