// Service lifecycle, logs and settings UI (split from ui.js)

// --- SERVICE LIFECYCLE OPERATIONS (start / stop / restart) ---
const OP_LABELS = {
  start: { busy: 'Starting...', done: 'started' },
  stop: { busy: 'Stopping...', done: 'stopped' },
  restart: { busy: 'Restarting...', done: 'restarted' },
};
const OP_POLL_MS = 3000; // how often the UI asks the backend for the live stage
window.AppState.pendingOps = window.AppState.pendingOps || {};
const opFailures = {};

window.getPendingOp = function (serviceName) {
  return window.AppState.pendingOps[serviceName]?.action || null;
};

window.noteOpResult = function (serviceName, result) {
  if (window.AppState.pendingOps[serviceName] && result && !result.ok) {
    opFailures[serviceName] = (result.message || 'Operation failed.').toString();
  }
};

// Reflects pending operations on the service cards: disables buttons and shows a status line.
window.applyPendingOps = function () {
  document.querySelectorAll('[data-core-card="1"]').forEach(card => {
    const name = card.getAttribute('data-service-name');
    const op = window.getPendingOp(name);
    let line = card.querySelector('[data-role="op-status"]');
    card.querySelectorAll('[data-svc-action]').forEach(btn => { btn.disabled = !!op; btn.classList.toggle('opacity-50', !!op); btn.classList.toggle('cursor-not-allowed', !!op); });
    if (!op) { line?.remove(); return; }
    if (!line) {
      line = document.createElement('div');
      line.setAttribute('data-role', 'op-status');
      line.className = 'flex items-center gap-1.5 text-[9px] text-amber-400 uppercase tracking-widest mb-1';
      line.setAttribute('role', 'status');
      const anchor = card.querySelector('[data-role="service-path"]');
      if (anchor) anchor.insertAdjacentElement('afterend', line);
      else card.appendChild(line);
    }
    line.innerHTML = '<span class="inline-block w-2.5 h-2.5 border border-amber-400 border-t-transparent rounded-full animate-spin"></span><span></span>';
    line.lastChild.textContent = OP_LABELS[op].busy;
  });
};

window.runServiceOperation = function (action, serviceName, command) {
  const pending = window.getPendingOp(serviceName);
  if (pending) {
    window.logToTerminal('UI_OVERRIDE', `${serviceName} is busy (${OP_LABELS[pending].busy.replace('...', '').toLowerCase()}). Please wait.`, 'text-amber-400 font-bold');
    return;
  }
  const socket = window.AppState.socket;
  if (!socket) return;

  const finish = (error) => {
    const entry = window.AppState.pendingOps[serviceName];
    if (!entry || entry.token !== token) return;
    clearInterval(entry.timer);
    delete window.AppState.pendingOps[serviceName];
    const failure = error || opFailures[serviceName];
    delete opFailures[serviceName];
    if (failure) window.logToTerminal('UI_OVERRIDE', `${action.toUpperCase()} failed for ${serviceName}: ${failure}`, 'text-red-400 font-bold');
    else window.logToTerminal('UI_OVERRIDE', `${serviceName} ${OP_LABELS[action].done} successfully.`, 'text-emerald-400 font-bold');
    window.applyPendingOps();
    socket.emit('get_projects');
  };

  const token = Symbol(serviceName);
  delete opFailures[serviceName];
  const entry = { action, token, stage: '' };
  // Completion is driven by the backend ack / project_start_result; this only polls the live stage.
  entry.timer = setInterval(() => {
    if (!socket.connected) { finish('Connection to server lost.'); return; }
    socket.emit('get_op_status', { service: serviceName }, (res) => {
      const current = window.AppState.pendingOps[serviceName];
      if (!current || current.token !== token || !res || !res.ok || !res.stage || res.stage === current.stage) return;
      current.stage = res.stage;
      window.logToTerminal('UI_OVERRIDE', `Checked now: ${res.stage}`, 'text-cyan-400');
    });
  }, OP_POLL_MS);
  window.AppState.pendingOps[serviceName] = entry;
  window.logToTerminal('UI_OVERRIDE', `${OP_LABELS[action].busy.replace('...', '')} ${serviceName}...`, 'text-amber-400 font-bold');
  window.applyPendingOps();
  try {
    socket.emit('ui_command', { command }, (ack) => {
      finish(ack && ack.ok === false ? (ack.error || 'Command rejected.') : null);
    });
  } catch (err) {
    finish(err?.message || 'Request failed.');
  }
};

// --- ACTION BUTTON ROUTERS ---
window.serviceAction = function (action, serviceName) {
  if (action === 'start') {
    window.openStartServiceModal(serviceName);
  } else if (action === 'log') {
    window.toggleLogs(serviceName);
  } else if (action === 'flush') {
    window.logToTerminal('UI_OVERRIDE', `Clearing PM2 logs for ${serviceName}`, 'text-zinc-400 font-bold');
    window.AppState.socket?.emit('ui_command', { command: `flush ${serviceName}` });
  } else {
    window.runServiceOperation(action, serviceName, `${action} ${serviceName}`);
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
