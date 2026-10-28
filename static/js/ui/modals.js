// Log files, remove, stop and shutdown modals (split from ui.js)

let logFilesService = null;
let logFilesRequest = null;

window.closeLogFiles = function () {
  logFilesService = null;
  logFilesRequest?.abort();
  document.getElementById('log-files-modal')?.classList.add('hidden');
};

window.openLogFiles = async function (serviceName) {
  logFilesRequest?.abort();
  const controller = new AbortController();
  logFilesRequest = controller;
  logFilesService = serviceName;
  const modal = document.getElementById('log-files-modal');
  const list = document.getElementById('log-files-list');
  const status = document.getElementById('log-files-status');
  const download = document.getElementById('log-file-download');
  document.getElementById('log-files-service').textContent = serviceName;
  list.replaceChildren();
  status.textContent = 'Loading log files...';
  download.removeAttribute('href');
  download.setAttribute('aria-disabled', 'true');
  download.classList.add('pointer-events-none', 'opacity-50');
  modal.classList.remove('hidden');
  try {
    const endpoint = `/api/services/${encodeURIComponent(serviceName)}/logs`;
    const response = await fetch(endpoint, { signal: controller.signal, cache: 'no-store' });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to load log files.');
    if (controller.signal.aborted) return;
    const files = data.files || [];
    status.textContent = files.length ? `${files.length} log files` : 'No stored log files available.';
    files.forEach(file => {
      const row = document.createElement('label');
      row.className = 'flex items-start gap-3 py-3 border-b border-cyan-900/40 cursor-pointer';
      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'pm2-log-file';
      radio.value = file.id;
      radio.className = 'mt-1 shrink-0 accent-cyan-400';
      const details = document.createElement('span');
      details.className = 'min-w-0 flex-1';
      const filename = document.createElement('span');
      filename.className = 'block break-all text-cyan-100';
      filename.textContent = file.name;
      const metadata = document.createElement('span');
      metadata.className = 'block mt-1 text-cyan-600';
      metadata.textContent = `PM2 ID ${file.instance ?? 'N/A'} / ${file.type.toUpperCase()} / ${Number(file.size).toLocaleString()} bytes`;
      details.append(filename, metadata);
      row.append(radio, details);
      radio.addEventListener('change', () => {
        download.href = `${endpoint}?file=${encodeURIComponent(file.id)}`;
        download.setAttribute('download', file.name);
        download.setAttribute('aria-disabled', 'false');
        download.classList.remove('pointer-events-none', 'opacity-50');
      });
      list.appendChild(row);
    });
  } catch (error) {
    if (error.name !== 'AbortError') status.textContent = error.message || 'Unable to load log files.';
  }
};

window.refreshLogFiles = function () {
  if (logFilesService) window.openLogFiles(logFilesService);
};

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && logFilesService) window.closeLogFiles();
});

// 1. REMOVE MODAL
window.promptRemoveService = function (serviceName) {
  window.AppState.serviceToRemove = serviceName;
  const deleteLogs = document.getElementById('remove-delete-logs');
  if (deleteLogs) deleteLogs.checked = true;
  const target = document.getElementById('remove-target-name');
  if (target) target.textContent = serviceName;
  document.getElementById('remove-modal')?.classList.remove('hidden');
};

window.closeRemoveModal = function () {
  window.AppState.serviceToRemove = null;
  const deleteLogs = document.getElementById('remove-delete-logs');
  if (deleteLogs) deleteLogs.checked = true;
  document.getElementById('remove-modal')?.classList.add('hidden');
};

window.confirmRemoveService = function () {
  if (window.AppState.serviceToRemove && window.AppState.socket) {
    const deleteLogs = document.getElementById('remove-delete-logs')?.checked;
    const deleteLogOption = deleteLogs ? ' --delete-logs' : ' --keep-logs';
    window.AppState.socket.emit('ui_command', { command: `delete ${window.AppState.serviceToRemove}${deleteLogOption}` });
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
    window.runServiceOperation('stop', window.AppState.serviceToStop, `stop ${window.AppState.serviceToStop}`);
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

