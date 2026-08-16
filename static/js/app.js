// ============================================================================
// SYSTEM PREFERENCES & PERSISTENCE
// ============================================================================
const defaultSettings = {
  engine: 'browser', // 'browser' or 'legacy'
  mic: false,
  speaker: false,
  autolisten: false,
  voiceURI: '',
  volume: 1.0,
  rate: 1.0,
  theme: 'dark'
};

const settingsAliases = {
  voiceuri: 'voiceURI'
};

function normalizeClientSettings(raw) {
  const normalized = { ...defaultSettings };
  if (!raw || typeof raw !== 'object') return normalized;

  const merged = { ...raw };
  Object.keys(settingsAliases).forEach(oldKey => {
    const newKey = settingsAliases[oldKey];
    if (!(newKey in merged) && oldKey in merged) merged[newKey] = merged[oldKey];
  });

  Object.keys(defaultSettings).forEach(key => {
    if (key in merged) normalized[key] = merged[key];
  });

  normalized.engine = (normalized.engine === 'legacy') ? 'legacy' : 'browser';
  normalized.mic = Boolean(normalized.mic);
  normalized.speaker = Boolean(normalized.speaker);
  normalized.autolisten = Boolean(normalized.autolisten);
  normalized.voiceURI = (normalized.voiceURI ?? '').toString();
  normalized.theme = (normalized.theme === 'light') ? 'light' : 'dark';

  const volumeNum = Number(normalized.volume);
  normalized.volume = Number.isFinite(volumeNum) ? volumeNum : defaultSettings.volume;

  const rateNum = Number(normalized.rate);
  normalized.rate = Number.isFinite(rateNum) ? rateNum : defaultSettings.rate;

  return normalized;
}

// Load from LocalStorage
let sysSettings = defaultSettings;
try {
  const parsed = JSON.parse(localStorage.getItem('jarvisSettings'));
  if (parsed) sysSettings = normalizeClientSettings(parsed);
} catch (e) {
  console.warn("Failed to load settings from localStorage. Using defaults.", e);
}

try {
  localStorage.setItem('jarvisSettings', JSON.stringify(sysSettings));
} catch (e) {
  console.error("Storage error:", e);
}

if (typeof window.applyTheme === 'function') {
  window.applyTheme(sysSettings.theme || 'dark');
} else {
  document.documentElement.setAttribute('data-theme', (sysSettings.theme === 'light') ? 'light' : 'dark');
}

// Save & Sync across to Backend
window.setSetting = function (key, val) {
  key = settingsAliases[key] || key;
  if (!(key in defaultSettings)) return;

  if (sysSettings[key] === val) {
    renderSettingsUI();
    return;
  }

  sysSettings[key] = val;
  sysSettings = normalizeClientSettings(sysSettings);
  localStorage.setItem('jarvisSettings', JSON.stringify(sysSettings));
  if (key === 'theme') {
    if (typeof window.applyTheme === 'function') {
      window.applyTheme(sysSettings.theme);
    } else {
      document.documentElement.setAttribute('data-theme', sysSettings.theme);
    }
  }
  socket.emit('ui_command', { command: `sys_setting:${key}:${val}` });
  renderSettingsUI();
};

window.toggleSetting = function (key) {
  setSetting(key, !sysSettings[key]);
};

// Render Settings Modal matching state
function renderSettingsUI() {
  if (typeof window.applyTheme === 'function') {
    window.applyTheme(sysSettings.theme || 'dark');
  }

  // Engine Toggle
  const btnB = document.getElementById('btn-eng-browser');
  const btnL = document.getElementById('btn-eng-legacy');
  if (sysSettings.engine === 'browser') {
    btnB.className = "px-4 py-1.5 text-[9px] font-bold tracking-widest border transition-all bg-emerald-950/60 text-emerald-400 border-emerald-800";
    btnL.className = "px-4 py-1.5 text-[9px] font-bold tracking-widest border transition-all bg-black text-cyan-600 border-cyan-900";
  } else {
    btnL.className = "px-4 py-1.5 text-[9px] font-bold tracking-widest border transition-all bg-emerald-950/60 text-emerald-400 border-emerald-800";
    btnB.className = "px-4 py-1.5 text-[9px] font-bold tracking-widest border transition-all bg-black text-cyan-600 border-cyan-900";
  }

  // Buttons
  const updateBtn = (id, val, textOn = "ON", textOff = "OFF") => {
    const btn = document.getElementById(id);
    if (val) {
      btn.className = "px-5 py-1.5 text-[9px] font-bold tracking-widest border transition-all bg-emerald-950/60 text-emerald-400 border-emerald-800";
      btn.textContent = textOn;
    } else {
      btn.className = "px-5 py-1.5 text-[9px] font-bold tracking-widest border transition-all bg-black text-cyan-600 border-cyan-900";
      btn.textContent = textOff;
    }
  };
  updateBtn('btn-set-mic', sysSettings.mic);
  updateBtn('btn-set-speaker', sysSettings.speaker);
  updateBtn('btn-set-autolisten', sysSettings.autolisten);

  // Sliders
  document.getElementById('slide-volume').value = sysSettings.volume;
  document.getElementById('lbl-volume').textContent = `${Math.round(sysSettings.volume * 100)}%`;
  document.getElementById('slide-rate').value = sysSettings.rate;
  document.getElementById('lbl-rate').textContent = `${sysSettings.rate.toFixed(1)}x`;

  // Top Header Badges
  const micBadge = document.getElementById('status-mic');
  if (micBadge) {
    micBadge.className = sysSettings.mic
      ? 'inline-flex items-center justify-center status-chip-up border px-2 py-0.5 font-bold'
      : 'inline-flex items-center justify-center status-chip-down border px-2 py-0.5 font-bold';
    micBadge.setAttribute('aria-label', sysSettings.mic ? 'Microphone is on' : 'Microphone is off');
    const micSlash = document.getElementById('status-mic-slash');
    if (micSlash) micSlash.classList.toggle('hidden', sysSettings.mic);
  }

  const audioBadge = document.getElementById('status-audio');
  if (audioBadge) {
    audioBadge.className = sysSettings.speaker
      ? 'inline-flex items-center justify-center status-chip-up border px-2 py-0.5 font-bold'
      : 'inline-flex items-center justify-center text-amber-400 border border-amber-600 px-2 py-0.5 bg-amber-950/30 font-bold';
    audioBadge.setAttribute('aria-label', sysSettings.speaker ? 'Speaker is on' : 'Speaker is muted');
    const audioWave = document.getElementById('status-audio-wave');
    if (audioWave) audioWave.classList.toggle('hidden', !sysSettings.speaker);
    const audioSlash = document.getElementById('status-audio-slash');
    if (audioSlash) audioSlash.classList.toggle('hidden', sysSettings.speaker);
  }
}

window.toggleSettingsModal = function () {
  renderSettingsUI();
  document.getElementById('settings-modal').classList.toggle('hidden');
};

// ============================================================================
// BROWSER-BASED VOICE INTERACTION (STT & TTS)
// ============================================================================
let currentInteractionState = 'IDLE';
let isSpeakingTTS = false;
let availableVoices = [];

// Load System Voices asynchronously
if (window.speechSynthesis) {
  const loadVoices = () => {
    availableVoices = window.speechSynthesis.getVoices();
    const sel = document.getElementById('sel-voice');
    if (availableVoices.length > 0 && sel.options.length <= 1) {
      sel.innerHTML = '<option value="">DEFAULT SYSTEM VOICE</option>';
      availableVoices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.voiceURI;
        opt.textContent = `${v.name} (${v.lang})`;
        sel.appendChild(opt);
      });
      sel.value = sysSettings.voiceURI;
    }
  };
  loadVoices();
  window.speechSynthesis.onvoiceschanged = loadVoices;
}

function setInteractionState(state, textColorClass, dotColorClass) {
  currentInteractionState = state;
  const textEl = document.getElementById('state-text');
  const dotEl = document.getElementById('state-dot');
  if (textEl && dotEl) {
    textEl.textContent = state;
    textEl.className = textColorClass;
    dotEl.className = `w-1.5 h-1.5 rounded-full ${dotColorClass}`;
  }
}

function speakBrowserResponse(text) {
  if (sysSettings.engine !== 'browser' || !sysSettings.speaker || !window.speechSynthesis) return;

  const cleanText = text.replace(/\[.*?\]/g, '').trim();
  if (!cleanText) return;

  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.volume = sysSettings.volume;
  utterance.rate = sysSettings.rate;

  if (sysSettings.voiceURI && availableVoices.length > 0) {
    const matchingVoice = availableVoices.find(v => v.voiceURI === sysSettings.voiceURI);
    if (matchingVoice) utterance.voice = matchingVoice;
  }

  utterance.onstart = () => {
    isSpeakingTTS = true;
    if (recognition && isBrowserListening) {
      try { recognition.stop(); } catch (e) { }
    }
    setInteractionState('SPEAKING', 'text-emerald-400', 'bg-emerald-400 animate-pulse');
  };

  utterance.onend = () => {
    isSpeakingTTS = false;
    setInteractionState('IDLE', 'text-cyan-600', 'bg-cyan-600');

    // Auto-Listen loop kick-off
    if (sysSettings.autolisten && sysSettings.mic && sysSettings.engine === 'browser') {
      try { recognition.start(); } catch (e) { }
    }
  };

  window.speechSynthesis.speak(utterance);
}

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let isBrowserListening = false;

if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  recognition.onstart = () => {
    isBrowserListening = true;
    setInteractionState('LISTENING', 'text-amber-400', 'bg-amber-400 animate-pulse');
    document.getElementById('btn-browser-mic').classList.add('bg-amber-900/80', 'border-amber-500', 'text-amber-300');
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    document.getElementById('command-input').value = transcript;
    setInteractionState('PROCESSING', 'text-cyan-300', 'bg-cyan-300 animate-pulse');
    setTimeout(() => document.getElementById('command-form').dispatchEvent(new Event('submit')), 300);
  };

  recognition.onerror = (event) => {
    console.error("Browser STT Error: ", event.error);
    if (event.error === 'not-allowed') {
      logToTerminal('SYS_ERR', "Microphone access denied! If not using 'localhost', HTTPS is required by the browser.", 'text-red-500 font-bold');
    } else {
      logToTerminal('SYS_ERR', `Microphone error: ${event.error}`, 'text-red-500');
    }
    setInteractionState('IDLE', 'text-cyan-600', 'bg-cyan-600');
    document.getElementById('btn-browser-mic').classList.remove('bg-amber-900/80', 'border-amber-500', 'text-amber-300');
    isBrowserListening = false;
  };

  recognition.onend = () => {
    isBrowserListening = false;
    document.getElementById('btn-browser-mic').classList.remove('bg-amber-900/80', 'border-amber-500', 'text-amber-300');
    if (currentInteractionState === 'LISTENING') setInteractionState('IDLE', 'text-cyan-600', 'bg-cyan-600');

    // Auto-listen loop continuation (if no TTS is speaking)
    if (!isSpeakingTTS && sysSettings.autolisten && sysSettings.mic && sysSettings.engine === 'browser') {
      try { recognition.start(); } catch (e) { }
    }
  };
}

// THE FIX: Explicitly request permission before starting recognition to force the browser UI prompt
window.toggleBrowserVoiceInput = function () {
  if (sysSettings.engine !== 'browser') {
    logToTerminal('SYS', "Cannot start mic. Voice Engine is set to LEGACY in Settings.", 'text-amber-400 font-bold');
    return;
  }
  if (!sysSettings.mic) {
    logToTerminal('SYS', "Microphone is currently OFF in Settings.", 'text-amber-400 font-bold');
    return;
  }
  if (!recognition) {
    logToTerminal('SYS', "Browser Speech API is not supported in this browser.", 'text-red-500 font-bold');
    return;
  }

  if (isBrowserListening) {
    recognition.stop();
  } else {
    // Force the browser permission dialogue
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then((stream) => {
        window.speechSynthesis.cancel();
        try { recognition.start(); } catch (e) { }
      })
      .catch((err) => {
        logToTerminal('SYS_ERR', `Microphone access blocked: ${err.message}. Web Speech requires HTTPS or localhost.`, 'text-red-500 font-bold animate-pulse');
      });
  }
};

// ============================================================================
// CORE SYSTEM, UI ROUTING & SOCKETS
// ============================================================================

function updateClock() {
  const now = new Date();
  document.getElementById('digital-clock').textContent = now.toLocaleTimeString('en-US', { hour12: false });
}
setInterval(updateClock, 1000); updateClock();

const socket = io({ path: (window.APP_CONFIG && window.APP_CONFIG.SOCKET_PATH) || '/jarvis.io' });
const assistantLogLabel = (window.APP_CONFIG && window.APP_CONFIG.ASSISTANT_LOG_LABEL) || 'QUASON';
const terminalStream = document.getElementById('terminal-stream');
const serviceLogStream = document.getElementById('service-log-stream');
const logConnectionStatus = document.getElementById('log-connection-status');
const coreContainer = document.getElementById('core-services-container');
const amrContainer = document.getElementById('amr-services-container');
const commandInput = document.getElementById('command-input');

let activeLogService = null;
let isLogPanelOpen = false;
let isAmrPanelOpen = true;
let prevAmrTotal = -1;
let serviceToRemove = null;

// Initial settings render
renderSettingsUI();

// Keep UI in sync on connect; persist only on explicit setting changes.
socket.on('connect', () => {
  logToTerminal('SYS', 'Telemetry handshake verified. Link stable.', 'text-emerald-400');
  const wsBadge = document.getElementById('status-ws');
  wsBadge.className = 'status-chip-up border px-2 py-0.5 font-bold';
  wsBadge.textContent = 'WS: CONN';
});

socket.on('disconnect', () => {
  logToTerminal('SYS', 'WebSocket connection lost. Awaiting automatic reconnect...', 'text-red-500 font-bold');
  const wsBadge = document.getElementById('status-ws');
  wsBadge.className = 'status-chip-down border px-2 py-0.5 font-bold animate-pulse';
  wsBadge.textContent = 'WS: DROP';
});

socket.on('log_stream', (data) => {
  logToTerminal(data.source || assistantLogLabel, data.message, data.color || 'text-cyan-200');
  if (data.source === assistantLogLabel) speakBrowserResponse(data.message);
});

// Modals & Panels
window.promptRemoveService = function (s) { serviceToRemove = s; document.getElementById('remove-target-name').textContent = s; document.getElementById('remove-modal').classList.remove('hidden'); };
window.closeRemoveModal = function () { serviceToRemove = null; document.getElementById('remove-modal').classList.add('hidden'); };
window.confirmRemoveService = function () { if (serviceToRemove) { logToTerminal('UI_OVERRIDE', `Initiating REMOVE sequence for ${serviceToRemove}`, 'text-red-500 font-bold'); socket.emit('ui_command', { command: `delete ${serviceToRemove}` }); closeRemoveModal(); } };
window.toggleLogPanel = function () { isLogPanelOpen = !isLogPanelOpen; document.getElementById('dedicated-log-panel').classList.toggle('hidden'); document.getElementById('dedicated-log-panel').classList.toggle('flex'); document.getElementById('log-toggle-icon').textContent = isLogPanelOpen ? '[-]' : '[+]'; };
window.toggleAmrPanel = function (f = null) { isAmrPanelOpen = f !== null ? f : !isAmrPanelOpen; amrContainer.classList.toggle('hidden', !isAmrPanelOpen); document.getElementById('amr-panel').classList.toggle('flex-1', isAmrPanelOpen); document.getElementById('amr-toggle-icon').textContent = isAmrPanelOpen ? '[-]' : '[+]'; };
window.serviceAction = function (action, s) { if (action === 'log') toggleLogs(s); else if (action === 'flush') { logToTerminal('UI_OVERRIDE', `Clearing PM2 logs for ${s}`, 'text-zinc-400 font-bold'); socket.emit('ui_command', { command: `flush ${s}` }); } else { logToTerminal('UI_OVERRIDE', `Initiating ${action.toUpperCase()} sequence for ${s}`, 'text-amber-400 font-bold'); socket.emit('ui_command', { command: `${action} ${s}` }); } };
window.restoreCoreServices = function () { logToTerminal('UI_OVERRIDE', `Initiating bulk START sequence for all Core Services`, 'text-amber-400 font-bold'); socket.emit('ui_command', { command: 'start all' }); };

function toggleLogs(s) {
  if (activeLogService === s) { socket.emit('toggle_service_logs', { service: s, action: 'stop' }); activeLogService = null; logConnectionStatus.textContent = 'DISCONNECTED'; logConnectionStatus.className = 'text-[9px] text-amber-500 uppercase px-1 border border-amber-600 tracking-widest'; return; }
  if (activeLogService) socket.emit('toggle_service_logs', { service: activeLogService, action: 'stop' });
  if (!isLogPanelOpen) window.toggleLogPanel();
  activeLogService = s; serviceLogStream.innerHTML = ''; logConnectionStatus.textContent = `STREAMING: ${s}`; logConnectionStatus.className = 'text-[9px] text-emerald-400 uppercase px-1 border border-emerald-500 tracking-widest animate-pulse font-bold';
  socket.emit('toggle_service_logs', { service: s, action: 'start' });
}

document.getElementById('command-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const cmd = commandInput.value.trim();
  if (!cmd) return;
  logToTerminal('USER_INPUT', cmd, 'text-white font-bold');
  socket.emit('ui_command', { command: cmd });
  commandInput.value = '';
});

function logToTerminal(source, message, colorClass) {
  const entry = document.createElement('div');
  entry.className = `break-all ${colorClass} py-0.5 border-b border-cyan-900/20 last:border-0`;
  entry.innerHTML = `<span class="opacity-50 mr-2 text-[10px]">▪</span><span class="text-cyan-700 w-20 inline-block font-bold">[${source}]</span> ${message}`;
  terminalStream.appendChild(entry);
  terminalStream.scrollTop = terminalStream.scrollHeight;
}

socket.on('service_log_chunk', (data) => {
  if (data.service !== activeLogService) return;
  const line = data.log; const entry = document.createElement('div');
  let color = 'text-cyan-300'; const textLower = line.toLowerCase();
  if (textLower.includes('error') || textLower.includes('fail') || textLower.includes('exception')) color = 'text-red-400 font-bold bg-red-950/20';
  else if (textLower.includes('warn')) color = 'text-amber-300';
  else if (textLower.includes('info') || textLower.includes('success')) color = 'text-emerald-300';
  else if (textLower.includes('debug')) color = 'text-cyan-600';
  entry.className = `border-b border-cyan-900/20 py-0.5 last:border-0 ${color}`; entry.textContent = line;
  serviceLogStream.appendChild(entry); serviceLogStream.scrollTop = serviceLogStream.scrollHeight;
});

socket.on('pm2_telemetry', (services) => {
  coreContainer.innerHTML = ''; amrContainer.innerHTML = '';
  let coreCount = 0, coreOnline = 0, amrTotal = 0, amrOnline = 0, aggCpu = 0, aggMem = 0;

  services.forEach(srv => {
    const isRemoved = srv.status === 'removed';
    const isOnline = srv.status === 'online';
    const isAMR = srv.name.startsWith('amr-service-');
    let colorBase = isOnline ? (isAMR ? 'emerald' : 'cyan') : 'red';
    let statusClass = isOnline ? `text-${colorBase}-300` : 'text-red-500 bg-red-950/30';

    if (!isRemoved) { aggCpu += parseFloat(srv.cpu) || 0; aggMem += parseInt(srv.memory.replace('MB', '')) || 0; }

    let displayName = srv.name; let subText = `PORT // ${srv.port || 'UNK'}`;
    if (isAMR) {
      const parts = srv.name.replace('amr-service-', '').split('-');
      displayName = parts[0] || 'UNK'; subText = `SERIAL: ${parts[1] || 'UNK'}`;
      if (!isRemoved) { amrTotal++; if (isOnline) amrOnline++; }
    } else { coreCount++; if (isOnline) coreOnline++; }

    if (isRemoved) {
      const card = document.createElement('div');
      card.className = `flex flex-col p-2 bg-red-950/10 border border-red-900/40 border-dashed mb-1 opacity-80 shrink-0`;
      card.innerHTML = `<div class="flex justify-between items-start mb-1"><span class="text-[12px] font-bold text-zinc-500 uppercase tracking-wide truncate pr-2">${displayName} <span class="text-red-500/70 ml-1 text-[9px] tracking-widest">(NOT ACTIVE)</span></span><span class="text-[9px] text-red-500 bg-red-950/30 border border-red-800/50 px-1.5 uppercase shrink-0">REMOVED</span></div><div class="text-[9px] text-zinc-500/80 mb-3 italic leading-relaxed">This service was previously removed. You can restore it or clear its old logs.</div><div class="flex gap-1 pt-2 border-t border-red-900/30"><button onclick="serviceAction('start', '${srv.name}')" class="flex-[2] bg-black hover:bg-emerald-950/60 text-emerald-600 hover:text-emerald-400 text-[9px] py-1 border border-emerald-900/50 hover:border-emerald-500 transition-all font-bold tracking-widest">RESTORE SERVICE</button><button onclick="serviceAction('flush', '${srv.name}')" class="flex-1 bg-black hover:bg-zinc-900/80 text-zinc-500 hover:text-zinc-300 text-[9px] py-1 border border-zinc-800 hover:border-zinc-500 transition-all">CLEAR LOGS</button></div>`;
      isAMR ? amrContainer.appendChild(card) : coreContainer.appendChild(card); return;
    }

    const cpuWidth = Math.min(srv.cpu * 2, 100);
    const isLogging = (activeLogService === srv.name);
    const logBtnClass = isLogging ? `bg-${colorBase}-900/60 text-${colorBase}-300 border-${colorBase}-500 font-bold` : `bg-black hover:bg-${colorBase}-900/50 text-${colorBase}-600 border-${colorBase}-900 hover:border-${colorBase}-500`;

    let controlsHTML = isOnline
      ? `<div class="flex gap-1 mb-1"><button onclick="serviceAction('stop', '${srv.name}')" class="flex-1 bg-black hover:bg-amber-950/80 text-amber-600 hover:text-amber-400 text-[9px] py-1 border border-amber-900/50 transition-all">STOP</button><button onclick="serviceAction('restart', '${srv.name}')" class="flex-1 bg-black hover:bg-${colorBase}-950/80 text-${colorBase}-600 hover:text-${colorBase}-400 text-[9px] py-1 border border-${colorBase}-900/50 transition-all">RESTART</button><button onclick="promptRemoveService('${srv.name}')" class="flex-1 bg-black hover:bg-red-950/80 text-red-600 hover:text-red-400 text-[9px] py-1 border border-red-900/50 transition-all">REMOVE</button></div><div class="flex gap-1"><button onclick="serviceAction('log', '${srv.name}')" class="flex-1 transition-all text-[9px] py-1 border ${logBtnClass}">${isLogging ? 'STOP LOGS' : 'LOGS'}</button><button onclick="serviceAction('flush', '${srv.name}')" class="flex-1 bg-black hover:bg-zinc-900/80 text-zinc-500 hover:text-zinc-300 text-[9px] py-1 border border-zinc-800 transition-all">CLEAR LOGS</button></div>`
      : `<div class="flex gap-1 mb-1"><button onclick="serviceAction('start', '${srv.name}')" class="flex-[2] bg-black hover:bg-emerald-950/80 text-emerald-600 hover:text-emerald-400 text-[9px] py-1 border border-emerald-900/50 transition-all font-bold tracking-widest">START</button><button onclick="promptRemoveService('${srv.name}')" class="flex-1 bg-black hover:bg-red-950/80 text-red-600 hover:text-red-400 text-[9px] py-1 border border-red-900/50 transition-all">REMOVE</button></div><div class="flex gap-1"><button onclick="serviceAction('log', '${srv.name}')" class="flex-1 transition-all text-[9px] py-1 border ${logBtnClass}">${isLogging ? 'STOP LOGS' : 'LOGS'}</button><button onclick="serviceAction('flush', '${srv.name}')" class="flex-1 bg-black hover:bg-zinc-900/80 text-zinc-500 hover:text-zinc-300 text-[9px] py-1 border border-zinc-800 transition-all">CLEAR LOGS</button></div>`;

    const metadataRows = [];
    const addMetaRow = (label, value) => {
      if (value === undefined || value === null || value === '') return;
      metadataRows.push(`<div class="flex justify-between gap-2 text-[8px] text-${colorBase}-600"><span>${label}</span><span class="text-${colorBase}-400 text-right">${String(value)}</span></div>`);
    };
    addMetaRow('UPTIME', srv.uptime);
    addMetaRow('↺', srv.restarts);
    addMetaRow('USER', srv.user);
    addMetaRow('WATCH', srv.watching !== undefined ? (srv.watching ? 'ON' : 'OFF') : undefined);
    addMetaRow('PID', srv.pid);
    addMetaRow('NS', srv.namespace);
    addMetaRow('MODE', srv.mode);
    addMetaRow('VERSION', srv.version);

    const metadataHTML = metadataRows.length ? `<div class="mt-2 pt-2 border-t border-${colorBase}-900/40 space-y-1">${metadataRows.join('')}</div>` : '';
    const card = document.createElement('div');
    card.className = `flex flex-col p-2 bg-${colorBase}-950/10 border border-${colorBase}-900/40 mb-1 hover:border-${colorBase}-500/50 transition-colors shrink-0`;
    card.innerHTML = `<div class="flex justify-between items-start mb-1"><span class="text-[12px] font-bold text-${colorBase}-400 uppercase tracking-wide truncate pr-2">${displayName}</span><span class="text-[9px] ${statusClass} border border-${colorBase}-800/50 px-1.5 uppercase shrink-0">${srv.status}</span></div><div class="text-[9px] text-${colorBase}-600/80 mb-2">${subText}</div><div class="flex items-center gap-2 text-[9px] text-${colorBase}-500"><span class="w-8">CPU</span><div class="flex-1 h-1.5 bg-${colorBase}-950 border border-${colorBase}-900 relative"><div class="absolute left-0 top-0 h-full bg-${colorBase}-500 transition-all" style="width: ${cpuWidth}%"></div></div><span class="w-8 text-right">${srv.cpu}%</span></div><div class="flex justify-between mt-1 text-[9px] text-${colorBase}-600"><span>MEM_USAGE</span><span class="text-${colorBase}-400">${srv.memory}</span></div>${metadataHTML}<div class="mt-2 pt-2 border-t border-${colorBase}-900/40 flex flex-col">${controlsHTML}</div>`;
    isAMR ? amrContainer.appendChild(card) : coreContainer.appendChild(card);
  });

  document.getElementById('amr-count-header').textContent = `(${amrTotal})`;
  if (amrTotal !== prevAmrTotal) {
    if (amrTotal === 0 && isAmrPanelOpen) window.toggleAmrPanel(false);
    else if (amrTotal > 0 && !isAmrPanelOpen) window.toggleAmrPanel(true);
    prevAmrTotal = amrTotal;
  }

  if (coreCount === 0) {
    coreContainer.innerHTML = `<div class="flex flex-col items-center justify-center p-6 text-center h-full border border-dashed border-cyan-900/40 bg-cyan-950/20 gap-3"><div class="text-cyan-700/80 mb-1"><svg class="w-8 h-8 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"></path></svg></div><h3 class="text-xs font-bold tracking-[0.2em] text-cyan-500 uppercase">No Core Services Available</h3><p class="text-[9px] text-cyan-600 leading-relaxed max-w-[90%]">All Core PM2 services have been removed or are currently unavailable.<br><br>Start or restore the default Core Infrastructure services required for system operation.</p><button onclick="restoreCoreServices()" class="mt-3 bg-cyan-950/60 hover:bg-cyan-800 border border-cyan-700 hover:border-cyan-400 text-cyan-300 hover:text-white px-5 py-2 text-[10px] font-bold tracking-[0.2em] transition-all shadow-[0_0_10px_rgba(8,145,178,0.2)]">START CORE SERVICES</button></div>`;
  }
  if (amrTotal === 0 && isAmrPanelOpen) {
    amrContainer.innerHTML = `<div class="flex flex-col items-center justify-center p-4 text-center h-full border border-dashed border-emerald-900/30 bg-emerald-950/5"><span class="text-[9px] tracking-widest text-emerald-700 uppercase">No Virtual AMRs Active</span></div>`;
  }

  setCircleData('circ-cpu', 'val-cpu', Math.round(aggCpu), 100, '%', 'text-cyan-400');
  setCircleData('circ-mem', 'val-mem', aggMem, 4096, 'M', 'text-cyan-400');
  setCircleData('circ-core', 'val-core', coreOnline, coreCount, `/${coreCount}`, (coreOnline === coreCount && coreCount > 0) ? "text-cyan-400" : "text-red-500");
  setCircleData('circ-amr', 'val-amr', amrOnline, amrTotal, `/${amrTotal}`, (amrOnline === amrTotal && amrTotal > 0) ? "text-emerald-400" : "text-red-500");

  const healthEl = document.getElementById('stat-sys-health');
  if (coreCount === 0 && amrTotal === 0) { healthEl.textContent = "AWAITING TELEMETRY"; healthEl.className = "font-bold tracking-widest text-cyan-600"; }
  else if (coreOnline < coreCount || amrOnline < amrTotal) { healthEl.textContent = "SYSTEM DEGRADED"; healthEl.className = "font-bold tracking-widest text-red-500"; }
  else { healthEl.textContent = "SYSTEM OPTIMAL"; healthEl.className = "font-bold tracking-widest text-emerald-400"; }
});