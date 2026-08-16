import queue
import threading
import subprocess
import base64
import os
import shutil
from jarvis_assistant.config import ASSISTANT_LOG_LABEL

class JarvisVoiceEngine:
    def __init__(self, socketio=None):
        self.q = queue.Queue()
        self.running = True
        
        # ==========================================
        # SOCKET.IO BINDING FOR WEB UI REFLEXES
        # ==========================================
        self.socketio = socketio 
        
        # ==========================================
        # DEFAULT OVERRIDE: Muted by default for local hardware
        # ==========================================
        self.muted = True 
        self._warned_no_local_tts = False
        
        self.thread = threading.Thread(target=self.worker, daemon=True)
        self.thread.start()

    def worker(self):
        while self.running:
            text = self.q.get()
            if text is None:
                self.q.task_done()
                break

            # 1. JARVIS will always print to the terminal
            print(f"\n[{ASSISTANT_LOG_LABEL}]: {text}")
            
            # 2. CROSS-EMIT TO THE WEB UI OVER SOCKETS INSTANTLY
            if self.socketio:
                try:
                    self.socketio.emit('jarvis_speech', {'text': text})
                except Exception as se:
                    print(f"[SOCKET EMIT ERROR]: {se}")
            
            # 3. Local Hardware TTS Engine Fallback (Host Machine Speaker)
            if not self.muted:
                try:
                    if os.name == 'nt':
                        encoded_text = base64.b64encode(text.encode('utf-16le')).decode('utf-8')
                        ps_cmd = (
                            f"$text = [System.Text.Encoding]::Unicode.GetString([System.Convert]::FromBase64String('{encoded_text}')); "
                            "Add-Type -AssemblyName System.Speech; "
                            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                            "$synth.Rate = 1; "
                            "$synth.Speak($text)"
                        )
                        subprocess.run(
                            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        )
                    else:
                        tts_bin = shutil.which("espeak") or shutil.which("spd-say")
                        if tts_bin:
                            subprocess.run([tts_bin, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        elif not self._warned_no_local_tts:
                            print("[VOICE RUNTIME WARNING]: No local TTS binary found (espeak/spd-say).")
                            self._warned_no_local_tts = True
                except Exception as e:
                    print(f"[VOICE RUNTIME ERROR]: {e}")
            
            self.q.task_done()

    def speak_and_wait(self, text):
        self.q.put(text)
        self.q.join()
        
    def speak_async(self, text):
        self.q.put(text)

    def stop(self):
        self.running = False
        while not self.q.empty():
            try:
                self.q.get_nowait()
                self.q.task_done()
            except queue.Empty:
                break
        self.q.put(None)
        self.thread.join(timeout=1.0)