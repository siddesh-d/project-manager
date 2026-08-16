import subprocess
import socket
import time
import json
import os
import re
import threading

from jarvis_assistant.config import PM2_EXECUTABLE

# Background-polled cache so get_host_metrics() never blocks the telemetry loop
_cached_host_metrics = None
_host_metrics_lock = threading.Lock()


def _fallback_host_metrics():
    if os.name == "nt":
        cpu_out = subprocess.check_output('wmic cpu get loadpercentage', shell=True, text=True)
        cpu_match = re.search(r'\d+', cpu_out)
        cpu = float(cpu_match.group()) if cpu_match else 0.0

        mem_out = subprocess.check_output('wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /Value', shell=True, text=True)
        free_mem = float(re.search(r'FreePhysicalMemory=(\d+)', mem_out).group(1))
        tot_mem = float(re.search(r'TotalVisibleMemorySize=(\d+)', mem_out).group(1))
        mem = ((tot_mem - free_mem) / tot_mem) * 100
        return cpu, mem

    cpu_count = os.cpu_count() or 1
    load1 = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    cpu = min((load1 / cpu_count) * 100, 100)

    mem = 0.0
    with open('/proc/meminfo', 'r', encoding='utf-8') as f:
        values = {}
        for line in f:
            key, value = line.split(':', 1)
            values[key] = float(value.strip().split()[0])
    total = values.get('MemTotal', 0.0)
    available = values.get('MemAvailable', 0.0)
    if total > 0:
        mem = ((total - available) / total) * 100

    return cpu, mem


def _poll_host_metrics():
    """Polls true OS host metrics natively, completely bypassing PM2 CLI scraping limitations."""
    global _cached_host_metrics
    has_psutil = False

    try:
        import psutil
        has_psutil = True
        psutil.cpu_percent()  # Prime CPU measurement
    except ImportError:
        pass

    while True:
        try:
            if has_psutil:
                import psutil
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory().percent
            else:
                cpu, mem = _fallback_host_metrics()
                time.sleep(1)

            with _host_metrics_lock:
                _cached_host_metrics = {"cpu": round(cpu, 1), "ram": round(mem, 1)}
        except Exception:
            pass
        time.sleep(2)


def start_host_metrics_poller():
    t = threading.Thread(target=_poll_host_metrics, daemon=True)
    t.start()


def get_host_metrics():
    with _host_metrics_lock:
        return _cached_host_metrics


def is_port_open(port):
    """Checks port availability across IPv4 loopback and localhost."""
    for host in ['127.0.0.1', 'localhost']:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex((host, port)) == 0:
                    return True
        except Exception:
            continue
    return False


def get_pm2_process_info(pm2_name):
    """Queries the live PM2 daemon registry."""
    try:
        env = os.environ.copy()
        env["NODE_NO_WARNINGS"] = "1"
        result = subprocess.run(
            [PM2_EXECUTABLE, 'jlist'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        output = result.stdout.strip()
        processes = []

        # Read lines in reverse to locate the JSON payload
        for line in reversed(output.split('\n')):
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                try:
                    processes = json.loads(line)
                    break
                except Exception:
                    continue

        for proc in processes:
            if proc.get('name') == pm2_name:
                return {
                    "status": proc.get('pm2_env', {}).get('status'),
                    "restarts": proc.get('pm2_env', {}).get('restart_time', 0)
                }
    except Exception:
        pass
    return None


def wait_for_service_stability(pm2_name, port, startup_event=None, timeout=45):
    """
    Verifies service health by prioritizing explicit log-based boot signatures.
    If no logs are found, falls back to port and process flap-detection.
    """
    if startup_event and startup_event.is_set():
        return True

    start_time = time.time()
    print(f"[SYSTEM DIAGNOSTIC]: Waiting for boot confirmation for '{pm2_name}' (Timeout: {timeout}s)...")

    while time.time() - start_time < timeout:
        if startup_event and startup_event.is_set():
            time.sleep(1)
            return True

        pm2_info = get_pm2_process_info(pm2_name)
        if pm2_info and pm2_info["status"] == "online":
            if is_port_open(port):
                time.sleep(3)
                post_pm2_info = get_pm2_process_info(pm2_name)
                if post_pm2_info and post_pm2_info["restarts"] == pm2_info["restarts"] and post_pm2_info["status"] == "online":
                    return True

        time.sleep(1.5)

    return False


def monitor_pm2_logs(pm2_name, friendly_name, voice, startup_event=None):
    """Tails PM2 logs to catch errors and confirm successful boot sequences."""
    time.sleep(2)
    process = subprocess.Popen(
        [PM2_EXECUTABLE, 'logs', pm2_name, '--raw'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    success_signatures = [
        "nest application successfully started",
        "listening on port",
        "server is running",
        "database connected"
    ]

    for line in iter(process.stdout.readline, ''):
        line = line.strip()
        if not line:
            continue

        if startup_event and not startup_event.is_set():
            lower_line = line.lower()
            if any(sig in lower_line for sig in success_signatures):
                print(f"\n[SYSTEM]: Validated boot signature for {friendly_name} -> '{line}'")
                startup_event.set()

        if "EADDRINUSE" in line:
            voice.speak_async(f"Alert. The port for {friendly_name} is already occupied.")
        elif "Cannot find module" in line or "ERR_MODULE_NOT_FOUND" in line:
            voice.speak_async(f"Alert. A critical Node module is missing in {friendly_name}.")
        elif "MongoParseError" in line or "MongoTimeoutError" in line:
            voice.speak_async(f"Database connection failed for {friendly_name}.")