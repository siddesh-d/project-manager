"""Project runtime preparation helpers: command environment, dependency install and build detection."""
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import threading

from assistant.services import pm2_cli

NODE_PACKAGE_MANAGERS = {"npm", "yarn", "pnpm"}

# Live stage of in-flight start operations, keyed by lowercase project name.
_active_stages = {}
_active_stages_lock = threading.Lock()


def set_active_stage(name, stage):
    key = str(name or "").lower()
    with _active_stages_lock:
        if stage:
            _active_stages[key] = stage
        else:
            _active_stages.pop(key, None)


def get_active_stage(name):
    with _active_stages_lock:
        return _active_stages.get(str(name or "").lower())


def build_command_env(extra_env=None):
    env = os.environ.copy()
    if isinstance(extra_env, dict):
        for key, value in extra_env.items():
            if key:
                env[str(key)] = str(value)

    merged_paths = []
    seen = set()

    def add_segments(raw_path):
        for segment in str(raw_path or "").split(os.pathsep):
            seg = segment.strip()
            if not seg:
                continue
            key = os.path.normcase(seg)
            if key in seen:
                continue
            seen.add(key)
            merged_paths.append(seg)

    add_segments(env.get("PATH"))
    add_segments(os.getenv("EXTRA_BIN_PATH"))

    if os.name != "nt":
        add_segments(os.pathsep.join([
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/local/sbin",
            "/usr/sbin",
            "/sbin",
            "/opt/homebrew/bin",
            "/home/linuxbrew/.linuxbrew/bin",
        ]))

    env["PATH"] = os.pathsep.join(merged_paths)
    return env


def run_command_with_output(command, cwd, extra_env=None):
    env = build_command_env(extra_env)
    process = subprocess.run(
        command,
        cwd=cwd,
        shell=isinstance(command, str),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return process.returncode, process.stdout or ""


def resolve_executable(command_name, env=None):
    if not command_name:
        return None

    env = env or build_command_env({})
    token = str(command_name).strip()
    if not token:
        return None

    if any(ch in token for ch in ('/', '\\')):
        return token if os.path.exists(token) else None

    candidates = [token]
    if os.name == "nt":
        lowered = token.lower()
        if lowered in NODE_PACKAGE_MANAGERS:
            candidates = [f"{lowered}.cmd", f"{lowered}.exe", lowered]

    search_path = env.get("PATH")
    for candidate in candidates:
        resolved = shutil.which(candidate, path=search_path)
        if resolved:
            return resolved
    return None


def detect_node_package_manager(path):
    if os.path.exists(os.path.join(path, "pnpm-lock.yaml")):
        return "pnpm"
    if os.path.exists(os.path.join(path, "yarn.lock")):
        return "yarn"
    return "npm"


def _missing_node_tool_message(tool):
    return (
        f"{tool} is not installed or not available in PATH. "
        f"Install Node.js tooling ({tool}) and retry. "
        "If launching with sudo, ensure PATH includes standard binary folders "
        "or set EXTRA_BIN_PATH."
    )


def prepare_install_command(install_command, project_type, project_path, extra_env=None):
    """Return (command, error). Resolves the executable and checks prerequisites."""
    env = build_command_env(extra_env)

    if isinstance(install_command, (list, tuple)):
        command_list = [str(part) for part in install_command if str(part).strip()]
    else:
        command_text = str(install_command or "").strip()
        if not command_text:
            return None, None
        command_list = None

    if command_list:
        executable_token = command_list[0]
        resolved = resolve_executable(executable_token, env)
        if not resolved:
            lowered = executable_token.lower()
            if lowered in NODE_PACKAGE_MANAGERS:
                return None, _missing_node_tool_message(lowered)
            return None, f"Required command '{executable_token}' is not available in PATH."
        command_list[0] = resolved
        return command_list, None

    try:
        tokens = shlex.split(command_text, posix=(os.name != "nt"))
    except ValueError:
        tokens = command_text.split()

    if tokens:
        lowered = tokens[0].lower()
        if lowered in NODE_PACKAGE_MANAGERS and not resolve_executable(lowered, env):
            return None, _missing_node_tool_message(lowered)

    if project_type == "node" and not os.path.exists(os.path.join(project_path, "package.json")):
        return None, "package.json is missing for Node project dependency install."

    return command_text, None


def load_dotenv_vars(project_path):
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


def derive_install_command(path, profile):
    configured = str(profile.get("install_command") or "").strip()
    if configured:
        return configured

    project_type = str(profile.get("project_type") or "custom")
    if project_type == "node":
        manager = detect_node_package_manager(path)
        if manager == "pnpm":
            return ["pnpm", "install", "--frozen-lockfile"]
        if manager == "yarn":
            return ["yarn", "install", "--frozen-lockfile"]
        if os.path.exists(os.path.join(path, "package-lock.json")):
            return ["npm", "ci"]
        return ["npm", "install"]
    if project_type == "python" and os.path.exists(os.path.join(path, "requirements.txt")):
        return [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
    return ""


def runtime_profile(proj):
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


def validate_project_requirements(proj, profile):
    path = proj.get("path", "")
    errors = []

    if not os.path.isdir(path):
        errors.append("Project directory is missing on disk.")
        return errors

    for req in profile.get("required_files") or []:
        if not os.path.exists(os.path.join(path, req)):
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


def install_fingerprint(path, profile):
    project_type = str(profile.get("project_type") or "custom")
    if project_type == "node":
        return _fingerprint_files(path, ["package-lock.json", "package.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"])
    if project_type == "python":
        return _fingerprint_files(path, ["requirements.txt", "pyproject.toml", "poetry.lock"])
    return ""


def build_fingerprint(path, profile):
    base = _fingerprint_files(path, ["package.json", "package-lock.json", "tsconfig.json", "webpack.config.js"])
    tree = _source_tree_signature(path)
    return f"{base}:{tree}"


def needs_build(path, profile, runtime_state):
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
        current = build_fingerprint(path, profile)
        previous = str(runtime_state.get("build_fingerprint") or "")
        return current != previous

    return False


def start_pm2_entry(pm2_name, path, entry_command, extra_env=None):
    code, _output = run_command_with_output(entry_command, path, extra_env=extra_env)
    if code != 0:
        return False, f"PM2 start command failed (exit {code})."

    online, status = pm2_cli.wait_pm2_online(pm2_name)
    if online:
        return True, ""

    logs = pm2_cli.recent_pm2_logs(pm2_name)
    if logs.strip():
        return False, logs[-1200:]
    return False, f"PM2 process status is '{status or 'unknown'}'."
