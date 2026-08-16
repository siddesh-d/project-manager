import subprocess
import time
import re
import json
import os
import hashlib
import queue
import threading
import sys
from jarvis_assistant.registry.projects import (
    get_projects,
    refresh_project_deployment_profile,
    update_runtime_state,
)
from jarvis_assistant.config import SETTINGS_FILE, PM2_EXECUTABLE, DEFAULT_PM2_FIELD_CONFIG
from jarvis_assistant.config import ASSISTANT_LOG_LABEL

from jarvis_assistant.services import web_server

# =====================================================================
# GLOBAL CONVERSATION STATE & UNIFIED PIPELINES
# =====================================================================
active_conversation_queue = None

SETTINGS_SCHEMA = {
    "engine": "browser",
    "mic": False,
    "speaker": False,
    "autolisten": False,
    "voiceURI": "",
    "volume": 1.0,
    "rate": 1.0,
}

SETTINGS_ALIASES = {
    "voiceuri": "voiceURI",
}


def _coerce_setting_value(key, raw_value):
    if not isinstance(raw_value, str):
        return raw_value

    lower = raw_value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False

    if key in {"volume", "rate"}:
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return raw_value

    # Preserve string representation for numeric-like values expected by UI sliders.
    return raw_value


def _normalize_pm2_settings(raw_pm2):
    default_fields = dict(DEFAULT_PM2_FIELD_CONFIG)
    normalized = {
        "refresh_seconds": 5,
        "fields": dict(default_fields),
    }

    if not isinstance(raw_pm2, dict):
        return normalized

    refresh_seconds = raw_pm2.get("refresh_seconds", normalized["refresh_seconds"])
    try:
        normalized["refresh_seconds"] = max(1, int(refresh_seconds))
    except (TypeError, ValueError):
        normalized["refresh_seconds"] = 5

    fields = raw_pm2.get("fields", {})
    if isinstance(fields, dict):
        for field_name, default_value in default_fields.items():
            if field_name not in fields:
                continue
            value = fields[field_name]
            if isinstance(value, str):
                normalized_value = value.strip().lower() in {"1", "true", "yes", "on"}
            else:
                normalized_value = bool(value)
            normalized["fields"][field_name] = normalized_value

    return normalized


def _normalize_settings(raw_settings):
    normalized = dict(SETTINGS_SCHEMA)

    if not isinstance(raw_settings, dict):
        return normalized

    merged = dict(raw_settings)
    for old_key, new_key in SETTINGS_ALIASES.items():
        if new_key not in merged and old_key in merged:
            merged[new_key] = merged[old_key]

    for key in SETTINGS_SCHEMA:
        if key in merged:
            normalized[key] = _coerce_setting_value(key, merged[key])

    for key, value in merged.items():
        if key not in normalized and key != "pm2":
            normalized[key] = value

    if "pm2" in merged:
        normalized["pm2"] = _normalize_pm2_settings(merged["pm2"])

    if normalized["engine"] not in {"browser", "legacy"}:
        normalized["engine"] = SETTINGS_SCHEMA["engine"]

    for key in ("mic", "speaker", "autolisten"):
        normalized[key] = bool(normalized[key])

    if not isinstance(normalized["voiceURI"], str):
        normalized["voiceURI"] = str(normalized["voiceURI"])

    try:
        normalized["volume"] = float(normalized["volume"])
    except (TypeError, ValueError):
        normalized["volume"] = SETTINGS_SCHEMA["volume"]

    try:
        normalized["rate"] = float(normalized["rate"])
    except (TypeError, ValueError):
        normalized["rate"] = SETTINGS_SCHEMA["rate"]

    return normalized


def _load_settings_file():
    settings = dict(SETTINGS_SCHEMA)

    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
                settings = _normalize_settings(loaded)
        except Exception:
            # Keep safe defaults when the file is malformed instead of forcing mic/speaker true.
            pass

    return settings


def _persist_settings_file(settings):
    normalized = _normalize_settings(settings)

    if "pm2" not in normalized and SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as existing_handle:
                existing = json.load(existing_handle)
            if isinstance(existing, dict) and "pm2" in existing:
                normalized["pm2"] = _normalize_pm2_settings(existing.get("pm2", {}))
        except Exception:
            pass

    tmp_path = SETTINGS_FILE.with_suffix(SETTINGS_FILE.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(normalized, f)
    os.replace(tmp_path, SETTINGS_FILE)

def broadcast(voice, message, log_type=ASSISTANT_LOG_LABEL, color="text-cyan-300", speak=True, wait=False):
    has_web_stream = 'web_server' in globals() or 'web_server' in sys.modules
    if has_web_stream:
        web_server.stream_log_to_ui(log_type, message, color)
    
    should_speak = bool(speak and voice and (not has_web_stream or not getattr(voice, 'muted', False)))

    if should_speak:
        if wait:
            voice.speak_and_wait(message)
        else:
            voice.speak_async(message)
    elif not has_web_stream:
        print(f"\n[{log_type}]: {message}")

def ask_question(voice, ear, prompt_text, timeout=12.0):
    global active_conversation_queue
    broadcast(voice, prompt_text, color="text-amber-400 font-bold", speak=True, wait=True)
    
    current_queue = queue.Queue()
    active_conversation_queue = current_queue
    
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
        
    active_conversation_queue = None
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

# =====================================================================
# SYSTEM STATUS & TELEMETRY
# =====================================================================
def display_advanced_status(voice):
    try:
        env = os.environ.copy()
        env["NODE_NO_WARNINGS"] = "1"
        result = subprocess.run([PM2_EXECUTABLE, 'jlist'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        if result.returncode != 0 or not result.stdout.strip():
            broadcast(voice, "I could not retrieve the active P M 2 process list.", color="text-red-400", speak=True)
            return
            
        output = result.stdout.strip()
        processes = []
        
        # ULTIMATE SHIELD: Read lines in reverse to find the true JSON payload, ignoring PM2 update nags
        for line in reversed(output.split('\n')):
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                try:
                    processes = json.loads(line)
                    break
                except Exception:
                    continue
    except Exception:
        broadcast(voice, "Error reading P M 2 registry.", color="text-red-400", speak=True)
        return

    if not processes:
        broadcast(voice, "There are currently no active services in the P M 2 registry.", speak=True)
        return

    table_output = "\n" + "="*95 + "\n"
    table_output += f"{'PID':<6} | {'SERVICE NAME':<20} | {'STATUS':<10} | {'UPTIME':<12} | {'CPU':<6} | {'MEM':<8} | {'RESTARTS':<8}\n"
    table_output += "-" * 95 + "\n"
    
    online_count = 0
    offline_count = 0
    
    for p in processes:
        pid = p.get("pm_id", "N/A")
        name = p.get("name", "N/A")
        status = p.get("pm2_env", {}).get("status", "unknown")
        restarts = p.get("pm2_env", {}).get("restart_time", 0)
        
        monit = p.get("monit") or {}
        cpu = monit.get("cpu", 0)
        mem_bytes = monit.get("memory", 0)
        mem_mb = int(mem_bytes / (1024 * 1024))
        
        pm_uptime = p.get("pm2_env", {}).get("pm_uptime", 0)
        if pm_uptime > 0 and status == "online":
            uptime_sec = (time.time() * 1000 - pm_uptime) / 1000
            m, s = divmod(int(uptime_sec), 60)
            h, m = divmod(m, 60)
            uptime_str = f"{h}h {m}m {s}s"
        else:
            uptime_str = "0h 0m 0s"

        if status == "online":
            online_count += 1
        else:
            offline_count += 1

        table_output += f"{pid:<6} | {name:<20} | {status.upper():<10} | {uptime_str:<12} | {f'{cpu}%':<6} | {f'{mem_mb}MB':<8} | {restarts:<8}\n"
        
    table_output += "="*95
    print(table_output)
    
    if 'web_server' in globals() or 'web_server' in sys.modules:
        web_server.stream_log_to_ui("SYSTEM", table_output, "text-cyan-400 font-mono whitespace-pre")
    
    if offline_count == 0:
        broadcast(voice, f"All {online_count} managed services are currently online and stable.", speak=True)
    elif online_count == 0:
        broadcast(voice, f"Alert. All {offline_count} managed services are currently offline or errored.", color="text-red-400 font-bold", speak=True)
    else:
        broadcast(voice, f"{online_count} services are online, and {offline_count} services are offline.", speak=True)

def resolve_pm2_target(target_name):
    try:
        env = os.environ.copy()
        env["NODE_NO_WARNINGS"] = "1"
        result = subprocess.run([PM2_EXECUTABLE, 'jlist'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        if result.returncode == 0 and result.stdout.strip():
            output = result.stdout.strip()
            processes = []
            # ULTIMATE SHIELD
            for line in reversed(output.split('\n')):
                line = line.strip()
                if line.startswith('[') and line.endswith(']'):
                    try:
                        processes = json.loads(line)
                        break
                    except Exception:
                        continue
            
            target_lower = target_name.lower().strip()
            for p in processes:
                real_name = p.get("name", "")
                if real_name.lower() == target_lower:
                    return real_name
                    
            for p in processes:
                real_name = p.get("name", "")
                if target_lower in real_name.lower():
                    return real_name
    except Exception:
        pass
    return target_name


def _run_command_with_output(command, cwd, extra_env=None):
    env = os.environ.copy()
    if isinstance(extra_env, dict):
        for key, value in extra_env.items():
            if key:
                env[str(key)] = str(value)
    process = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return process.returncode, process.stdout or ""


def _load_dotenv_vars(project_path):
    env_file = os.path.join(project_path, ".env")
    if not os.path.exists(env_file):
        return {}

    parsed = {}
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.lower().startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if not key:
                    continue
                value = value.strip()
                if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
                    value = value[1:-1]
                parsed[key] = value
    except Exception:
        return {}
    return parsed


def _fingerprint_files(base_path, relative_paths):
    digest = hashlib.sha256()
    for rel in relative_paths:
        full_path = os.path.join(base_path, rel)
        if not os.path.exists(full_path):
            continue
        try:
            digest.update(rel.encode("utf-8", errors="ignore"))
            with open(full_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 128)
                    if not chunk:
                        break
                    digest.update(chunk)
        except OSError:
            continue
    return digest.hexdigest()


def _source_tree_signature(path):
    src_dir = os.path.join(path, "src")
    if not os.path.isdir(src_dir):
        return ""

    newest = 0
    count = 0
    for root, _, files in os.walk(src_dir):
        for name in files:
            full_path = os.path.join(root, name)
            try:
                stat_info = os.stat(full_path)
            except OSError:
                continue
            newest = max(newest, int(stat_info.st_mtime))
            count += 1

    return f"{count}:{newest}"


def _derive_install_command(path, profile):
    configured = str(profile.get("install_command") or "").strip()
    if configured:
        return configured

    project_type = str(profile.get("project_type") or "custom")
    if project_type == "node":
        if os.path.exists(os.path.join(path, "pnpm-lock.yaml")):
            return "pnpm install --frozen-lockfile"
        if os.path.exists(os.path.join(path, "yarn.lock")):
            return "yarn install --frozen-lockfile"
        if os.path.exists(os.path.join(path, "package-lock.json")):
            return "npm ci"
        return "npm install"
    if project_type == "python" and os.path.exists(os.path.join(path, "requirements.txt")):
        return "pip install -r requirements.txt"
    return ""


def _runtime_profile(proj):
    profile = dict(proj.get("deployment_profile") or {})
    profile.setdefault("project_type", "custom")
    profile.setdefault("required_files", [])
    profile.setdefault("env_mode", "optional")
    profile.setdefault("build_policy", "if_missing")
    profile.setdefault("auto_install", True)
    profile.setdefault("auto_build", True)
    profile.setdefault("build_command", "")
    profile.setdefault("runtime_entry", "")
    return profile


def _validate_project_requirements(proj, profile):
    path = proj.get("path", "")
    errors = []

    if not os.path.isdir(path):
        errors.append("Project directory is missing on disk.")
        return errors

    for req in profile.get("required_files") or []:
        required_path = os.path.join(path, req)
        if not os.path.exists(required_path):
            errors.append(f"Required file missing: {req}")

    env_mode = str(profile.get("env_mode") or "optional").lower()
    if env_mode == "required" and not os.path.exists(os.path.join(path, ".env")):
        errors.append("Required environment file .env is missing.")

    project_type = str(profile.get("project_type") or "custom")
    if project_type == "node" and not os.path.exists(os.path.join(path, "package.json")):
        errors.append("package.json is missing for Node project.")
    if project_type == "python":
        if not (os.path.exists(os.path.join(path, "requirements.txt")) or os.path.exists(os.path.join(path, "pyproject.toml"))):
            errors.append("Python project is missing requirements.txt or pyproject.toml.")

    return errors


def _install_fingerprint(path, profile):
    project_type = str(profile.get("project_type") or "custom")
    if project_type == "node":
        return _fingerprint_files(path, ["package-lock.json", "package.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"])
    if project_type == "python":
        return _fingerprint_files(path, ["requirements.txt", "pyproject.toml", "poetry.lock"])
    return ""


def _build_fingerprint(path, profile):
    base = _fingerprint_files(path, ["package.json", "package-lock.json", "tsconfig.json", "webpack.config.js"])
    tree = _source_tree_signature(path)
    return f"{base}:{tree}"


def _needs_build(path, profile, runtime_state):
    policy = str(profile.get("build_policy") or "if_missing").lower()
    if policy == "never":
        return False
    if policy == "always":
        return True

    runtime_entry = str(profile.get("runtime_entry") or "").strip()
    if policy == "if_missing":
        if runtime_entry:
            return not os.path.exists(os.path.join(path, runtime_entry))
        return False

    if policy == "on_change":
        current = _build_fingerprint(path, profile)
        previous = str(runtime_state.get("build_fingerprint") or "")
        return current != previous

    return False


def _prepare_project_runtime(proj, voice):
    name = proj.get("name", "")
    path = proj.get("path", "")
    profile = _runtime_profile(proj)
    runtime_state = dict(proj.get("runtime_state") or {})

    validation_errors = _validate_project_requirements(proj, profile)
    if validation_errors:
        update_runtime_state(name, {
            "last_error_stage": "validate",
            "last_error": " | ".join(validation_errors),
            "last_error_at": int(time.time()),
        })
        broadcast(voice, f"Cannot start {proj.get('friendly_name', name)}: {validation_errors[0]}", color="text-red-400", speak=True)
        return False

    install_command = _derive_install_command(path, profile)
    current_install_fp = _install_fingerprint(path, profile)
    project_type = str(profile.get("project_type") or "custom").lower()
    project_env = _load_dotenv_vars(path)
    deps_installed = bool(runtime_state.get("deps_installed", False))
    previous_install_fp = str(runtime_state.get("install_fingerprint") or "")

    # If dependencies already exist on disk (for example from prior manual install),
    # treat them as installed and avoid running install on each start.
    if project_type == "node":
        node_modules_path = os.path.join(path, "node_modules")
        node_modules_exists = os.path.isdir(node_modules_path)
        deps_installed = deps_installed and node_modules_exists
        runtime_state["deps_installed"] = deps_installed

    install_changed = bool(current_install_fp and previous_install_fp and current_install_fp != previous_install_fp)
    missing_install_state = bool(current_install_fp and not previous_install_fp)

    should_install = bool(
        profile.get("auto_install", True)
        and install_command
        and ((not deps_installed) or install_changed or missing_install_state)
    )
    if should_install:
        broadcast(voice, f"Installing dependencies for {proj.get('friendly_name', name)}...", color="text-cyan-400", speak=False)
        code, output = _run_command_with_output(install_command, path, extra_env=project_env)
        if code != 0:
            update_runtime_state(name, {
                "last_error_stage": "install",
                "last_error": output[-1500:],
                "last_error_at": int(time.time()),
            })
            broadcast(voice, f"Dependency installation failed for {proj.get('friendly_name', name)}.", color="text-red-400", speak=True)
            return False
        runtime_state["install_fingerprint"] = _install_fingerprint(path, profile)
        runtime_state["deps_installed"] = True

    build_command = str(profile.get("build_command") or "").strip()
    if profile.get("auto_build", True) and build_command and _needs_build(path, profile, runtime_state):
        broadcast(voice, f"Building {proj.get('friendly_name', name)}...", color="text-cyan-400", speak=False)
        code, output = _run_command_with_output(build_command, path, extra_env=project_env)
        if code != 0:
            update_runtime_state(name, {
                "last_error_stage": "build",
                "last_error": output[-1500:],
                "last_error_at": int(time.time()),
            })
            broadcast(voice, f"Build failed for {proj.get('friendly_name', name)}.", color="text-red-400", speak=True)
            return False
        runtime_state["build_fingerprint"] = _build_fingerprint(path, profile)

    runtime_state["last_ready_at"] = int(time.time())
    runtime_state["last_error_stage"] = ""
    runtime_state["last_error"] = ""
    if current_install_fp and not runtime_state.get("install_fingerprint"):
        runtime_state["install_fingerprint"] = current_install_fp
    update_runtime_state(name, runtime_state)
    return True


def _pm2_service_status(pm2_name):
    try:
        env = os.environ.copy()
        env["NODE_NO_WARNINGS"] = "1"
        result = subprocess.run(
            [PM2_EXECUTABLE, 'jlist'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=4,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""

        processes = []
        for line in reversed(result.stdout.strip().split('\n')):
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                try:
                    processes = json.loads(line)
                    break
                except Exception:
                    continue

        for process in processes:
            if process.get("name") == pm2_name:
                return str(process.get("pm2_env", {}).get("status", "")).strip().lower()
    except Exception:
        return ""
    return ""


def _wait_pm2_online(pm2_name, timeout_seconds=6):
    end_at = time.time() + max(1, timeout_seconds)
    while time.time() < end_at:
        status = _pm2_service_status(pm2_name)
        if status in {"online", "launching"}:
            return True, status
        if status in {"errored", "stopped", "one-launch-status"}:
            return False, status
        time.sleep(0.6)
    return False, _pm2_service_status(pm2_name)


def _recent_pm2_logs(pm2_name, lines=60):
    try:
        result = subprocess.run(
            [PM2_EXECUTABLE, 'logs', pm2_name, '--raw', '--nostream', '--lines', str(lines)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=6,
        )
        return result.stdout or ""
    except Exception:
        return ""


def _looks_like_missing_module_error(text):
    lowered = str(text or "").lower()
    tokens = [
        "cannot find module",
        "err_module_not_found",
        "module_not_found",
    ]
    return any(token in lowered for token in tokens)


def _start_pm2_entry(pm2_name, path, entry_command, extra_env=None):
    code, output = _run_command_with_output(entry_command, path, extra_env=extra_env)
    if code != 0:
        return False, f"PM2 start command failed (exit {code})."

    online, status = _wait_pm2_online(pm2_name)
    if online:
        return True, ""

    logs = _recent_pm2_logs(pm2_name)
    if logs.strip():
        return False, logs[-1200:]
    return False, f"PM2 process status is '{status or 'unknown'}'."


def _get_runtime_error_summary(project_name):
    project = next((p for p in get_projects() if p.get("name", "").lower() == str(project_name or "").lower()), None)
    if not project:
        return "", ""

    runtime_state = project.get("runtime_state") if isinstance(project.get("runtime_state"), dict) else {}
    stage = str(runtime_state.get("last_error_stage") or "").strip()
    message = str(runtime_state.get("last_error") or "").strip()
    return stage, message

# =====================================================================
# INTELLIGENT COMMAND-LINE BUILD ENGINE
# =====================================================================
def intelligent_service_start(proj, voice, ear):
    """Starts a project with validation, dependency install, and optional build preparation."""
    pm2_name = proj["name"]
    path = proj["path"]

    refreshed = refresh_project_deployment_profile(pm2_name)
    if isinstance(refreshed, dict):
        proj = refreshed
        path = proj["path"]

    broadcast(voice, f"Starting {proj['friendly_name']}...", speak=False)

    if not _prepare_project_runtime(proj, voice):
        return False

    subprocess.run(f'"{PM2_EXECUTABLE}" delete {pm2_name}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    profile = _runtime_profile(proj)
    project_env = _load_dotenv_vars(path)
    install_command = _derive_install_command(path, profile)
    project_type = str(profile.get("project_type") or "custom").lower()

    def _retry_install_then_start(entry_command, failure_message):
        if project_type != "node":
            return False, failure_message
        if not profile.get("auto_install", True) or not install_command:
            return False, failure_message
        if not _looks_like_missing_module_error(failure_message):
            return False, failure_message

        broadcast(voice, f"Missing module detected for {proj['friendly_name']}. Installing dependencies and retrying...", color="text-amber-400", speak=False)
        install_code, install_output = _run_command_with_output(install_command, path, extra_env=project_env)
        if install_code != 0:
            return False, install_output[-1200:] or f"Dependency installation failed (exit {install_code})."

        update_runtime_state(pm2_name, {
            "deps_installed": True,
            "install_fingerprint": _install_fingerprint(path, profile),
        })

        subprocess.run(f'"{PM2_EXECUTABLE}" delete {pm2_name}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok, retry_message = _start_pm2_entry(pm2_name, path, entry_command, extra_env=project_env)
        return ok, retry_message

    if "custom_start" in proj:
        code, output = _run_command_with_output(proj["custom_start"], path, extra_env=project_env)
        if code != 0:
            update_runtime_state(pm2_name, {
                "last_error_stage": "start",
                "last_error": output[-1200:] or f"Custom start command exited with code {code}.",
                "last_error_at": int(time.time()),
            })
            return False
        return True

    runtime_entry = str(profile.get("runtime_entry") or "").strip()
    entry_on_disk = os.path.join(path, runtime_entry) if runtime_entry else ""

    if runtime_entry and os.path.exists(entry_on_disk):
        start_command = f'"{PM2_EXECUTABLE}" start "{runtime_entry}" --name "{pm2_name}" --update-env'
        ok, start_message = _start_pm2_entry(pm2_name, path, start_command, extra_env=project_env)
        if not ok:
            ok, retry_message = _retry_install_then_start(start_command, start_message)
            if ok:
                return True
            update_runtime_state(pm2_name, {
                "last_error_stage": "start",
                "last_error": (retry_message if retry_message else start_message) or f"PM2 failed to start runtime entry '{runtime_entry}'.",
                "last_error_at": int(time.time()),
            })
            return False
        return True

    fallback_entry = os.path.join(path, "dist", "main.js")
    if os.path.exists(fallback_entry):
        start_command = f'"{PM2_EXECUTABLE}" start dist/main.js --name "{pm2_name}" --update-env'
        ok, start_message = _start_pm2_entry(pm2_name, path, start_command, extra_env=project_env)
        if not ok:
            ok, retry_message = _retry_install_then_start(start_command, start_message)
            if ok:
                return True
            update_runtime_state(pm2_name, {
                "last_error_stage": "start",
                "last_error": (retry_message if retry_message else start_message) or "PM2 failed to start fallback entry 'dist/main.js'.",
                "last_error_at": int(time.time()),
            })
            return False
        return True

    update_runtime_state(pm2_name, {
        "last_error_stage": "start",
        "last_error": "Runtime entry not found after preparation.",
        "last_error_at": int(time.time()),
    })
    broadcast(voice, f"Cannot start {proj['friendly_name']}: runtime entry is missing.", color="text-red-400", speak=True)
    return False

# =====================================================================
# DECOUPLED CONVERSATIONAL COMMAND PROCESSOR
# =====================================================================
def process_command(raw_command, voice, ear=None, tenant_id=None):
    global active_conversation_queue
    raw_command_stripped = raw_command.strip()
    command = raw_command_stripped.lower()
    
    if active_conversation_queue is not None:
        active_conversation_queue.put(command)
        return

    raw_parts = raw_command.strip().split()
    command_projects = [
        project for project in get_projects()
        if tenant_id is None or str(project.get('tenant_id') or '').strip() == str(tenant_id).strip()
    ]

    if raw_command_stripped.lower().startswith("sys_setting:"):
        parts = raw_command_stripped.split(":", 2)
        if len(parts) == 3:
            key, raw_val = parts[1], parts[2]
            key = key.lower()
            key = SETTINGS_ALIASES.get(key, key)
            if key not in SETTINGS_SCHEMA:
                return {"type": "sys_setting", "key": key, "changed": False, "ignored": True}

            val = _coerce_setting_value(key, raw_val)
            settings = _load_settings_file()
            old_val = settings.get(key)
            settings[key] = val

            # Persist only when a real change happened.
            changed = old_val != val
            if old_val != val:
                _persist_settings_file(settings)

            if key in ["engine", "mic", "speaker"]:
                if settings["engine"] == "browser":
                    voice.muted = True
                    if ear: ear.mic_enabled = False
                else:
                    voice.muted = not settings["speaker"]
                    if ear: ear.mic_enabled = settings["mic"]
            return {"type": "sys_setting", "key": key, "changed": changed}

    command = re.sub(r'\ba\s*[\s\.]*\s*u\s*[\s\.]*\s*t\s*[\s\.]*\s*h\b', 'auth', command)
    for phrase in ["hot service", "earth service", "authentication", "out service", "art service", "aught service", "hot logs", "earth logs"]:
        if phrase in command: 
            command = command.replace(phrase, "auth")

    ui_parts = command.split()
    is_ui_exact = (len(ui_parts) == 2) and (ui_parts[0] in ["start", "stop", "restart", "delete", "remove", "flush"]) and (ui_parts[1] != "all")

    if "disable voice" in command or "disable mic" in command:
        if ear: ear.mic_enabled = False
        broadcast(voice, "Microphone disabled.", speak=True)
        return
    elif "enable voice" in command or "enable mic" in command:
        if ear: ear.mic_enabled = True
        broadcast(voice, "Microphone restored.", speak=True)
        return
    elif "unmute" in command or "speak" in command:
        voice.muted = False
        broadcast(voice, "Voice output enabled. Audio system active.", color="text-emerald-400 font-bold", speak=True)
        return
    elif "mute" in command or "silent mode" in command:
        voice.muted = True
        broadcast(voice, "Entering silent mode.", color="text-amber-400", speak=False)
        return

    if command in ["status", "list", "online", "offline"] or "show status" in command or "get status" in command:
        broadcast(voice, "Fetching detailed infrastructure telemetry.", speak=True, wait=True)
        display_advanced_status(voice)
        return
        
    elif "start all" in command or "boot all" in command or "start all services" in command:
        broadcast(voice, "Initializing all project-specific background services.", color="text-emerald-400", speak=True)
        for proj in command_projects:
            intelligent_service_start(proj, voice, ear)
        return
        
    elif "stop all" in command or "shutdown services" in command or "stop all services" in command:
        if require_confirmation(voice, ear, "stop", "all infrastructure services", is_ui_exact=False):
            broadcast(voice, "Halting project-specific background services.", color="text-amber-400", speak=True)
            for proj in command_projects:
                subprocess.run(f'"{PM2_EXECUTABLE}" stop {proj["name"]}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
        
    elif "delete all" in command or "remove all" in command:
        if require_confirmation(voice, ear, "delete", "all infrastructure services", is_ui_exact=False):
            broadcast(voice, "Purging project-specific services from the P M 2 registry.", color="text-red-400", speak=True)
            for proj in command_projects:
                subprocess.run(f'"{PM2_EXECUTABLE}" delete {proj["name"]}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
        
    elif "exit" in command or "quit" in command:
        broadcast(voice, "Terminating control systems.", speak=True)
        raise KeyboardInterrupt

    if "log" in command or "logs" in command or "telemetry" in command:
        matched_target = None
        for proj in command_projects:
            if proj["name"] in command or proj["friendly_name"].lower() in command:
                matched_target = proj["name"]
                break
        
        if not matched_target:
            amr_match = re.search(r'\b(amr-service-\d+)\b', command)
            if amr_match: matched_target = amr_match.group(1)

        if matched_target:
            broadcast(voice, f"Opening live logs for {matched_target}.", speak=True)
            if 'web_server' in globals() or 'web_server' in sys.modules:
                web_server.socketio.emit('log_stream_intent', {'service': matched_target})
        else:
            response = ask_question(voice, ear, "Sure, which service would you like to fetch logs for? Please confirm the process name.")
            if response and not any(w in response.lower() for w in ["cancel", "abort", "nevermind", "nothing"]):
                process_command(f"log {response}", voice, ear)
        return

    elif "restart all" in command or "reboot all" in command or "restart all services" in command:
        if require_confirmation(voice, ear, "restart", "all infrastructure services", is_ui_exact=False):
            broadcast(voice, "All core services will be restarted.", speak=True)
            for proj in command_projects:
                subprocess.run(f'"{PM2_EXECUTABLE}" restart {proj["name"]}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
            try:
                env = os.environ.copy()
                env["NODE_NO_WARNINGS"] = "1"
                result = subprocess.run([PM2_EXECUTABLE, 'jlist'], stdout=subprocess.PIPE, text=True, env=env)
                processes = []
                if result.returncode == 0 and result.stdout.strip():
                    # ULTIMATE SHIELD for restart all amrs
                    for line in reversed(result.stdout.strip().split('\n')):
                        line = line.strip()
                        if line.startswith('[') and line.endswith(']'):
                            try:
                                processes = json.loads(line)
                                break
                            except Exception:
                                continue
                online_amrs = [p.get("name") for p in processes if p.get("name", "").startswith("amr-service-") and p.get("pm2_env", {}).get("status") == "online"]
            except Exception: online_amrs = []
                
            if online_amrs:
                response = ask_question(voice, ear, "Would you also like to restart the online Virtual AMRs?")
                if response and any(w in response.lower() for w in ["yes", "sure", "restart", "do it", "okay", "yep"]):
                    broadcast(voice, "Confirmed. Rebooting online Virtual A M R services.", speak=True)
                    for amr in online_amrs: subprocess.run(f'"{PM2_EXECUTABLE}" restart {amr}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    broadcast(voice, "No response received. Proceeding with core service restart only. Virtual A M R restart has been skipped.", color="text-amber-500", speak=True)
        return

    action_intent = None
    if "restart" in command or "reboot" in command: action_intent = "restart"
    elif "stop" in command or "halt" in command: action_intent = "stop"
    elif "start" in command or "boot" in command: action_intent = "start"
    elif "delete" in command or "remove" in command or "purge" in command: action_intent = "delete"
    elif "flush" in command or "clear log" in command: action_intent = "flush"

    if action_intent:
        target = None
        if is_ui_exact:
            target = resolve_pm2_target(raw_parts[1])
        else:
            for proj in command_projects:
                if proj["name"] in command or proj["friendly_name"].lower() in command:
                    target = proj["name"]
                    break
            if not target:
                amr_match = re.search(r'\b(amr-service-\d+)\b', command)
                if amr_match: target = amr_match.group(1)

        if target:
            matched_proj = next((p for p in command_projects if p["name"].lower() == target.lower()), None)
            if tenant_id is not None and not matched_proj:
                return {
                    "type": "command_result",
                    "target": target,
                    "ok": False,
                    "message": "Project not found or access denied.",
                }

            if action_intent in ["stop", "delete", "flush", "restart"]:
                if not require_confirmation(voice, ear, action_intent, target, is_ui_exact):
                    return
            
            if action_intent == "start":
                if matched_proj:
                    started = intelligent_service_start(matched_proj, voice, ear)
                    if started:
                        return {
                            "type": "start_result",
                            "target": matched_proj.get("name", target),
                            "ok": True,
                            "message": f"Project '{matched_proj.get('friendly_name', target)}' started successfully.",
                        }

                    stage, err_message = _get_runtime_error_summary(matched_proj.get("name", target))
                    error_text = err_message or "Startup failed."
                    if stage:
                        error_text = f"{stage}: {error_text}"
                    return {
                        "type": "start_result",
                        "target": matched_proj.get("name", target),
                        "ok": False,
                        "message": error_text,
                    }
                else:
                    proc = subprocess.run(f'"{PM2_EXECUTABLE}" start {target}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return {
                        "type": "start_result",
                        "target": target,
                        "ok": proc.returncode == 0,
                        "message": "Project started successfully." if proc.returncode == 0 else "PM2 start command failed.",
                    }
            else:
                broadcast(voice, f"Executing {action_intent.upper()} directive for {target}", color="text-emerald-400 font-bold", speak=True)
                subprocess.run(f'"{PM2_EXECUTABLE}" {action_intent} {target}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
        else:
            response = ask_question(voice, ear, f"Which service would you like to {action_intent}?")
            if response and not any(w in response.lower() for w in ["cancel", "abort", "nothing"]):
                process_command(f"{action_intent} {response}", voice, ear, tenant_id=tenant_id)
        return

    if command in ["hi", "hello", "hey", "hi jarvis", "hello jarvis", "hey jarvis"]:
        broadcast(voice, "Hello! How can I help you today?", color="text-emerald-400 font-bold", speak=True)
        return

    if is_ui_exact:
        broadcast(voice, f"Unrecognized directive '{command}'", color="text-red-500", speak=False)
    else:
        broadcast(voice, "I didn't recognize that command. Can you rephrase it or tell me what you'd like to do?", color="text-amber-400 font-bold", speak=True)

# =====================================================================
# STANDBY LOOP
# =====================================================================
def run_standby_loop(voice, ear):
    print("\n========================================================")
    print("[SYSTEM]: Standby Mode Active. Listening for instructions...")
    print("Available Commands: 'status', 'start all', 'start [name]', 'restart [name]', 'stop [name]', 'delete [name]', 'stop all', 'disable mic', 'mute', 'exit'")
    print("========================================================\n")
    
    try:
        while True:
            raw_command = ear.get_command()
            if not raw_command: continue
            
            process_command(raw_command, voice, ear)
                
    except KeyboardInterrupt:
        print("\n[SYSTEM]: Interrupted by user. Terminating engine components cleanly...")
        broadcast(voice, "Shutting down core engine components.", speak=True)
        time.sleep(0.5)
    finally:
        voice.stop()
        print("[SYSTEM]: Engine offline.")