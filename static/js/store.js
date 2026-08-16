// ============================================================================
// SYSTEM PREFERENCES & STATE PERSISTENCE (store.js)
// ============================================================================

const defaultSettings = {
  engine: 'browser',
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

// Safely load settings to prevent JSON parse crashes
let savedSettings = defaultSettings;
try {
  const parsed = JSON.parse(localStorage.getItem('jarvisSettings'));
  if (parsed) savedSettings = normalizeClientSettings(parsed);
} catch (e) {
  console.warn("Failed to load settings from localStorage. Using defaults.", e);
}

try {
  localStorage.setItem('jarvisSettings', JSON.stringify(savedSettings));
} catch (e) {
  console.error("Storage error:", e);
}

// Global App State
window.AppState = {
  settings: savedSettings,
  socket: null,
  activeLogService: null,
  isLogPanelOpen: false,
  isAmrPanelOpen: true,
  prevAmrTotal: -1,
  serviceToRemove: null,
  sessionSeconds: 0,
  projects: [],
  folderPath: null,
  folderParent: null,
  folderListing: null,
  folderSelectTarget: 'proj-path',
  coreProjectPath: '',
  editingProject: null,
  uploadSelectionMap: {},
  isConsolePanelOpen: true,
  cpuHistory: [],
  memHistory: []
};

// Sync State across storage and backend safely
window.setSetting = function (key, val) {
  key = settingsAliases[key] || key;
  if (!(key in defaultSettings)) return;

  if (window.AppState.settings[key] === val) {
    if (typeof window.renderSettingsUI === 'function') {
      window.renderSettingsUI();
    }
    return;
  }

  window.AppState.settings[key] = val;
  window.AppState.settings = normalizeClientSettings(window.AppState.settings);
  try {
    localStorage.setItem('jarvisSettings', JSON.stringify(window.AppState.settings));
  } catch (e) { console.error("Storage error:", e); }

  if (window.AppState.socket) {
    window.AppState.socket.emit('ui_command', { command: `sys_setting:${key}:${val}` });
  }
  if (typeof window.renderSettingsUI === 'function') {
    window.renderSettingsUI();
  }
};

window.toggleSetting = function (key) {
  window.setSetting(key, !window.AppState.settings[key]);
};