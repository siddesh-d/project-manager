import time
import threading
import subprocess
import json
import os
import shutil

from jarvis_assistant.services.voice import JarvisVoiceEngine
from jarvis_assistant.services.ear import JarvisMultimodalEar
# FIXED: Imported `broadcast` so main.py can stream logs to the UI during pre-flight checks
from jarvis_assistant.core.command_center import display_advanced_status, process_command, broadcast, _load_settings_file
from jarvis_assistant.config import (
    get_port_from_env,
    SETTINGS_FILE,
    PM2_EXECUTABLE,
    PM2_FIELDS,
    PM2_TELEMETRY_REFRESH_SECONDS,
    ENABLE_PREFLIGHT_CHECKS,
    APACHE_HTTPD_PATH,
    APACHE_CHECK_CMD,
    APACHE_START_CMD,
    REDIS_CHECK_CMD,
    REDIS_START_CMD,
    RABBITMQ_CONTAINER_NAME,
)
from jarvis_assistant.registry.projects import get_projects

from jarvis_assistant.services import web_server
from jarvis_assistant.core import boot_sequence
from jarvis_assistant.services import pm2_manager

def handle_ui_command_routing(command_text, tenant_id=None):
    """Routes commands arriving via the web input straight into the core processor."""
    return process_command(command_text, voice_engine, ear_engine, tenant_id=tenant_id)

def live_telemetry_loop():
    """Polls real active PM2 numbers directly from the OS and pushes to the web dashboard."""
    while True:
        try:
            env = os.environ.copy()
            env["NODE_NO_WARNINGS"] = "1"
            result = subprocess.run([PM2_EXECUTABLE, 'jlist'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            if result.returncode == 0:
                output = result.stdout.strip()
                processes = []
                
                # ULTIMATE SHIELD: Ignore PM2 update nags
                for line in reversed(output.split('\n')):
                    line = line.strip()
                    if line.startswith('[') and line.endswith(']'):
                        try:
                            processes = json.loads(line)
                            break
                        except Exception:
                            continue
                
                metrics = []
                seen_core_services = set()
                
                for p in processes:
                    name = p.get("name", "N/A")
                    status = p.get("pm2_env", {}).get("status", "offline")
                    seen_core_services.add(name)
                    
                    monit = p.get("monit") or {}
                    cpu = monit.get("cpu", 0)
                    mem_bytes = monit.get("memory", 0)
                    mem_mb = f"{int(mem_bytes / (1024 * 1024))}MB"
                    
                    port = "N/A"
                    for proj in get_projects():
                        if proj["name"] == name:
                            port = get_port_from_env(proj["path"])
                            break
                    
                    metric_entry = {
                        "name": name,
                        "status": status,
                        "cpu": cpu,
                        "memory": mem_mb,
                        "port": port
                    }
                    for field_name, enabled in PM2_FIELDS.items():
                        if field_name in {"name", "status", "cpu", "memory", "port"}:
                            continue
                        if not enabled:
                            continue
                        if field_name == "uptime":
                            metric_entry["uptime"] = p.get("pm2_env", {}).get("pm_uptime") or p.get("pm2_env", {}).get("uptime") or '0s'
                        elif field_name == "restarts":
                            metric_entry["restarts"] = int(p.get("pm2_env", {}).get("restart_time") or p.get("pm2_env", {}).get("restarts") or 0)
                        elif field_name == "user":
                            metric_entry["user"] = p.get("pm2_env", {}).get("user") or "N/A"
                        elif field_name == "watching":
                            metric_entry["watching"] = bool(p.get("pm2_env", {}).get("watch") or p.get("pm2_env", {}).get("watching") or False)
                        elif field_name == "pid":
                            metric_entry["pid"] = p.get("pid") or "N/A"
                        elif field_name == "namespace":
                            metric_entry["namespace"] = p.get("pm2_env", {}).get("namespace") or "default"
                        elif field_name == "mode":
                            metric_entry["mode"] = p.get("pm2_env", {}).get("mode") or "fork"
                        elif field_name == "version":
                            metric_entry["version"] = p.get("pm2_env", {}).get("version") or p.get("version") or "N/A"
                    metrics.append(metric_entry)
                
                for proj in get_projects():
                    if proj["name"] not in seen_core_services:
                        metrics.append({
                            "name": proj["name"],
                            "status": "removed",
                            "cpu": 0,
                            "memory": "0MB",
                            "port": get_port_from_env(proj["path"])
                        })
                
                web_server.socketio.emit('pm2_telemetry', {'services': metrics, 'host': pm2_manager.get_host_metrics()})
                
        except Exception as e:
            print(f"[METRICS CRASH]: {e}")
            
        time.sleep(PM2_TELEMETRY_REFRESH_SECONDS)
        
# =====================================================================
# PRE-FLIGHT DEPENDENCY CHECKER
# =====================================================================
def pre_flight_checks(voice):
    """Verifies Apache, Redis, and optionally RabbitMQ before PM2 boots."""
    if not ENABLE_PREFLIGHT_CHECKS:
        broadcast(voice, "Pre-flight dependency checks are disabled by configuration.", color="text-amber-400", speak=False)
        return
    
    # 1. Check Apache (optional, Windows-oriented by default)
    if APACHE_CHECK_CMD and APACHE_START_CMD:
        broadcast(voice, "Checking Apache Web Server...", color="text-cyan-600", speak=False)
        try:
            apache_check = subprocess.run(APACHE_CHECK_CMD, shell=True, capture_output=True, text=True)
            if "httpd.exe" not in apache_check.stdout and "running" not in apache_check.stdout.lower():
                broadcast(voice, "Apache is offline. Attempting startup...", color="text-amber-400", speak=True)
                if APACHE_HTTPD_PATH and os.path.exists(APACHE_HTTPD_PATH):
                    creation_flags = 0
                    if os.name == 'nt':
                        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                    subprocess.Popen(APACHE_HTTPD_PATH, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creation_flags)
                else:
                    subprocess.run(APACHE_START_CMD, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(2)
        except Exception as e:
            print(f"[SYSTEM]: Apache check failed - {e}")

    # 2. Check Redis
    if REDIS_CHECK_CMD:
        broadcast(voice, "Checking Redis service...", color="text-cyan-600", speak=False)
        try:
            redis_check = subprocess.run(REDIS_CHECK_CMD, shell=True, capture_output=True, text=True)
            if "PONG" not in redis_check.stdout:
                broadcast(voice, "Redis is offline. Attempting startup...", color="text-amber-400", speak=True)
                if REDIS_START_CMD:
                    subprocess.run(REDIS_START_CMD, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(2)
        except Exception as e:
            print(f"[SYSTEM]: Redis check failed - {e}")

    # 3. Check RabbitMQ (Docker) - Optional for MQTT
    requires_mqtt = any(proj.get("name") == "mqtt" for proj in get_projects())
    if requires_mqtt:
        broadcast(voice, "Checking Docker RabbitMQ...", color="text-cyan-600", speak=False)
        try:
            if not shutil.which("docker"):
                return
            rmq_check = subprocess.run(
                f'docker ps -f "name={RABBITMQ_CONTAINER_NAME}" --format "{{{{.Names}}}}"',
                shell=True,
                capture_output=True,
                text=True,
            )
            if RABBITMQ_CONTAINER_NAME.lower() not in rmq_check.stdout.lower():
                broadcast(voice, "Rabbit M Q is offline. Starting Docker container...", color="text-amber-400", speak=True)
                subprocess.run(f"docker start {RABBITMQ_CONTAINER_NAME}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(3)
        except Exception as e:
            print(f"[SYSTEM]: RabbitMQ check failed - {e}")

def boot_orchestrator(voice, ear, ui_log_fn):
    """Wrapper to run external dependencies before the main boot sequence."""
    time.sleep(3) # Wait 3 seconds to ensure the WebSocket UI is connected
    
    broadcast(voice, "Initiating pre-flight dependency checks...", color="text-emerald-400 font-bold", speak=True, wait=True)
    pre_flight_checks(voice)
    broadcast(voice, "External dependencies verified. Proceeding with PM2 assessment.", color="text-emerald-400", speak=False)
    
    # Hand over to the original PM2 boot sequence
    boot_sequence.execute_core_boot_sequence(voice, ear, ui_log_fn)

# =====================================================================
# SYSTEM ENTRY POINT
# =====================================================================
def run():
    global voice_engine, ear_engine
    voice_engine = JarvisVoiceEngine()
    ear_engine = JarvisMultimodalEar()

    settings = _load_settings_file()

    # INITIALIZE HARDWARE STATE
    if settings["engine"] == "browser":
        voice_engine.muted = True
        ear_engine.mic_enabled = False
        print("[SYSTEM]: Booting in BROWSER Voice Mode. Hardware muted.")
    else:
        voice_engine.muted = not settings.get("speaker", False)
        ear_engine.mic_enabled = settings.get("mic", False)
        print("[SYSTEM]: Booting in LEGACY Hardware Voice Mode.")

    web_server._ui_command_callback = handle_ui_command_routing

    init_thread = threading.Thread(
        target=boot_orchestrator, 
        args=(voice_engine, ear_engine, web_server.stream_log_to_ui), 
        daemon=True
    )
    init_thread.start()

    web_server.start_web_server()


if __name__ == "__main__":
    run()