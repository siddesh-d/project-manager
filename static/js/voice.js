// ============================================================================
// BROWSER VOICE ENGINE (STT & TTS) (voice.js)
// ============================================================================

window.currentInteractionState = 'IDLE';
window.isSpeakingTTS = false;
window.isBrowserListening = false;
let availableVoices = [];

// --- TTS VOICES ---
if (window.speechSynthesis) {
  const loadVoices = () => {
    availableVoices = window.speechSynthesis.getVoices();
    const sel = document.getElementById('sel-voice');
    if (sel && availableVoices.length > 0 && sel.options.length <= 1) {
      sel.innerHTML = '<option value="">DEFAULT SYSTEM VOICE</option>';
      availableVoices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.voiceURI;
        opt.textContent = `${v.name} (${v.lang})`;
        sel.appendChild(opt);
      });
      sel.value = window.AppState.settings.voiceURI;
    }
  };
  loadVoices();
  window.speechSynthesis.onvoiceschanged = loadVoices;
}

window.setInteractionState = function (state, textColorClass, dotColorClass) {
  window.currentInteractionState = state;
  const textEl = document.getElementById('state-text');
  const dotEl = document.getElementById('state-dot');
  if (textEl && dotEl) {
    textEl.textContent = state;
    textEl.className = textColorClass;
    dotEl.className = `w-1.5 h-1.5 rounded-full ${dotColorClass}`;
  }
};

window.speakBrowserResponse = function (text) {
  if (window.AppState.settings.engine !== 'browser' || !window.AppState.settings.speaker || !window.speechSynthesis) return;

  const cleanText = text.replace(/\[.*?\]/g, '').trim();
  if (!cleanText) return;

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.volume = window.AppState.settings.volume;
  utterance.rate = window.AppState.settings.rate;

  if (window.AppState.settings.voiceURI && availableVoices.length > 0) {
    const matchingVoice = availableVoices.find(v => v.voiceURI === window.AppState.settings.voiceURI);
    if (matchingVoice) utterance.voice = matchingVoice;
  }

  utterance.onstart = () => {
    window.isSpeakingTTS = true;
    if (window.recognition && window.isBrowserListening) { try { window.recognition.stop(); } catch (e) { } }
    window.setInteractionState('SPEAKING', 'text-emerald-400', 'bg-emerald-400 animate-pulse');
  };

  utterance.onend = () => {
    window.isSpeakingTTS = false;
    window.setInteractionState('IDLE', 'text-cyan-600', 'bg-cyan-600');
    if (window.AppState.settings.autolisten && window.AppState.settings.mic && window.AppState.settings.engine === 'browser') {
      try { window.recognition.start(); } catch (e) { }
    }
  };
  window.speechSynthesis.speak(utterance);
};

// --- STT (SPEECH RECOGNITION) ---
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognition) {
  window.recognition = new SpeechRecognition();
  window.recognition.continuous = false;
  window.recognition.interimResults = true;

  // UPDATED: Hardcoded locale to English (India) to fix voice tracking/accents
  window.recognition.lang = 'en-IN';

  window.recognition.onstart = () => {
    window.isBrowserListening = true;
    window.setInteractionState('LISTENING', 'text-amber-400', 'bg-amber-400 animate-pulse');

    // Trigger UI theme changes and activate the animation ping ring
    const micBtn = document.getElementById('btn-browser-mic');
    const micPing = document.getElementById('mic-ping');
    if (micBtn) {
      micBtn.classList.remove('btn-ui-cyan');
      micBtn.classList.add('btn-ui-amber');
    }
    if (micPing) micPing.classList.remove('hidden');
  };

  window.recognition.onresult = (event) => {
    let interimTranscript = '';
    let finalTranscript = '';

    // Sort out which text is final and which is actively being transcribed
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      if (event.results[i].isFinal) {
        finalTranscript += event.results[i][0].transcript;
      } else {
        interimTranscript += event.results[i][0].transcript;
      }
    }

    const inputObj = document.getElementById('command-input');
    if (inputObj) {
      // Display whichever transcript is currently active so user sees real-time input
      inputObj.value = finalTranscript || interimTranscript;
    }

    window.setInteractionState('PROCESSING', 'text-cyan-300', 'bg-cyan-300 animate-pulse');

    // Only trigger the auto-submit once the system is confident the user stopped speaking
    if (finalTranscript) {
      setTimeout(() => document.getElementById('command-form')?.dispatchEvent(new Event('submit')), 300);
    }
  };

  window.recognition.onerror = (event) => {
    window.setInteractionState('IDLE', 'text-cyan-600', 'bg-cyan-600');

    // Deactivate UI animation elements on error
    const micBtn = document.getElementById('btn-browser-mic');
    const micPing = document.getElementById('mic-ping');
    if (micBtn) {
      micBtn.classList.remove('btn-ui-amber');
      micBtn.classList.add('btn-ui-cyan');
    }
    if (micPing) micPing.classList.add('hidden');

    window.isBrowserListening = false;
  };

  window.recognition.onend = () => {
    window.isBrowserListening = false;

    // Deactivate UI animation elements gracefully
    const micBtn = document.getElementById('btn-browser-mic');
    const micPing = document.getElementById('mic-ping');
    if (micBtn) {
      micBtn.classList.remove('btn-ui-amber');
      micBtn.classList.add('btn-ui-cyan');
    }
    if (micPing) micPing.classList.add('hidden');

    if (window.currentInteractionState === 'LISTENING' || window.currentInteractionState === 'PROCESSING') {
      window.setInteractionState('IDLE', 'text-cyan-600', 'bg-cyan-600');
    }
  };
}

// --- MIC FIX: EXPLICIT PERMISSION REQUEST ---
window.toggleBrowserVoiceInput = async function () {
  if (window.AppState.settings.engine !== 'browser') {
    window.logToTerminal('SYS_ERR', "Cannot start mic. Voice Engine is set to LEGACY.", 'text-amber-400 font-bold');
    return;
  }
  if (!window.AppState.settings.mic) {
    window.logToTerminal('SYS_ERR', "Microphone is currently OFF in Settings.", 'text-amber-400 font-bold');
    return;
  }
  if (!window.recognition) {
    window.logToTerminal('SYS_ERR', "Web Speech API is not supported in this browser.", 'text-red-500 font-bold');
    return;
  }

  if (window.isBrowserListening) {
    window.recognition.stop();
  } else {
    try {
      // Force the browser permission prompt
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Immediately stop the manual stream so the Speech Engine can claim it
      stream.getTracks().forEach(track => track.stop());

      window.speechSynthesis.cancel();
      window.recognition.start();
    } catch (err) {
      window.logToTerminal('SYS_ERR', `Mic access blocked: ${err.message}. HTTPS or localhost required.`, 'text-red-500 font-bold animate-pulse');
    }
  }
};



