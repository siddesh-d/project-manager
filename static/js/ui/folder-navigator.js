// Folder navigator (split from ui.js)

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

