// Clock and terminal log output (split from ui.js)

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

