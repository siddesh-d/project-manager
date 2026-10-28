"""User-facing messaging: log streaming, spoken output and confirmation prompts.

The log sink is injected by the composition root (``assistant.core.app``) so this
module does not depend on the web layer.
"""
import queue
import threading

from assistant.config import ASSISTANT_LOG_LABEL

_log_sink = None
_event_sink = None
_active_queue = None


def set_log_sink(sink):
    """Register ``sink(log_type, message, color)`` used to stream messages to the UI."""
    global _log_sink
    _log_sink = sink


def set_event_sink(sink):
    """Register ``sink(event_name, payload)`` used to push UI events."""
    global _event_sink
    _event_sink = sink


def stream_log(log_type, message, color="text-zinc-300"):
    if _log_sink is not None:
        _log_sink(log_type, message, color)


def emit_event(event_name, payload):
    if _event_sink is not None:
        _event_sink(event_name, payload)


def broadcast(voice, message, log_type=ASSISTANT_LOG_LABEL, color="text-cyan-300", speak=True, wait=False):
    has_web_stream = _log_sink is not None
    if has_web_stream:
        _log_sink(log_type, message, color)

    should_speak = bool(speak and voice and (not has_web_stream or not getattr(voice, 'muted', False)))

    if should_speak:
        if wait:
            voice.speak_and_wait(message)
        else:
            voice.speak_async(message)
    elif not has_web_stream:
        print(f"\n[{log_type}]: {message}")


def submit_reply(command):
    """Hand a command to a pending question. Returns True when it was consumed."""
    pending = _active_queue
    if pending is None:
        return False
    pending.put(command)
    return True


def ask_question(voice, ear, prompt_text, timeout=12.0):
    global _active_queue
    broadcast(voice, prompt_text, color="text-amber-400 font-bold", speak=True, wait=True)

    current_queue = queue.Queue()
    _active_queue = current_queue

    if ear and getattr(ear, 'mic_enabled', True):
        def listen_worker():
            try:
                cmd = ear.get_command()
                if cmd and str(cmd).strip():
                    current_queue.put(cmd)
            except Exception:
                pass
        threading.Thread(target=listen_worker, daemon=True).start()

    try:
        response = current_queue.get(timeout=timeout)
    except queue.Empty:
        response = None

    _active_queue = None
    return response


def require_confirmation(voice, ear, action, target, is_ui_exact):
    if is_ui_exact:
        return True

    prompt = f"Warning. You are about to {action} {target}. Are you sure you want to proceed?"
    response = ask_question(voice, ear, prompt)

    if response and any(w in str(response).lower() for w in ["yes", "sure", "do it", "okay", "yep", "confirm", "proceed"]):
        return True

    broadcast(voice, f"{action.capitalize()} operation cancelled.", color="text-amber-500", speak=True)
    return False
