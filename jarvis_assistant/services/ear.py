import speech_recognition as sr
import threading
import sys
import queue
import time
import os

try:
    import msvcrt
except ImportError:
    msvcrt = None

class JarvisMultimodalEar:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.mic_enabled = True
        
        print("[System]: Calibrating microphone noise floor...")
        try:
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
        except Exception:
            print("[SYSTEM WARNING]: Microphone not detected or inaccessible.")

    def _listen_voice(self, q, stop_event):
        try:
            mic = sr.Microphone()
            with mic as source:
                while not stop_event.is_set():
                    try:
                        audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=4)
                        if stop_event.is_set():
                            break
                        text = self.recognizer.recognize_google(audio)
                        q.put(("voice", text.strip().lower()))
                        break
                    except (sr.WaitTimeoutError, sr.UnknownValueError):
                        continue
                    except Exception:
                        break
        except Exception as e:
            print(f"\n[MIC THREAD ERROR]: {e}")

    def _listen_keyboard(self, q, stop_event):
        prompt = "\n[QUASON]: Awaiting command (Type or Speak) >> " if self.mic_enabled else "\n[QUASON]: Awaiting command (Type only) >> "
        if os.name == 'nt' and msvcrt:
            sys.stdout.write(prompt)
            sys.stdout.flush()

            line = ""
            while not stop_event.is_set():
                if msvcrt.kbhit():
                    char = msvcrt.getwche()
                    if char in ('\r', '\n'):
                        print()
                        if line.strip():
                            q.put(("text", line.strip().lower()))
                            break
                    elif char == '\x08':
                        if len(line) > 0:
                            line = line[:-1]
                            sys.stdout.write(" \x08")
                            sys.stdout.flush()
                    else:
                        line += char
                time.sleep(0.05)
            return

        try:
            line = input(prompt)
            if line.strip() and not stop_event.is_set():
                q.put(("text", line.strip().lower()))
        except EOFError:
            pass

    def get_command(self):
        q = queue.Queue()
        stop_event = threading.Event()

        threads = []
        
        if self.mic_enabled:
            voice_thread = threading.Thread(target=self._listen_voice, args=(q, stop_event), daemon=True)
            threads.append(voice_thread)
            voice_thread.start()

        kb_thread = threading.Thread(target=self._listen_keyboard, args=(q, stop_event), daemon=True)
        threads.append(kb_thread)
        kb_thread.start()

        source, command = q.get()
        stop_event.set()

        if source == "voice":
            print(f"\n[Microphone Intercept]: {command}")

        return command