"""Command orchestration: interprets text/voice commands and drives service lifecycle.

Lower-level concerns live in dedicated modules:
  - ``conversation``   messaging, confirmation prompts, UI sinks
  - ``settings_store`` settings persistence
  - ``services.pm2_cli`` / ``services.project_runtime`` PM2 and project preparation
"""
import os
import re
import subprocess
import time

from assistant.config import PM2_EXECUTABLE
from assistant.core import settings_store
from assistant.core.conversation import (  # noqa: F401 - re-exported for existing callers
    ask_question,
    broadcast,
    emit_event,
    require_confirmation,
    stream_log,
    submit_reply,
)
from assistant.registry.projects import (
    get_projects,
    refresh_project_deployment_profile,
    update_runtime_state,
)
from assistant.services import pm2_cli, project_runtime

# Backward-compatible names used across the codebase and tests.
SETTINGS_SCHEMA = settings_store.SETTINGS_SCHEMA
SETTINGS_ALIASES = settings_store.SETTINGS_ALIASES
_coerce_setting_value = settings_store.coerce_setting_value
_load_settings_file = settings_store.load_settings
_persist_settings_file = settings_store.persist_settings
resolve_pm2_target = pm2_cli.resolve_pm2_target
_delete_pm2_service = pm2_cli.delete_pm2_service
_looks_like_missing_module_error = pm2_cli.looks_like_missing_module_error
_run_command_with_output = project_runtime.run_command_with_output
_prepare_install_command = project_runtime.prepare_install_command
_load_dotenv_vars = project_runtime.load_dotenv_vars
_derive_install_command = project_runtime.derive_install_command
_runtime_profile = project_runtime.runtime_profile
_validate_project_requirements = project_runtime.validate_project_requirements
_install_fingerprint = project_runtime.install_fingerprint
_build_fingerprint = project_runtime.build_fingerprint
_needs_build = project_runtime.needs_build
_start_pm2_entry = project_runtime.start_pm2_entry


# =====================================================================
# SYSTEM STATUS & TELEMETRY
# =====================================================================
def display_advanced_status(voice):
    processes = pm2_cli.fetch_pm2_processes()
    if processes is None:
        broadcast(voice, "I could not retrieve the active P M 2 process list.", color="text-red-400", speak=True)
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
        mem_mb = int(monit.get("memory", 0) / (1024 * 1024))

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
    stream_log("SYSTEM", table_output, "text-cyan-400 font-mono whitespace-pre")

    if offline_count == 0:
        broadcast(voice, f"All {online_count} managed services are currently online and stable.", speak=True)
    elif online_count == 0:
        broadcast(voice, f"Alert. All {offline_count} managed services are currently offline or errored.", color="text-red-400 font-bold", speak=True)
    else:
        broadcast(voice, f"{online_count} services are online, and {offline_count} services are offline.", speak=True)


# =====================================================================
# PROJECT RUNTIME PREPARATION & SERVICE START
# =====================================================================
def _record_runtime_error(name, stage, message):
    update_runtime_state(name, {
        "last_error_stage": stage,
        "last_error": message,
        "last_error_at": int(time.time()),
    })


def _prepare_project_runtime(proj, voice):
    name = proj.get("name", "")
    path = proj.get("path", "")
    label = proj.get('friendly_name', name)
    profile = _runtime_profile(proj)
    runtime_state = dict(proj.get("runtime_state") or {})

    validation_errors = _validate_project_requirements(proj, profile)
    if validation_errors:
        _record_runtime_error(name, "validate", " | ".join(validation_errors))
        broadcast(voice, f"Cannot start {label}: {validation_errors[0]}", color="text-red-400", speak=True)
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
        node_modules_exists = os.path.isdir(os.path.join(path, "node_modules"))
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
        prepared_install_command, preparation_error = _prepare_install_command(
            install_command,
            project_type,
            path,
            extra_env=project_env,
        )
        if preparation_error:
            _record_runtime_error(name, "install", preparation_error)
            broadcast(voice, f"Dependency installation failed for {label}.", color="text-red-400", speak=True)
            return False

        project_runtime.set_active_stage(name, "Dependency installation is in progress.")
        broadcast(voice, f"Installing dependencies for {label}...", color="text-cyan-400", speak=False)
        code, output = _run_command_with_output(prepared_install_command, path, extra_env=project_env)
        if code != 0:
            _record_runtime_error(name, "install", output[-1500:])
            broadcast(voice, f"Dependency installation failed for {label}.", color="text-red-400", speak=True)
            return False
        runtime_state["install_fingerprint"] = _install_fingerprint(path, profile)
        runtime_state["deps_installed"] = True

    build_command = str(profile.get("build_command") or "").strip()
    if profile.get("auto_build", True) and build_command and _needs_build(path, profile, runtime_state):
        project_runtime.set_active_stage(name, "Build is in progress.")
        broadcast(voice, f"Building {label}...", color="text-cyan-400", speak=False)
        code, output = _run_command_with_output(build_command, path, extra_env=project_env)
        if code != 0:
            _record_runtime_error(name, "build", output[-1500:])
            broadcast(voice, f"Build failed for {label}.", color="text-red-400", speak=True)
            return False
        runtime_state["build_fingerprint"] = _build_fingerprint(path, profile)

    runtime_state["last_ready_at"] = int(time.time())
    runtime_state["last_error_stage"] = ""
    runtime_state["last_error"] = ""
    if current_install_fp and not runtime_state.get("install_fingerprint"):
        runtime_state["install_fingerprint"] = current_install_fp

    update_runtime_state(name, runtime_state)
    return True


def _get_runtime_error_summary(project_name):
    project = next((p for p in get_projects() if p.get("name", "").lower() == str(project_name or "").lower()), None)
    if not project:
        return "", ""

    runtime_state = project.get("runtime_state") if isinstance(project.get("runtime_state"), dict) else {}
    stage = str(runtime_state.get("last_error_stage") or "").strip()
    message = str(runtime_state.get("last_error") or "").strip()
    return stage, message


def _pm2_delete_quiet(pm2_name):
    subprocess.run(f'"{PM2_EXECUTABLE}" delete {pm2_name}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def intelligent_service_start(proj, voice, ear, instances=None):
    """Starts a project, publishing its live stage for status checks until it finishes."""
    project_runtime.set_active_stage(proj["name"], "Start is in progress.")
    try:
        return _intelligent_service_start(proj, voice, ear, instances=instances)
    finally:
        project_runtime.set_active_stage(proj["name"], None)


def _intelligent_service_start(proj, voice, ear, instances=None):
    """Starts a project with validation, dependency install, and optional build preparation."""
    pm2_name = proj["name"]
    path = proj["path"]

    refreshed = refresh_project_deployment_profile(pm2_name)
    if isinstance(refreshed, dict):
        proj = refreshed
        path = proj["path"]

    if instances is not None:
        error = ''
        if isinstance(instances, bool) or not isinstance(instances, int) or instances < 1:
            error = 'Cluster instances must be a positive integer.'
        elif "custom_start" in proj or str(_runtime_profile(proj).get("project_type") or "custom").lower() != "node":
            error = 'Cluster instances require a Node.js runtime entry, not a custom start command.'
        if error:
            _record_runtime_error(pm2_name, "start", error)
            broadcast(voice, error, color="text-red-400", speak=False)
            return False

    instance_args = f' --instances {instances}' if instances is not None else ''
    broadcast(voice, f"Starting {proj['friendly_name']}...", speak=False)

    if not _prepare_project_runtime(proj, voice):
        return False

    _pm2_delete_quiet(pm2_name)

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
        prepared_install_command, preparation_error = _prepare_install_command(
            install_command,
            project_type,
            path,
            extra_env=project_env,
        )
        if preparation_error:
            return False, preparation_error

        install_code, install_output = _run_command_with_output(prepared_install_command, path, extra_env=project_env)
        if install_code != 0:
            return False, install_output[-1200:] or f"Dependency installation failed (exit {install_code})."

        update_runtime_state(pm2_name, {
            "deps_installed": True,
            "install_fingerprint": _install_fingerprint(path, profile),
        })

        _pm2_delete_quiet(pm2_name)
        return _start_pm2_entry(pm2_name, path, entry_command, extra_env=project_env)

    if "custom_start" in proj:
        code, output = _run_command_with_output(proj["custom_start"], path, extra_env=project_env)
        if code != 0:
            _record_runtime_error(pm2_name, "start", output[-1200:] or f"Custom start command exited with code {code}.")
            return False
        return True

    def _start_entry(entry, description):
        start_command = f'"{PM2_EXECUTABLE}" start {entry} --name "{pm2_name}" --update-env{instance_args}'
        ok, start_message = _start_pm2_entry(pm2_name, path, start_command, extra_env=project_env)
        if ok:
            return True
        ok, retry_message = _retry_install_then_start(start_command, start_message)
        if ok:
            return True
        _record_runtime_error(
            pm2_name,
            "start",
            (retry_message if retry_message else start_message) or f"PM2 failed to start {description}.",
        )
        return False

    runtime_entry = str(profile.get("runtime_entry") or "").strip()
    if runtime_entry and os.path.exists(os.path.join(path, runtime_entry)):
        return _start_entry(f'"{runtime_entry}"', f"runtime entry '{runtime_entry}'")

    if os.path.exists(os.path.join(path, "dist", "main.js")):
        return _start_entry("dist/main.js", "fallback entry 'dist/main.js'")

    _record_runtime_error(pm2_name, "start", "Runtime entry not found after preparation.")
    broadcast(voice, f"Cannot start {proj['friendly_name']}: runtime entry is missing.", color="text-red-400", speak=True)
    return False


# =====================================================================
# DECOUPLED CONVERSATIONAL COMMAND PROCESSOR
# =====================================================================
def _apply_sys_setting(raw_command_stripped, voice, ear):
    """Handle a ``sys_setting:key:value`` command. Returns a result dict, or None if malformed."""
    parts = raw_command_stripped.split(":", 2)
    if len(parts) != 3:
        return None

    key, raw_val = parts[1].lower(), parts[2]
    key = SETTINGS_ALIASES.get(key, key)
    if key not in SETTINGS_SCHEMA:
        return {"type": "sys_setting", "key": key, "changed": False, "ignored": True}

    val = _coerce_setting_value(key, raw_val)
    settings = _load_settings_file()
    old_val = settings.get(key)
    settings[key] = val

    # Persist only when a real change happened.
    changed = old_val != val
    if changed:
        _persist_settings_file(settings)

    if key in ["engine", "mic", "speaker"]:
        if settings["engine"] == "browser":
            voice.muted = True
            if ear: ear.mic_enabled = False
        else:
            voice.muted = not settings["speaker"]
            if ear: ear.mic_enabled = settings["mic"]
    return {"type": "sys_setting", "key": key, "changed": changed}


def _online_virtual_amrs():
    processes = pm2_cli.fetch_pm2_processes() or []
    return [
        p.get("name") for p in processes
        if p.get("name", "").startswith("amr-service-") and p.get("pm2_env", {}).get("status") == "online"
    ]


def process_command(raw_command, voice, ear=None, tenant_id=None):
    from assistant.services.pm2_manager import parse_delete_logs, parse_keep_logs, parse_start_instances

    try:
        raw_command, keep_logs = parse_keep_logs(raw_command)
        raw_command, explicit_delete_logs = parse_delete_logs(raw_command)
        if keep_logs and explicit_delete_logs:
            raise ValueError('Use either --delete-logs or keep logs, not both.')
        raw_command, instances = parse_start_instances(raw_command)
    except ValueError as error:
        return {"type": "start_result", "target": "", "ok": False, "message": str(error)}
    # Removing a service also removes its logs unless the user asked to keep them.
    delete_logs = not keep_logs
    raw_command_stripped = raw_command.strip()
    command = raw_command_stripped.lower()

    if submit_reply(command):
        return

    raw_parts = raw_command.strip().split()
    command_projects = [
        project for project in get_projects()
        if tenant_id is None or str(project.get('tenant_id') or '').strip() == str(tenant_id).strip()
    ]

    if raw_command_stripped.lower().startswith("sys_setting:"):
        setting_result = _apply_sys_setting(raw_command_stripped, voice, ear)
        if setting_result is not None:
            return setting_result

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
            intelligent_service_start(proj, voice, ear, instances=instances)
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
                deleted, message = _delete_pm2_service(proj["name"], delete_logs=delete_logs)
                if not deleted:
                    broadcast(voice, message, color="text-red-400", speak=False)
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
            emit_event('log_stream_intent', {'service': matched_target})
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

            online_amrs = _online_virtual_amrs()
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
                    started = intelligent_service_start(matched_proj, voice, ear, instances=instances)
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
                    instance_args = f' --instances {instances}' if instances is not None else ''
                    proc = subprocess.run(f'"{PM2_EXECUTABLE}" start {target}{instance_args}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return {
                        "type": "start_result",
                        "target": target,
                        "ok": proc.returncode == 0,
                        "message": "Project started successfully." if proc.returncode == 0 else "PM2 start command failed.",
                    }
            else:
                broadcast(voice, f"Executing {action_intent.upper()} directive for {target}", color="text-emerald-400 font-bold", speak=True)
                if action_intent == 'delete':
                    deleted, message = _delete_pm2_service(target, delete_logs=delete_logs)
                    broadcast(voice, message, color="text-emerald-400" if deleted else "text-red-400", speak=False)
                else:
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
