"""Thin wrapper around the PM2 command line: process listing, status, logs and removal."""
import json
import os
import subprocess
import time

from assistant.config import PM2_EXECUTABLE


def _pm2_env():
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    return env


def parse_jlist_output(output):
    """Extract the JSON process list from `pm2 jlist` output, ignoring PM2 update banners."""
    for line in reversed(str(output or "").strip().split('\n')):
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            try:
                return json.loads(line)
            except Exception:
                continue
    return []


def fetch_pm2_processes(timeout=None):
    """Return the PM2 process list, or None when PM2 could not be queried."""
    try:
        result = subprocess.run(
            [PM2_EXECUTABLE, 'jlist'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_pm2_env(),
            timeout=timeout,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return parse_jlist_output(result.stdout)


def resolve_pm2_target(target_name):
    """Map a user-supplied name to the real PM2 process name (exact, then partial match)."""
    processes = fetch_pm2_processes() or []
    target_lower = target_name.lower().strip()
    for p in processes:
        real_name = p.get("name", "")
        if real_name.lower() == target_lower:
            return real_name
    for p in processes:
        real_name = p.get("name", "")
        if target_lower in real_name.lower():
            return real_name
    return target_name


def pm2_service_status(pm2_name):
    processes = fetch_pm2_processes(timeout=4) or []
    for process in processes:
        if process.get("name") == pm2_name:
            return str(process.get("pm2_env", {}).get("status", "")).strip().lower()
    return ""


def wait_pm2_online(pm2_name, timeout_seconds=6):
    end_at = time.time() + max(1, timeout_seconds)
    while time.time() < end_at:
        status = pm2_service_status(pm2_name)
        if status in {"online", "launching"}:
            return True, status
        if status in {"errored", "stopped", "one-launch-status"}:
            return False, status
        time.sleep(0.6)
    return False, pm2_service_status(pm2_name)


def recent_pm2_logs(pm2_name, lines=60):
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


def looks_like_missing_module_error(text):
    lowered = str(text or "").lower()
    return any(token in lowered for token in ("cannot find module", "err_module_not_found", "module_not_found"))


def delete_pm2_service(pm2_name, delete_logs=False):
    log_paths = set()
    if delete_logs:
        try:
            result = subprocess.run(
                [PM2_EXECUTABLE, 'jlist'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=_pm2_env(), timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False, 'Unable to read PM2 log paths; service was not removed.'
        processes = None
        if result.returncode == 0:
            for line in reversed(result.stdout.strip().splitlines()):
                try:
                    candidate = json.loads(line)
                except ValueError:
                    continue
                if isinstance(candidate, list):
                    processes = candidate
                    break
        if processes is None:
            return False, 'Unable to read PM2 log paths; service was not removed.'
        for proc in processes:
            if str(proc.get('name') or '').lower() != str(pm2_name).lower():
                continue
            pm2_env = proc.get('pm2_env') or {}
            for field in ('pm_out_log_path', 'pm_err_log_path', 'pm_log_path'):
                path = pm2_env.get(field)
                if path and os.path.isabs(path):
                    log_paths.add(os.path.abspath(path))

    try:
        command = subprocess.list2cmdline([PM2_EXECUTABLE, 'delete', pm2_name])
        result = subprocess.run(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False, 'Unable to execute PM2 delete.'
    if result.returncode != 0:
        return False, 'PM2 could not remove the service; its logs were kept.'

    failed_paths = []
    for path in log_paths:
        try:
            if os.path.isfile(path):
                os.unlink(path)
        except OSError:
            failed_paths.append(path)
    if failed_paths:
        return True, f'Service removed, but {len(failed_paths)} log file(s) could not be deleted.'
    return True, 'Service removed and selected log files deleted.' if delete_logs else 'Service removed; log files were kept.'
