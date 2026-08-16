import os
import subprocess
import time
import json
import threading
import queue

from jarvis_assistant.config import get_port_from_env, PM2_EXECUTABLE
from jarvis_assistant.registry.projects import get_projects
from jarvis_assistant.services import pm2_manager
from jarvis_assistant.core.command_center import run_standby_loop, broadcast, ask_question, intelligent_service_start

def handle_service_failure(project, port, voice, ear):
    pm2_name = project["name"]
    friendly_name = project["friendly_name"]
    path = project["path"]

    prompt = f"Alert. {friendly_name} failed to come online. Would you like me to retry, perform a clean rebuild, delete the service, or skip?"
    response = ask_question(voice, ear, prompt, timeout=15.0)
    
    if not response:
        broadcast(voice, f"No response. Skipping {friendly_name}.", color="text-amber-500", speak=True)
        return False
        
    command = str(response).lower()
    
    if "retry" in command:
        broadcast(voice, f"Understood. Force restarting {friendly_name}.", color="text-amber-400", speak=True)
        subprocess.run(f'"{PM2_EXECUTABLE}" restart {pm2_name}', shell=True, stdout=subprocess.DEVNULL)
        if pm2_manager.wait_for_service_stability(pm2_name, port, timeout=45):
            broadcast(voice, f"Recovery successful. {friendly_name} is online.", color="text-emerald-400", speak=True)
            return True
            
    elif "rebuild" in command or "clean" in command:
        broadcast(voice, f"Initiating clean reset for {friendly_name}.", color="text-amber-400", speak=True)
        subprocess.run(f'"{PM2_EXECUTABLE}" delete {pm2_name}', shell=True, stdout=subprocess.DEVNULL)
        
        if "custom_start" in project:
            subprocess.run(project["custom_start"], cwd=path, shell=True, stdout=subprocess.DEVNULL)
        else:
            subprocess.run("npm run build", cwd=path, shell=True, stdout=subprocess.DEVNULL)
            subprocess.run(f'"{PM2_EXECUTABLE}" start dist/main.js --name "{pm2_name}"', cwd=path, shell=True, stdout=subprocess.DEVNULL)
            
        if pm2_manager.wait_for_service_stability(pm2_name, port, timeout=45):
            broadcast(voice, f"Recovery successful. {friendly_name} is online.", color="text-emerald-400", speak=True)
            return True
            
    elif "delete" in command or "remove" in command:
        broadcast(voice, f"Removing {friendly_name}.", color="text-amber-400", speak=True)
        subprocess.run(f'"{PM2_EXECUTABLE}" delete {pm2_name}', shell=True, stdout=subprocess.DEVNULL)
        return False
            
    elif "skip" in command or "leave" in command or "keep" in command:
        broadcast(voice, f"Skipping {friendly_name}.", speak=True)
        return False
        
    return False

def start_service(project, voice, ear):
    pm2_name = project["name"]
    friendly_name = project["friendly_name"]
    path = project["path"]

    if not os.path.exists(path):
        broadcast(voice, f"Directory missing for {friendly_name}.", color="text-rose-400", speak=True)
        return False

    port = get_port_from_env(path)
    broadcast(voice, f"Initializing {friendly_name} on port {port}.", color="text-zinc-300", speak=True)
    
    started = intelligent_service_start(project, voice, ear)
    if not started:
        return False

    startup_event = threading.Event() 
    log_thread = threading.Thread(target=pm2_manager.monitor_pm2_logs, args=(pm2_name, friendly_name, voice, startup_event), daemon=True)
    log_thread.start()

    if pm2_manager.wait_for_service_stability(pm2_name, port, startup_event, timeout=45):
        return True
    return handle_service_failure(project, port, voice, ear)

def launch_service_batch(project, voice):
    pm2_name = project["name"]
    friendly_name = project["friendly_name"]
    path = project["path"]

    if not os.path.exists(path):
        return None, None

    port = get_port_from_env(path)
    broadcast(voice, f"Initializing {friendly_name} on port {port}...", color="text-zinc-300", speak=False)

    started = intelligent_service_start(project, voice, None)
    if not started:
        return None, None

    startup_event = threading.Event() 
    log_thread = threading.Thread(target=pm2_manager.monitor_pm2_logs, args=(pm2_name, friendly_name, voice, startup_event), daemon=True)
    log_thread.start()
    return port, startup_event

def execute_core_boot_sequence(voice, ear, ui_log_fn=None):
    time.sleep(4) 
    broadcast(voice, "Hello. I am inspecting the current PM2 environment...", speak=True, wait=True)

    try:
        env = os.environ.copy()
        env["NODE_NO_WARNINGS"] = "1"
        result = subprocess.run([PM2_EXECUTABLE, 'jlist'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        
        if result.returncode == 0 and result.stdout.strip():
            output = result.stdout.strip()
            # NODE 22 SHIELD APPLIED HERE
            start_idx = output.find('[')
            end_idx = output.rfind(']') + 1
            if start_idx != -1 and end_idx > start_idx:
                processes = json.loads(output[start_idx:end_idx])
            else:
                processes = []
        else:
            processes = []
    except Exception:
        processes = []

    pm2_status_map = {p.get("name"): p.get("pm2_env", {}).get("status", "unknown") for p in processes}

    online_services = []
    offline_projects = []

    for proj in get_projects():
        name = proj["name"]
        status = pm2_status_map.get(name)
        if status == "online":
            online_services.append(name)
        else:
            offline_projects.append(proj)

    if not offline_projects:
        msg = (
            "I have completed a health check of the managed services. "
            "All required services are currently online and operating normally. "
            "I am now in standby mode and ready for commands."
        )
        broadcast(voice, msg, color="text-emerald-400 font-bold", speak=True)
        run_standby_loop(voice, ear)
        return

    summary_lines = ["I found that:"]
    for srv in online_services:
        summary_lines.append(f"- {srv} is online and healthy")
    for proj in offline_projects:
        summary_lines.append(f"- {proj['name']} is not currently running")
        
    summary_text = "\n".join(summary_lines)
    
    broadcast(voice, summary_text, color="text-cyan-300", speak=False)
    spoken_summary = f"I found that {len(online_services)} services are online, and {len(offline_projects)} services are offline."
    broadcast(voice, spoken_summary, speak=True, wait=True)

    if len(offline_projects) == 1:
        prompt = f"Would you like me to start the {offline_projects[0]['name']} service?"
    else:
        prompt = "Would you like me to start the missing services?"

    response = ask_question(voice, ear, prompt, timeout=10.0)

    if response and any(w in str(response).lower() for w in ["yes", "sure", "do it", "okay", "yep", "start", "proceed", "please"]):
        broadcast(voice, "Confirmed. Initializing missing services.", color="text-emerald-400", speak=True)
        
        failed = 0
        batch_data = {}
        
        for proj in offline_projects:
            port, event = launch_service_batch(proj, voice)
            batch_data[proj["name"]] = (port, event)
        
        for proj in offline_projects:
            port, event = batch_data[proj["name"]]
            if port and not pm2_manager.wait_for_service_stability(proj["name"], port, event, timeout=45):
                if not handle_service_failure(proj, port, voice, ear): 
                    failed += 1
                
        broadcast(voice, "Startup sequence complete. I am now in standby mode.", color="text-emerald-400", speak=True)
        
    else:
        cancel_msg = (
            "I have not received a confirmation. No action will be taken at this time. "
            "I will remain in standby mode. Let me know if you need anything."
        )
        broadcast(voice, cancel_msg, color="text-amber-500", speak=True)

    run_standby_loop(voice, ear)