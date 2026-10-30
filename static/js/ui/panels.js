// Panels, metric graphs and settings toggle (split from ui.js)

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
  ['pw-current', 'pw-new', 'pw-confirm'].forEach((id) => { const el = document.getElementById(id); if (el) el.value = ''; });
  document.getElementById('pw-message')?.classList.add('hidden');
  document.getElementById('settings-modal')?.classList.toggle('hidden');
};

window.submitPasswordChange = async function () {
  const current = document.getElementById('pw-current');
  const next = document.getElementById('pw-new');
  const confirm = document.getElementById('pw-confirm');
  const messageEl = document.getElementById('pw-message');
  const show = (text, ok) => {
    if (!messageEl) return;
    messageEl.textContent = text;
    messageEl.classList.remove('hidden', 'text-red-400', 'text-emerald-400');
    messageEl.classList.add(ok ? 'text-emerald-400' : 'text-red-400');
  };
  if (!current.value || !next.value || !confirm.value) return show('All password fields are required.', false);
  if (next.value !== confirm.value) return show('New password and confirmation do not match.', false);

  try {
    const { payload, ok } = await window.fetchApi('/api/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: current.value, new_password: next.value, confirm_password: confirm.value }),
    });
    if (!ok) return show(payload.error || 'Unable to change password.', false);
    [current, next, confirm].forEach((el) => { el.value = ''; });
    show(payload.message || 'Password updated successfully.', true);
  } catch (error) {
    show('Unable to change password.', false);
  }
};

