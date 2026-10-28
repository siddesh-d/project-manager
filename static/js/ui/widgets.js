// Circular widgets (split from ui.js)

// --- CIRCULAR WIDGETS ---
const CIRC_MAX = 150.7;
window.setCircleData = function (elementId, textId, value, max, formatStr, colorClass) {
  const percent = max === 0 ? 0 : Math.min(Math.max((value / max) * 100, 0), 100);
  const offset = CIRC_MAX - (percent / 100) * CIRC_MAX;
  const circ = document.getElementById(elementId);
  const txt = document.getElementById(textId);
  if (circ && txt) {
    circ.style.strokeDashoffset = offset;
    circ.className.baseVal = `${colorClass} circle-transition`;
    txt.textContent = `${value}${formatStr}`;
  }
};

