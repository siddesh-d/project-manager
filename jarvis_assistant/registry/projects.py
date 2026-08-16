import os
import re
import json
import stat
import string
import fnmatch
import threading
import shutil
from pathlib import Path

from jarvis_assistant.config import PROJECTS_FILE

# =====================================================================
# JSON-BACKED PROJECT REGISTRY
# =====================================================================
PROJECTS_FILE = str(PROJECTS_FILE)

_LEGACY_DEFAULTS = []

_NAME_PATTERN = re.compile(r'^[A-Za-z0-9._-]{1,40}$')
_DEPLOY_FILE_CANDIDATES = [".jarvisdeploy.json", "jarvis.deploy.json"]
_COMMON_EXCLUDES = [
    ".git/**",
    ".svn/**",
    ".hg/**",
    "__pycache__/**",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "Thumbs.db",
]

_lock = threading.Lock()
_projects = None
_core_project_path = ""


def _expand_project_path(path_value):
    if not isinstance(path_value, str):
        return ""

    expanded = path_value.replace("${HOME}", str(Path.home())).replace("$HOME", str(Path.home()))
    expanded = os.path.expandvars(os.path.expanduser(expanded))
    return os.path.normpath(expanded)


def _to_portable_path(path_value):
    normalized = os.path.normpath(path_value)
    home = os.path.normpath(str(Path.home()))

    try:
        rel_to_home = os.path.relpath(normalized, home)
        if not rel_to_home.startswith(".."):
            return "${HOME}/" + rel_to_home.replace("\\", "/")
    except Exception:
        pass

    return normalized.replace("\\", "/")


def _normalize_core_path(path_value):
    if not isinstance(path_value, str):
        return ""
    value = path_value.strip()
    if not value:
        return ""
    return _expand_project_path(value)


def _detect_project_type(project_path):
    path = Path(project_path)
    if (path / "package.json").exists():
        return "node"
    if (path / "requirements.txt").exists() or (path / "pyproject.toml").exists():
        return "python"
    return "custom"


def _default_deployment_profile(project_type):
    base = {
        "project_type": project_type,
        "include_paths": ["**"],
        "exclude_paths": list(_COMMON_EXCLUDES),
        "required_files": [],
        "env_mode": "optional",
        "install_command": "",
        "build_command": "",
        "build_policy": "if_missing",
        "runtime_entry": "",
        "auto_install": True,
        "auto_build": True,
    }

    if project_type == "node":
        base["exclude_paths"] = base["exclude_paths"] + [
            "node_modules/**",
            ".next/**",
            ".nuxt/**",
            "coverage/**",
        ]
        base["required_files"] = ["package.json"]
        base["install_command"] = "npm install"
        base["build_command"] = "npm run build"
        base["runtime_entry"] = "dist/main.js"
    elif project_type == "python":
        base["exclude_paths"] = base["exclude_paths"] + [
            ".venv/**",
            "venv/**",
            ".mypy_cache/**",
            ".pytest_cache/**",
        ]
        base["required_files"] = []
        base["install_command"] = "pip install -r requirements.txt"
        base["build_command"] = ""
        base["runtime_entry"] = ""

    return base


def _normalize_list_of_paths(value):
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = str(item or "").strip().replace("\\", "/")
        if text:
            items.append(text)
    return items


def _load_project_deploy_file(project_path):
    for filename in _DEPLOY_FILE_CANDIDATES:
        candidate = Path(project_path) / filename
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            with candidate.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _merge_deployment_profile(base, override):
    merged = dict(base)
    if not isinstance(override, dict):
        return merged

    scalar_keys = {
        "project_type",
        "env_mode",
        "install_command",
        "build_command",
        "build_policy",
        "runtime_entry",
    }
    bool_keys = {"auto_install", "auto_build"}

    for key in scalar_keys:
        if key in override and str(override[key]).strip() != "":
            merged[key] = str(override[key]).strip()

    for key in bool_keys:
        if key in override:
            merged[key] = bool(override[key])

    if "include_paths" in override:
        merged["include_paths"] = _normalize_list_of_paths(override.get("include_paths"))
    if "exclude_paths" in override:
        merged["exclude_paths"] = _normalize_list_of_paths(override.get("exclude_paths"))
    if "required_files" in override:
        merged["required_files"] = _normalize_list_of_paths(override.get("required_files"))

    return merged


def _normalize_deployment_profile(profile, project_path):
    project_type = _detect_project_type(project_path)
    base = _default_deployment_profile(project_type)

    from_registry = profile if isinstance(profile, dict) else {}
    merged = _merge_deployment_profile(base, from_registry)

    file_profile = _load_project_deploy_file(project_path)
    merged = _merge_deployment_profile(merged, file_profile)

    merged["project_type"] = str(merged.get("project_type") or project_type).strip().lower() or project_type
    merged["env_mode"] = str(merged.get("env_mode") or "optional").strip().lower()
    if merged["env_mode"] not in {"required", "optional", "template_only"}:
        merged["env_mode"] = "optional"

    merged["build_policy"] = str(merged.get("build_policy") or "if_missing").strip().lower()
    if merged["build_policy"] not in {"never", "if_missing", "always", "on_change"}:
        merged["build_policy"] = "if_missing"

    if not merged.get("include_paths"):
        merged["include_paths"] = ["**"]

    merged["exclude_paths"] = _normalize_list_of_paths(merged.get("exclude_paths", []))
    merged["required_files"] = _normalize_list_of_paths(merged.get("required_files", []))

    return merged


def _normalize_relpath(path_value):
    rel = str(path_value).replace("\\", "/").strip("/")
    return rel


def _matches_pattern(rel_path, pattern):
    rel = _normalize_relpath(rel_path)
    pat = _normalize_relpath(pattern)
    if not pat:
        return False

    if pat == "**":
        return True
    if pat.endswith("/**"):
        base = pat[:-3]
        return rel == base or rel.startswith(base + "/")
    if "/" not in pat and fnmatch.fnmatch(os.path.basename(rel), pat):
        return True
    return fnmatch.fnmatch(rel, pat)


def _is_excluded(rel_path, exclude_patterns):
    return any(_matches_pattern(rel_path, p) for p in (exclude_patterns or []))


def _is_included(rel_path, include_patterns):
    include_patterns = include_patterns or ["**"]
    return any(_matches_pattern(rel_path, p) for p in include_patterns)


def _iter_selected_files(source_root, include_patterns, exclude_patterns):
    for root, dirs, files in os.walk(source_root):
        rel_root = _normalize_relpath(os.path.relpath(root, source_root))
        pruned_dirs = []
        for dirname in dirs:
            rel_dir = _normalize_relpath(os.path.join(rel_root, dirname))
            if _is_excluded(rel_dir, exclude_patterns):
                continue
            pruned_dirs.append(dirname)
        dirs[:] = pruned_dirs

        for filename in files:
            rel_path = _normalize_relpath(os.path.join(rel_root, filename))
            if _is_excluded(rel_path, exclude_patterns):
                continue
            if not _is_included(rel_path, include_patterns):
                continue
            yield rel_path


def _copy_file_if_changed(source_file, target_file):
    try:
        src_stat = os.stat(source_file)
        if os.path.exists(target_file):
            dst_stat = os.stat(target_file)
            if src_stat.st_size == dst_stat.st_size and int(src_stat.st_mtime) == int(dst_stat.st_mtime):
                return False
    except OSError:
        pass

    os.makedirs(os.path.dirname(target_file), exist_ok=True)
    shutil.copy2(source_file, target_file)
    return True


def _sync_project_tree(source_root, target_root, deployment_profile, prune=False):
    include_patterns = deployment_profile.get("include_paths") or ["**"]
    exclude_patterns = deployment_profile.get("exclude_paths") or []

    os.makedirs(target_root, exist_ok=True)

    copied = 0
    skipped = 0
    selected = set()

    for rel_path in _iter_selected_files(source_root, include_patterns, exclude_patterns):
        selected.add(rel_path)
        source_file = os.path.join(source_root, rel_path)
        target_file = os.path.join(target_root, rel_path)
        if _copy_file_if_changed(source_file, target_file):
            copied += 1
        else:
            skipped += 1

    removed = 0
    if prune:
        for root, _, files in os.walk(target_root):
            rel_root = _normalize_relpath(os.path.relpath(root, target_root))
            for filename in files:
                rel_path = _normalize_relpath(os.path.join(rel_root, filename))
                if rel_path not in selected and _is_included(rel_path, include_patterns):
                    try:
                        os.remove(os.path.join(target_root, rel_path))
                        removed += 1
                    except OSError:
                        pass

    return {"copied": copied, "skipped": skipped, "removed": removed}


def _normalize_project_entry(project):
    if not isinstance(project, dict):
        return None

    name = str(project.get("name", "")).strip()
    friendly_name = str(project.get("friendly_name", name)).strip() or name
    raw_path = project.get("path", "")
    path = _expand_project_path(raw_path)

    normalized = {
        "name": name,
        "friendly_name": friendly_name,
        "path": path,
    }

    deployment_profile = _normalize_deployment_profile(project.get("deployment_profile", {}), path)
    normalized["deployment_profile"] = deployment_profile

    runtime_state = project.get("runtime_state") if isinstance(project.get("runtime_state"), dict) else {}
    normalized["runtime_state"] = dict(runtime_state)

    custom_start = project.get("custom_start")
    if custom_start:
        normalized["custom_start"] = str(custom_start)

    return normalized


def _write_projects(project_list, core_project_path=""):
    """Atomic write: telemetry daemons read this list every 2-3 seconds."""
    tmp_path = PROJECTS_FILE + ".tmp"
    portable_projects = []
    for project in project_list:
        portable_entry = dict(project)
        portable_entry["path"] = _to_portable_path(portable_entry.get("path", ""))
        portable_projects.append(portable_entry)

    payload = {
        "core_project_path": _to_portable_path(core_project_path) if core_project_path else "",
        "projects": portable_projects,
    }

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, PROJECTS_FILE)


def _resolve_target_path(source_path, storage_mode, destination_path=None, core_project_path=""):
    source = _expand_project_path(source_path)
    mode = (storage_mode or "current").strip().lower()

    if mode == "current":
        return source, None

    if mode == "core":
        explicit_core_path = _normalize_core_path(destination_path or "")
        base = explicit_core_path or _normalize_core_path(core_project_path)
        if not base:
            return None, "Core Project Path is not configured."
    elif mode == "custom":
        base = _normalize_core_path(destination_path or "")
        if not base:
            return None, "Custom destination path is required."
    else:
        return None, "Invalid storage mode."

    try:
        os.makedirs(base, exist_ok=True)
    except Exception as e:
        return None, f"Cannot create destination folder: {e}"

    if not os.path.isdir(base):
        return None, "Destination path is not a directory."

    folder_name = os.path.basename(source.rstrip("\\/"))
    if not folder_name:
        return None, "Unable to derive source folder name."

    return os.path.normpath(os.path.join(base, folder_name)), None


def load_projects():
    global _projects, _core_project_path
    with _lock:
        if not os.path.exists(PROJECTS_FILE):
            _projects = [dict(p) for p in _LEGACY_DEFAULTS]
            _core_project_path = ""
            _write_projects(_projects, _core_project_path)
            return _projects

        try:
            with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                loaded = data
                _core_project_path = ""
            else:
                loaded = data.get("projects")
                _core_project_path = _normalize_core_path(data.get("core_project_path", ""))

            if not isinstance(loaded, list):
                raise ValueError("Invalid projects file structure")
            _projects = []
            for item in loaded:
                normalized = _normalize_project_entry(item)
                if normalized and normalized["name"]:
                    _projects.append(normalized)
        except Exception:
            try:
                os.replace(PROJECTS_FILE, PROJECTS_FILE + ".bak")
            except Exception:
                pass
            _projects = [dict(p) for p in _LEGACY_DEFAULTS]
            _core_project_path = ""
            _write_projects(_projects, _core_project_path)

        return _projects


def get_projects():
    if _projects is None:
        return load_projects()
    return _projects


def get_project(name):
    name_lower = str(name or "").strip().lower()
    for project in get_projects():
        if project.get("name", "").lower() == name_lower:
            return project
    return None


def get_core_project_path():
    if _projects is None:
        load_projects()
    return _core_project_path


def set_core_project_path(path):
    normalized = _normalize_core_path(path)
    if not normalized:
        return False, "Core Project Path cannot be empty."

    try:
        os.makedirs(normalized, exist_ok=True)
    except Exception as e:
        return False, f"Unable to create/access core path: {e}"

    if not os.path.isdir(normalized):
        return False, "Core Project Path is not a directory."

    with _lock:
        global _core_project_path
        _core_project_path = normalized
        _write_projects(get_projects(), _core_project_path)

    return True, None


def is_path_within_core(path):
    core = _normalize_core_path(get_core_project_path())
    target = _expand_project_path(path)
    if not core or not target:
        return False

    try:
        return os.path.commonpath([core, target]) == core
    except Exception:
        return False


def add_project(name, friendly_name, path, custom_start=None, storage_mode="current", destination_path=None, tenant_id=None, tenant_root=None):
    name = (name or "").strip()
    friendly_name = (friendly_name or "").strip() or name
    path = _expand_project_path((path or "").strip())
    custom_start = (custom_start or "").strip()
    tenant_id = str(tenant_id or "").strip() or None
    tenant_root = _normalize_core_path(tenant_root) if tenant_root else None

    if not _NAME_PATTERN.match(name):
        return False, "Invalid name. Use 1-40 chars: letters, digits, dot, dash, underscore (no spaces)."
    if name.lower() == "all" or name.lower().startswith("amr-service-"):
        return False, f"'{name}' is a reserved name."
    if not path or not os.path.isdir(path):
        return False, "Project path does not exist or is not a directory."
    if tenant_id and not tenant_root:
        return False, "Tenant project root is required."
    if tenant_id and custom_start:
        return False, "Tenant projects cannot configure custom shell start commands."

    core_path = get_core_project_path()
    target_path, resolve_err = _resolve_target_path(path, storage_mode, destination_path, core_path)
    if resolve_err:
        return False, resolve_err
    if tenant_id:
        resolved_target = os.path.realpath(os.path.abspath(os.path.normpath(target_path)))
        resolved_root = os.path.realpath(os.path.abspath(os.path.normpath(tenant_root)))
        try:
            if os.path.commonpath([resolved_target, resolved_root]) != resolved_root:
                return False, "Tenant projects must be stored within the assigned tenant project path."
        except ValueError:
            return False, "Tenant projects must be stored within the assigned tenant project path."

    deployment_profile = _normalize_deployment_profile({}, path)

    with _lock:
        projects = get_projects()
        if any(p["name"].lower() == name.lower() for p in projects):
            return False, f"A project named '{name}' already exists."

        final_path = path
        if os.path.normcase(os.path.normpath(target_path)) != os.path.normcase(os.path.normpath(path)):
            if os.path.exists(target_path) and not os.path.isdir(target_path):
                return False, "Destination project path exists and is not a directory."
            if os.path.isdir(target_path) and os.listdir(target_path):
                return False, "Destination project folder already exists and is not empty."
            try:
                _sync_project_tree(path, target_path, deployment_profile, prune=False)
                final_path = target_path
            except Exception as e:
                return False, f"Failed to deploy project files: {e}"

        entry = {
            "name": name,
            "friendly_name": friendly_name,
            "path": final_path,
            "deployment_profile": deployment_profile,
            "runtime_state": {},
        }
        if tenant_id:
            entry["tenant_id"] = tenant_id
        if custom_start:
            entry["custom_start"] = custom_start
        projects.append(entry)
        _write_projects(projects, get_core_project_path())

    return True, None


def remove_project(name):
    with _lock:
        projects = get_projects()
        for i, project in enumerate(projects):
            if project["name"].lower() == str(name).lower():
                projects.pop(i)
                _write_projects(projects, get_core_project_path())
                return True
    return False


def delete_project_from_core(name, core_project_path=None):
    with _lock:
        projects = get_projects()
        target_index = None
        target = None
        for i, project in enumerate(projects):
            if project.get("name", "").lower() == str(name or "").strip().lower():
                target_index = i
                target = project
                break

        if target is None:
            return False, "Project not found."

        core_path = _normalize_core_path(core_project_path or get_core_project_path())
        if not core_path:
            return False, "Core Project Path is not configured."

        target_path = _expand_project_path(target.get("path", ""))
        if not target_path:
            return False, "Project path is invalid."

        normalized_core = os.path.normcase(os.path.realpath(os.path.normpath(core_path)))
        normalized_target = os.path.normcase(os.path.realpath(os.path.normpath(target_path)))
        try:
            is_within_core = os.path.commonpath([normalized_target, normalized_core]) == normalized_core
        except ValueError:
            is_within_core = False
        if not is_within_core:
            return False, "Only projects stored in Core Project Path can be deleted."

        if normalized_core == normalized_target:
            return False, "Refusing to delete the Core Project Path root."

        if os.path.exists(target_path):
            if not os.path.isdir(target_path):
                return False, "Project path exists but is not a directory."
            try:
                shutil.rmtree(target_path)
            except Exception as e:
                return False, f"Failed to delete project files: {e}"

        projects.pop(target_index)
        _write_projects(projects, get_core_project_path())
        return True, None


def update_project(name, updates):
    updates = updates or {}
    new_name = str(updates.get("name", "")).strip()
    friendly_name = str(updates.get("friendly_name", "")).strip()
    path = updates.get("path")
    custom_start = updates.get("custom_start")
    deployment_profile_updates = updates.get("deployment_profile")

    with _lock:
        projects = get_projects()
        target = None
        for project in projects:
            if project["name"].lower() == str(name).lower():
                target = project
                break

        if not target:
            return False, "Project not found.", None

        if new_name and new_name.lower() != target["name"].lower():
            if not _NAME_PATTERN.match(new_name):
                return False, "Invalid name. Use 1-40 chars: letters, digits, dot, dash, underscore (no spaces).", None
            if new_name.lower() == "all" or new_name.lower().startswith("amr-service-"):
                return False, f"'{new_name}' is a reserved name.", None
            if any(project["name"].lower() == new_name.lower() and project is not target for project in projects):
                return False, f"A project named '{new_name}' already exists.", None
            target["name"] = new_name

        if friendly_name:
            target["friendly_name"] = friendly_name

        if path is not None:
            normalized_path = _expand_project_path(str(path).strip())
            if not normalized_path or not os.path.isdir(normalized_path):
                return False, "Project path does not exist or is not a directory.", None
            target["path"] = normalized_path
            target["deployment_profile"] = _normalize_deployment_profile(target.get("deployment_profile", {}), normalized_path)

        if custom_start is not None:
            custom_start_val = str(custom_start).strip()
            if custom_start_val:
                target["custom_start"] = custom_start_val
            else:
                target.pop("custom_start", None)

        if deployment_profile_updates is not None:
            merged_profile = _merge_deployment_profile(target.get("deployment_profile", {}), deployment_profile_updates)
            target["deployment_profile"] = _normalize_deployment_profile(merged_profile, target.get("path", ""))

        _write_projects(projects, get_core_project_path())
        return True, None, dict(target)


def move_project_to_core(name, destination_root=None):
    with _lock:
        projects = get_projects()
        target = None
        for project in projects:
            if project["name"].lower() == str(name).lower():
                target = project
                break

        if not target:
            return False, "Project not found.", None

        source_path = _expand_project_path(target.get("path", ""))
        if not source_path or not os.path.isdir(source_path):
            return False, "Project path does not exist on disk.", None

        core_path = destination_root or get_core_project_path()
        destination_path, err = _resolve_target_path(source_path, "core", core_path, core_path)
        if err:
            return False, err, None

        if os.path.normcase(os.path.normpath(destination_path)) == os.path.normcase(os.path.normpath(source_path)):
            return True, None, dict(target)

        if os.path.exists(destination_path) and not os.path.isdir(destination_path):
            return False, "Destination path exists and is not a directory.", None

        try:
            profile = _normalize_deployment_profile(target.get("deployment_profile", {}), source_path)
            _sync_project_tree(source_path, destination_path, profile, prune=False)
        except Exception as e:
            return False, f"Failed to deploy project to core path: {e}", None

        target["path"] = destination_path
        target["deployment_profile"] = _normalize_deployment_profile(target.get("deployment_profile", {}), destination_path)
        _write_projects(projects, get_core_project_path())
        return True, None, dict(target)


def refresh_project_deployment_profile(name):
    with _lock:
        projects = get_projects()
        target = None
        for project in projects:
            if project.get("name", "").lower() == str(name or "").strip().lower():
                target = project
                break

        if not target:
            return None

        target["deployment_profile"] = _normalize_deployment_profile(target.get("deployment_profile", {}), target.get("path", ""))
        _write_projects(projects, get_core_project_path())
        return dict(target)


def update_runtime_state(name, state_updates):
    if not isinstance(state_updates, dict):
        return False

    with _lock:
        projects = get_projects()
        target = None
        for project in projects:
            if project.get("name", "").lower() == str(name or "").strip().lower():
                target = project
                break

        if not target:
            return False

        runtime_state = target.get("runtime_state") if isinstance(target.get("runtime_state"), dict) else {}
        runtime_state.update(state_updates)
        target["runtime_state"] = runtime_state
        _write_projects(projects, get_core_project_path())
        return True


# =====================================================================
# SERVER-SIDE FOLDER NAVIGATOR
# =====================================================================
def _is_hidden(entry):
    if entry.name.startswith('.'):
        return True
    try:
        return bool(entry.stat().st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)
    except (OSError, AttributeError):
        return False


def list_folders(path=None):
    if not path:
        if os.name == "nt":
            # Avoid os.path.exists(A:\..Z:\): it can block on disconnected/mapped drives.
            try:
                import ctypes
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                roots = [
                    f"{d}:\\"
                    for i, d in enumerate(string.ascii_uppercase)
                    if (bitmask >> i) & 1
                ]
            except Exception:
                # Safe fallback if WinAPI lookup is unavailable.
                roots = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
        else:
            roots = [str(Path.home()), "/"]
        return {"path": None, "parent": None, "dirs": roots, "files": [], "error": None}

    path = _expand_project_path(path)
    parent = os.path.dirname(path)
    if parent == path:
        parent = ""  # drive root -> go back to drive list

    dirs = []
    files = []
    error = None
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if _is_hidden(entry):
                        continue
                    if entry.is_dir():
                        dirs.append(entry.path)
                    else:
                        files.append(entry.name)
                except OSError:
                    continue
        dirs.sort(key=str.lower)
        files.sort(key=str.lower)
    except (PermissionError, FileNotFoundError, OSError) as e:
        error = f"Cannot access folder: {e.__class__.__name__}"

    return {"path": path, "parent": parent, "dirs": dirs, "files": files, "error": error}
