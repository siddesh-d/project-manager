import sys
import os
import re
import json
import time
import subprocess
import threading
import tempfile
import shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, session, has_request_context
from flask_socketio import SocketIO, disconnect

from jarvis_assistant.auth import (
    add_tenant_user,
    build_session_user,
    create_tenant_registration,
    ensure_default_admin_user,
    get_tenant_by_id,
    get_tenant_core_project_path,
    get_tenant_user_store,
    get_tenant_users,
    get_user_by_id,
    load_tenant_store,
    load_user_store,
    get_user_by_username,
    normalize_role_name,
    remove_tenant_user,
    save_tenant_store,
    save_user_store,
    set_tenant_core_project_path,
    update_tenant_user,
    user_has_permission,
    user_has_scope_access,
    verify_user,
)

# IMPORT OUR CENTRALIZED SETTINGS WITH PROJECTS TO ASSURE TELEMETRY INTEGRITY
from jarvis_assistant.config import (
    SERVER_HOST,
    SERVER_PORT,
    SECRET_KEY,
    SOCKET_PATH,
    UPLOAD_MAX_CONTENT_BYTES,
    UPLOAD_MAX_FORM_MEMORY_BYTES,
    UPLOAD_MAX_FORM_PARTS,
    PM2_EXECUTABLE,
    PM2_FIELDS,
    PM2_TELEMETRY_REFRESH_SECONDS,
    FRONTEND_CONFIG,
    WEB_DEBUG,
    BASE_DIR,
    get_port_from_env,
)
from jarvis_assistant.registry import projects
from jarvis_assistant.services import pm2_manager

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / 'templates'),
    static_folder=str(BASE_DIR / 'static'),
    static_url_path='/static',
)
app.config['SECRET_KEY'] = SECRET_KEY
if UPLOAD_MAX_CONTENT_BYTES > 0:
    app.config['MAX_CONTENT_LENGTH'] = UPLOAD_MAX_CONTENT_BYTES
if UPLOAD_MAX_FORM_MEMORY_BYTES > 0:
    app.config['MAX_FORM_MEMORY_SIZE'] = UPLOAD_MAX_FORM_MEMORY_BYTES
if UPLOAD_MAX_FORM_PARTS > 0:
    app.config['MAX_FORM_PARTS'] = UPLOAD_MAX_FORM_PARTS

# Use the SOCKET_PATH from config.py
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    path=SOCKET_PATH,
    serve_client=True,
)

_ui_command_callback = None
active_log_processes = {}
_running_names_lock = threading.Lock()
_running_service_names = set()
_last_pm2_status_map = {}
_connected_socket_ids_lock = threading.Lock()
_connected_socket_ids = set()
_socket_user_map = {}


def _get_authenticated_user():
    if not hasattr(session, 'get'):
        return None
    user_id = session.get('user_id')
    if not user_id:
        return None
    from jarvis_assistant.auth import get_user_by_id
    user = get_user_by_id(user_id)
    if not user:
        return None
    return user


def _require_admin_auth():
    user = _get_authenticated_user()
    if not user:
        return None
    role = normalize_role_name(user.get('role') or 'tenant_user')
    if role != 'platform_admin':
        return None
    return user


def _require_permission(permission, tenant_id=None, project_id=None):
    user = _get_authenticated_user()
    if not user:
        return False
    if not user_has_permission(user, permission, tenant_id=tenant_id, project_id=project_id):
        return False
    return True


def _require_scope_access(tenant_id=None, project_id=None):
    user = _get_authenticated_user()
    if not user:
        return False
    return user_has_scope_access(user, tenant_id=tenant_id, project_id=project_id)


def _current_user_role():
    user = _get_authenticated_user()
    if not user:
        return 'guest'
    return normalize_role_name((user.get('role') or 'tenant_user'))


def _user_is_platform_admin(user=None):
    if user is None:
        user = _get_authenticated_user()
    if not user:
        return False
    return normalize_role_name((user.get('role') or 'tenant_user')) == 'platform_admin'


def _user_can_manage_projects(user=None):
    if user is None:
        user = _get_authenticated_user()
    if not user:
        return False
    role = normalize_role_name((user.get('role') or 'tenant_view_user'))
    if role == 'platform_admin':
        return True
    return role == 'tenant_admin' and bool(str(user.get('tenant_id') or '').strip())


def _filter_projects_for_user(projects_payload, user=None):
    if user is None:
        user = _get_authenticated_user()
    if not user:
        return []

    role = normalize_role_name((user.get('role') or 'tenant_user'))
    if role == 'platform_admin':
        return list(projects_payload or [])

    tenant_id = str(user.get('tenant_id') or '').strip()
    if not tenant_id:
        return []

    return [
        project for project in (projects_payload or [])
        if str(project.get('tenant_id') or '').strip() == tenant_id
    ]


def _get_project_for_user(project_name, user=None, require_manage=False):
    if user is None:
        user = _get_authenticated_user()
    if not user:
        return None
    if require_manage and not _user_can_manage_projects(user):
        return None

    normalized_name = str(project_name or '').strip().lower()
    if not normalized_name:
        return None
    for project in _filter_projects_for_user(projects.get_projects(), user):
        if str(project.get('name') or '').strip().lower() == normalized_name:
            if require_manage and not _user_is_platform_admin(user):
                tenant_root = get_tenant_core_project_path(str(user.get('tenant_id') or '').strip())
                if not _path_is_within_root(project.get('path'), tenant_root):
                    return None
            return project
    return None


def _path_is_within_root(path, root):
    if not path or not root:
        return False
    try:
        resolved_path = os.path.realpath(os.path.abspath(os.path.normpath(str(path))))
        resolved_root = os.path.realpath(os.path.abspath(os.path.normpath(str(root))))
        return os.path.commonpath([resolved_path, resolved_root]) == resolved_root
    except (OSError, TypeError, ValueError):
        return False


def _tenant_browse_path(user, requested_path=None):
    if _user_is_platform_admin(user):
        return str(requested_path or '').strip() or None, None

    tenant_id = str((user or {}).get('tenant_id') or '').strip()
    tenant_root = get_tenant_core_project_path(tenant_id) if tenant_id else None
    if not tenant_root:
        return None, 'Tenant core project path is not configured.'
    candidate = str(requested_path or '').strip() or tenant_root
    if not _path_is_within_root(candidate, tenant_root):
        return None, 'Access denied: folder is outside the assigned tenant project path.'
    return candidate, None


def _enforce_tenant_admin_project_constraints(user, source_path=None, storage_mode=None, destination_path=None):
    if not user:
        return {'ok': False, 'error': 'Authentication required.'}

    tenant_id = str(user.get('tenant_id') or '').strip()
    role = normalize_role_name((user.get('role') or 'tenant_user'))
    if role == 'platform_admin':
        return {'ok': True, 'storage_mode': (storage_mode or 'current').strip().lower(), 'destination_path': str(destination_path or '').strip() or None}

    if not tenant_id:
        return {'ok': False, 'error': 'Tenant users must belong to a tenant.'}

    core_path = get_tenant_core_project_path(tenant_id)
    if not core_path:
        return {'ok': False, 'error': 'Tenant core project path is not configured.'}

    normalized_storage_mode = (storage_mode or 'core').strip().lower()
    if normalized_storage_mode != 'core':
        return {'ok': False, 'error': 'Tenant users may only store projects in the assigned core project path.'}

    requested_destination = str(destination_path or '').strip()
    if requested_destination and os.path.abspath(os.path.normpath(requested_destination)) != os.path.abspath(os.path.normpath(core_path)):
        return {'ok': False, 'error': 'Tenant users cannot override the platform-assigned core project path.'}

    if source_path:
        src_abs = os.path.abspath(os.path.normpath(str(source_path).strip()))
        core_abs = os.path.abspath(os.path.normpath(core_path))
        try:
            if os.path.commonpath([src_abs, core_abs]) != core_abs:
                return {'ok': False, 'error': 'Tenant users cannot register projects outside the assigned tenant core path.'}
        except ValueError:
            return {'ok': False, 'error': 'Tenant users cannot register projects outside the assigned tenant core path.'}

    return {'ok': True, 'storage_mode': 'core', 'destination_path': core_path}


def _filter_pm2_services_for_user(services, user=None):
    if user is None:
        user = _get_authenticated_user()
    if not user:
        return []

    role = normalize_role_name((user.get('role') or 'tenant_view_user'))
    if role == 'platform_admin':
        return list(services or [])

    tenant_id = str(user.get('tenant_id') or '').strip()
    if not tenant_id:
        return []

    visible_projects = _filter_projects_for_user(projects.get_projects(), user)
    allowed_names = {
        str(project.get('name') or '').strip().lower()
        for project in visible_projects
        if str(project.get('name') or '').strip()
    }

    filtered = []
    for service in services or []:
        name = str(service.get('name') or '').strip()
        if not name:
            continue
        if name.lower() in allowed_names:
            filtered.append(service)
    return filtered


def _run_bulk_project_action_for_user(user, action, command_callback):
    if not _user_can_manage_projects(user):
        return {'ok': False, 'error': 'Permission denied.', 'results': []}
    if not callable(command_callback):
        return {'ok': False, 'error': 'Command processor is unavailable.', 'results': []}

    scoped_projects = _filter_projects_for_user(projects.get_projects(), user)
    results = []
    for project in scoped_projects:
        project_name = str(project.get('name') or '').strip()
        if not project_name:
            continue
        callback_result = _invoke_command_callback(command_callback, f'{action} {project_name}', user)
        results.append({
            'name': project_name,
            'ok': not isinstance(callback_result, dict) or bool(callback_result.get('ok', True)),
            'result': callback_result,
        })

    return {
        'ok': all(item['ok'] for item in results),
        'started': [item['name'] for item in results],
        'results': results,
    }


def _start_all_projects_for_user(user, command_callback):
    return _run_bulk_project_action_for_user(user, 'start', command_callback)


def _invoke_command_callback(command_callback, command_text, user):
    tenant_id = None if _user_is_platform_admin(user) else str((user or {}).get('tenant_id') or '').strip() or None
    return command_callback(command_text, tenant_id)


def _authorize_tenant_ui_command(user, command_text, command_callback):
    normalized = ' '.join(str(command_text or '').strip().split())
    parts = normalized.split(' ', 1)
    if len(parts) != 2:
        return {'ok': False, 'error': 'Tenant commands must target an assigned project.'}

    action = parts[0].lower()
    action = {'boot': 'start', 'remove': 'delete', 'reboot': 'restart'}.get(action, action)
    target = parts[1].strip()
    if action not in {'start', 'stop', 'restart', 'delete', 'flush', 'log'}:
        return {'ok': False, 'error': 'Command is not available to tenant users.'}

    if target.lower() in {'all', 'all services'}:
        if action == 'log':
            return {'ok': False, 'error': 'Bulk log access is not allowed.'}
        return _run_bulk_project_action_for_user(user, action, command_callback)

    project = _get_project_for_user(target, user, require_manage=True)
    if not project:
        return {'ok': False, 'error': 'Project not found or access denied.'}
    project_name = str(project.get('name') or '').strip()
    if action == 'log':
        return {'ok': True, 'log_target': project_name, 'results': []}
    if not callable(command_callback):
        return {'ok': False, 'error': 'Command processor is unavailable.'}
    callback_result = _invoke_command_callback(command_callback, f'{action} {project_name}', user)
    return {'ok': not isinstance(callback_result, dict) or bool(callback_result.get('ok', True)), 'results': [{'name': project_name, 'result': callback_result}]}


def _bind_socket_user(sid):
    user = _get_authenticated_user()
    if user:
        _socket_user_map[sid] = user
    else:
        _socket_user_map.pop(sid, None)
    return user


def _set_running_service_names(names):
    global _running_service_names
    with _running_names_lock:
        _running_service_names = set(names or [])


def _get_cached_running_service_names():
    with _running_names_lock:
        return set(_running_service_names)


def _get_running_service_names(live=False):
    if not live:
        return _get_cached_running_service_names()

    try:
        result = subprocess.run([PM2_EXECUTABLE, 'jlist'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                encoding='utf-8', errors='replace', timeout=2)
        if result.returncode != 0 or not result.stdout.strip():
            return _get_cached_running_service_names()

        processes = []
        for line in reversed(result.stdout.strip().split('\n')):
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                try:
                    processes = json.loads(line)
                    break
                except Exception:
                    continue

        running = set()
        for proc in processes:
            name = proc.get('name')
            status = proc.get('pm2_env', {}).get('status', '')
            if name and status in {'online', 'launching'}:
                running.add(name)

        _set_running_service_names(running)
        return running
    except Exception:
        return _get_cached_running_service_names()


def _human_duration_to_seconds(raw_value):
    matches = re.findall(r'(\d+)([dhms])', raw_value.lower())
    if not matches:
        return None

    total = 0
    for amount, unit in matches:
        amount = int(amount)
        if unit == 'd':
            total += amount * 86400
        elif unit == 'h':
            total += amount * 3600
        elif unit == 'm':
            total += amount * 60
        elif unit == 's':
            total += amount
    return total


def _format_pm2_uptime(value):
    if value in (None, '', 0):
        return '0s'

    if isinstance(value, str):
        raw_value = value.strip()
        if not raw_value:
            return '0s'

        lowered = raw_value.lower()
        if re.search(r'\d+[dhms]', lowered):
            total_seconds = _human_duration_to_seconds(raw_value)
            if total_seconds is not None:
                if total_seconds > (365 * 24 * 60 * 60):
                    return 'N/A'
                days, remainder = divmod(total_seconds, 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                parts = []
                if days:
                    parts.append(f"{days}d")
                if hours:
                    parts.append(f"{hours}h")
                if minutes:
                    parts.append(f"{minutes}m")
                if seconds or not parts:
                    parts.append(f"{seconds}s")
                return ' '.join(parts)
            return raw_value

        try:
            value = float(raw_value)
        except ValueError:
            return raw_value

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return str(value)

    if numeric_value <= 0:
        return '0s'

    if numeric_value > 1_000_000_000_000:
        numeric_value = max(0.0, time.time() * 1000 - numeric_value)

    if numeric_value >= 1_000_000:
        total_seconds = numeric_value / 1000.0
    else:
        total_seconds = numeric_value

    total_seconds = max(0, int(total_seconds))
    if total_seconds > (365 * 24 * 60 * 60):
        return 'N/A'

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return ' '.join(parts)


def _get_effective_core_project_path_for_user(user=None):
    user = user or _get_authenticated_user()
    if not user:
        return projects.get_core_project_path()

    role = normalize_role_name((user.get('role') or 'tenant_user'))
    if role == 'platform_admin':
        return projects.get_core_project_path()

    tenant_id = str(user.get('tenant_id') or '').strip()
    if not tenant_id:
        return ''

    tenant_path = get_tenant_core_project_path(tenant_id)
    return tenant_path or ''


def _build_pm2_service_payload(proc, port='N/A'):
    pm2_env = proc.get('pm2_env') or {}
    monit = proc.get('monit') or {}
    mem_bytes = int(monit.get('memory', 0) or 0)

    payload = {
        'name': proc.get('name', 'N/A'),
        'status': pm2_env.get('status', 'unknown'),
        'cpu': float(monit.get('cpu', 0) or 0),
        'memory': f"{int(mem_bytes / (1024 * 1024))}MB",
        'port': port,
    }

    field_map = {
        'uptime': _format_pm2_uptime(pm2_env.get('pm_uptime') or pm2_env.get('uptime') or 0),
        'restarts': int(pm2_env.get('restart_time') or pm2_env.get('restarts') or 0),
        'user': pm2_env.get('user') or proc.get('user') or 'N/A',
        'watching': bool(pm2_env.get('watch') or pm2_env.get('watching') or False),
        'pid': proc.get('pid') or pm2_env.get('pid') or 'N/A',
        'namespace': pm2_env.get('namespace') or proc.get('namespace') or 'default',
        'mode': pm2_env.get('mode') or proc.get('mode') or 'fork',
        'version': pm2_env.get('version') or proc.get('version') or 'N/A',
    }

    for field_name, enabled in PM2_FIELDS.items():
        if field_name in {'name', 'status', 'cpu', 'memory', 'port'}:
            continue
        if not enabled:
            continue
        value = field_map.get(field_name)
        if value is None or value == '':
            continue
        payload[field_name] = value

    return payload


def _emit_projects_list():
    running_names = _get_cached_running_service_names()
    running_names_lower = {name.lower() for name in running_names}
    user = _get_authenticated_user()
    core_path = _get_effective_core_project_path_for_user(user)
    all_projects = []
    for proj in projects.get_projects():
        entry = dict(proj)
        entry['is_running'] = proj.get('name', '').lower() in running_names_lower
        entry['is_in_core_path'] = projects.is_path_within_core(proj.get('path', ''))
        entry['core_project_path'] = core_path
        all_projects.append(entry)

    visible_projects = _filter_projects_for_user(all_projects, user)
    room = getattr(request, 'sid', None) if has_request_context() else None
    socketio.emit('projects_list', visible_projects, room=room)

def _emit_to_request(event, payload):
    room = getattr(request, 'sid', None) if has_request_context() else None
    socketio.emit(event, payload, room=room)


def stream_log_to_ui(source, message, color="text-zinc-300", tenant_id=None, room=None):
    """Prints logs cleanly to CMD and streams them to the UI over WebSockets."""
    print(f"[{source}] {message}")
    sys.stdout.flush()
    payload = {'source': source, 'message': message, 'color': color}
    if room is None and has_request_context():
        room = getattr(request, 'sid', None)
    if room:
        socketio.emit('log_stream', payload, room=room)
        return

    for sid, user in list(_socket_user_map.items()):
        role = normalize_role_name((user or {}).get('role') or 'tenant_view_user')
        user_tenant_id = str((user or {}).get('tenant_id') or '').strip()
        if role == 'platform_admin' or (tenant_id and user_tenant_id == str(tenant_id).strip()):
            socketio.emit('log_stream', payload, room=sid)

@app.before_request
def enforce_authentication():
    if request.path.startswith('/static/'):
        return None
    if request.path in {'/', '/api/login', '/api/session', '/api/logout'}:
        return None

    user = _get_authenticated_user()
    if not user:
        if request.path.startswith('/api/'):
            return jsonify({'ok': False, 'error': 'Authentication required.'}), 401
        if request.path.startswith('/socket.io'):
            return jsonify({'ok': False, 'error': 'Authentication required.'}), 401
        return None

    if request.path.startswith('/api/') and request.path not in {'/api/login', '/api/session', '/api/logout'}:
        if not _require_scope_access() and not _require_admin_auth():
            return jsonify({'ok': False, 'error': 'Access denied.'}), 403

    return None


@app.route('/')
def index():
    user = _get_authenticated_user()
    if not user:
        return render_template('login.html', app_config=FRONTEND_CONFIG)
    return render_template('index.html', app_config=FRONTEND_CONFIG)


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '')

    if not username or not password:
        return jsonify({'ok': False, 'error': 'Username and password are required.'}), 401

    user = get_user_by_username(username)
    if not user or not verify_user(username, password):
        return jsonify({'ok': False, 'error': 'Invalid username or password.'}), 401

    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    return jsonify({'ok': True, 'user': build_session_user(user)})


@app.route('/api/logout', methods=['POST'])
def logout():
    user_id = str(session.get('user_id') or '').strip()
    session.clear()
    if user_id:
        for sid, mapped_user in list(_socket_user_map.items()):
            if str((mapped_user or {}).get('id') or '').strip() == user_id:
                _socket_user_map.pop(sid, None)
                for key, proc in list(active_log_processes.items()):
                    if isinstance(key, tuple) and key[0] == sid:
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                        active_log_processes.pop(key, None)
    return jsonify({'ok': True})


@app.route('/api/session', methods=['GET'])
def check_session():
    user = _get_authenticated_user()
    if not user:
        return jsonify({'authenticated': False}), 401
    return jsonify({'authenticated': True, 'user': build_session_user(user)})


@app.route('/api/tenants', methods=['GET'])
def list_tenants():
    if not _require_admin_auth():
        return jsonify({'ok': False, 'error': 'Platform admin access required.'}), 403

    tenant_store = load_tenant_store().get('tenants', [])
    enriched = []
    for tenant in tenant_store:
        tenant_id = str(tenant.get('id') or '').strip()
        users = get_tenant_users(tenant_id)
        entry = dict(tenant)
        entry['users'] = users
        entry['user_count'] = len(users)
        entry['core_project_path'] = get_tenant_core_project_path(tenant_id) or entry.get('core_project_path')
        enriched.append(entry)
    return jsonify({'ok': True, 'tenants': enriched})


@app.route('/api/tenants/<tenant_id>', methods=['GET'])
def get_tenant_detail(tenant_id):
    if not _require_admin_auth():
        return jsonify({'ok': False, 'error': 'Platform admin access required.'}), 403

    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'ok': False, 'error': 'Tenant not found.'}), 404

    tenant_users = get_tenant_users(tenant_id)
    tenant['users'] = tenant_users
    tenant['user_count'] = len(tenant_users)
    tenant['core_project_path'] = get_tenant_core_project_path(tenant_id) or tenant.get('core_project_path')
    return jsonify({'ok': True, 'tenant': tenant})


@app.route('/api/tenants/<tenant_id>', methods=['PUT'])
def update_tenant(tenant_id):
    if not _require_admin_auth():
        return jsonify({'ok': False, 'error': 'Platform admin access required.'}), 403

    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'ok': False, 'error': 'Tenant not found.'}), 404

    payload = request.get_json(silent=True) or {}
    store = load_tenant_store()
    updated = False
    for item in store.get('tenants', []):
        if str(item.get('id') or '').strip() != str(tenant_id).strip():
            continue
        if 'name' in payload and str(payload.get('name') or '').strip():
            item['name'] = str(payload.get('name')).strip()
            updated = True
        if 'status' in payload:
            item['status'] = str(payload.get('status') or 'active').strip() or 'active'
            updated = True
        if 'core_project_path' in payload and str(payload.get('core_project_path') or '').strip():
            try:
                item['core_project_path'] = set_tenant_core_project_path(tenant_id, payload.get('core_project_path'), actor=_get_authenticated_user())
                updated = True
            except (PermissionError, ValueError) as exc:
                return jsonify({'ok': False, 'error': str(exc)}), 403 if isinstance(exc, PermissionError) else 400
        break
    else:
        return jsonify({'ok': False, 'error': 'Tenant not found.'}), 404

    if updated:
        save_tenant_store(store)
    tenant = get_tenant_by_id(tenant_id)
    tenant['users'] = get_tenant_users(tenant_id)
    tenant['user_count'] = len(tenant['users'])
    tenant['core_project_path'] = get_tenant_core_project_path(tenant_id) or tenant.get('core_project_path')
    return jsonify({'ok': True, 'tenant': tenant})


@app.route('/api/tenants/<tenant_id>', methods=['DELETE'])
def delete_tenant(tenant_id):
    if not _require_admin_auth():
        return jsonify({'ok': False, 'error': 'Platform admin access required.'}), 403

    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        return jsonify({'ok': False, 'error': 'Tenant id is required.'}), 400

    tenant_store = load_tenant_store()
    tenant_list = tenant_store.get('tenants', [])
    remaining_tenants = []
    removed = None
    for item in tenant_list:
        if str(item.get('id') or '').strip() == tenant_id:
            removed = dict(item)
            continue
        remaining_tenants.append(item)
    if removed is None:
        return jsonify({'ok': False, 'error': 'Tenant not found.'}), 404

    tenant_store['tenants'] = remaining_tenants
    save_tenant_store(tenant_store)

    user_store = load_user_store()
    user_store['users'] = [
        user for user in user_store.get('users', [])
        if not isinstance(user, dict) or str(user.get('tenant_id') or '').strip() != tenant_id
    ]
    save_user_store(user_store)

    return jsonify({'ok': True, 'tenant': removed})


@app.route('/api/tenants/<tenant_id>/users', methods=['GET'])
def list_tenant_users(tenant_id):
    user = _get_authenticated_user()
    if not user:
        return jsonify({'ok': False, 'error': 'Authentication required.'}), 401

    role = normalize_role_name((user.get('role') or 'tenant_user'))
    tenant_matches = str(user.get('tenant_id') or '').strip() == str(tenant_id or '').strip()
    if role != 'platform_admin' and not tenant_matches:
        return jsonify({'ok': False, 'error': 'Access denied.'}), 403

    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'ok': False, 'error': 'Tenant not found.'}), 404
    return jsonify({'ok': True, 'users': get_tenant_users(tenant_id)})


@app.route('/api/tenants/<tenant_id>/users', methods=['POST'])
def create_tenant_user(tenant_id):
    user = _get_authenticated_user()
    if not user:
        return jsonify({'ok': False, 'error': 'Authentication required.'}), 401

    role = normalize_role_name((user.get('role') or 'tenant_user'))
    if role not in {'platform_admin', 'tenant_admin'}:
        return jsonify({'ok': False, 'error': 'Tenant user management access required.'}), 403
    if role == 'tenant_admin' and str(user.get('tenant_id') or '').strip() != str(tenant_id or '').strip():
        return jsonify({'ok': False, 'error': 'Tenant User Admins can only manage users within their own tenant.'}), 403

    payload = request.get_json(silent=True) or {}
    username = str(payload.get('username') or '').strip()
    password = str(payload.get('password') or '').strip()
    role_name = str(payload.get('role') or 'tenant_view_user').strip()
    try:
        user = add_tenant_user(tenant_id, username, password, role=role_name, actor=user)
    except PermissionError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'user': user})


@app.route('/api/tenants/<tenant_id>/users/<user_id>', methods=['PUT'])
def update_tenant_user_route(tenant_id, user_id):
    user = _get_authenticated_user()
    if not user:
        return jsonify({'ok': False, 'error': 'Authentication required.'}), 401

    role = normalize_role_name((user.get('role') or 'tenant_user'))
    if role not in {'platform_admin', 'tenant_admin'}:
        return jsonify({'ok': False, 'error': 'Tenant user management access required.'}), 403
    if role == 'tenant_admin' and str(user.get('tenant_id') or '').strip() != str(tenant_id or '').strip():
        return jsonify({'ok': False, 'error': 'Tenant User Admins can only manage users within their own tenant.'}), 403

    payload = request.get_json(silent=True) or {}
    try:
        user = update_tenant_user(
            tenant_id,
            user_id,
            username=payload.get('username'),
            password=payload.get('password'),
            role=payload.get('role'),
            actor=user,
        )
    except PermissionError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'user': user})


@app.route('/api/tenants/<tenant_id>/users/<user_id>', methods=['DELETE'])
def delete_tenant_user_route(tenant_id, user_id):
    user = _get_authenticated_user()
    if not user:
        return jsonify({'ok': False, 'error': 'Authentication required.'}), 401

    role = normalize_role_name((user.get('role') or 'tenant_user'))
    if role not in {'platform_admin', 'tenant_admin'}:
        return jsonify({'ok': False, 'error': 'Tenant user management access required.'}), 403
    if role == 'tenant_admin' and str(user.get('tenant_id') or '').strip() != str(tenant_id or '').strip():
        return jsonify({'ok': False, 'error': 'Tenant User Admins can only manage users within their own tenant.'}), 403

    try:
        removed = remove_tenant_user(tenant_id, user_id, actor=user)
    except PermissionError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'user': removed})


@app.route('/api/tenants/<tenant_id>/core-path', methods=['PUT'])
def set_tenant_core_path_route(tenant_id):
    if not _require_admin_auth():
        return jsonify({'ok': False, 'error': 'Platform admin access required.'}), 403

    payload = request.get_json(silent=True) or {}
    path = str(payload.get('core_project_path') or '').strip()
    try:
        updated_path = set_tenant_core_project_path(tenant_id, path, actor=_get_authenticated_user())
    except PermissionError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'core_project_path': updated_path})


@app.route('/api/tenants/register', methods=['POST'])
def register_tenant():
    if not _require_admin_auth():
        return jsonify({'ok': False, 'error': 'Platform admin access required.'}), 403

    payload = request.get_json(silent=True) or {}
    tenant_name = str(payload.get('tenant_name') or '').strip()
    admin_username = str(payload.get('admin_username') or '').strip()
    admin_password = str(payload.get('admin_password') or '').strip()
    core_project_path = str(payload.get('core_project_path') or '').strip()

    if not tenant_name or not admin_username or not admin_password:
        return jsonify({'ok': False, 'error': 'Tenant name, initial admin username, and password are required.'}), 400

    actor = _get_authenticated_user()
    try:
        result = create_tenant_registration(
            tenant_name=tenant_name,
            admin_username=admin_username,
            admin_password=admin_password,
            created_by=actor.get('id') if actor else 'platform_admin',
            actor=actor,
            core_project_path=core_project_path or None,
        )
    except PermissionError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 403
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

    return jsonify({'ok': True, 'tenant': result})


def _safe_upload_destination(base_dir, relative_path):
    parts = [p for p in str(relative_path).replace('\\', '/').split('/') if p not in ('', '.', '..')]
    dest = os.path.normpath(os.path.join(base_dir, *parts))
    base_abs = os.path.abspath(base_dir)
    dest_abs = os.path.abspath(dest)
    if os.path.commonpath([base_abs, dest_abs]) != base_abs:
        raise ValueError('Invalid upload file path.')
    return dest_abs


@app.route('/api/upload_project', methods=['POST'])
def upload_project_from_device():
    user = _get_authenticated_user()
    if not user:
        return jsonify({'ok': False, 'error': 'Authentication required.'}), 401
    if not _user_can_manage_projects(user):
        return jsonify({'ok': False, 'error': 'Project management permission required.'}), 403

    name = (request.form.get('name') or '').strip()
    friendly_name = (request.form.get('friendly_name') or '').strip() or name
    custom_start = (request.form.get('custom_start') or '').strip() or None
    storage_mode = (request.form.get('storage_mode') or 'core').strip().lower()
    destination_path = (request.form.get('destination_path') or '').strip() or None

    role = normalize_role_name((user.get('role') or 'tenant_user'))
    if role != 'platform_admin':
        enforced = _enforce_tenant_admin_project_constraints(user, storage_mode=storage_mode, destination_path=destination_path)
        if not enforced['ok']:
            return jsonify({'ok': False, 'error': enforced['error']}), 403
        storage_mode = 'core'
        destination_path = enforced['destination_path']
        custom_start = None
    elif storage_mode not in {'core', 'custom'}:
        return jsonify({'ok': False, 'error': 'Upload mode supports only Core Path or Custom Path destinations.'}), 400

    upload_files = request.files.getlist('project_files')
    relative_paths_raw = request.form.get('relative_paths')

    if not upload_files:
        return jsonify({'ok': False, 'error': 'No uploaded files provided.'}), 400

    if relative_paths_raw:
        try:
            relative_paths = json.loads(relative_paths_raw)
            if not isinstance(relative_paths, list):
                raise ValueError('Invalid relative paths payload')
        except Exception:
            return jsonify({'ok': False, 'error': 'Invalid upload metadata.'}), 400
    else:
        # Prefer per-file relative paths from multipart filenames when provided by the browser.
        relative_paths = [str((file_obj.filename or '')).strip() for file_obj in upload_files]

    if len(relative_paths) != len(upload_files):
        return jsonify({'ok': False, 'error': 'Upload metadata does not match file count.'}), 400

    temp_root = tempfile.mkdtemp(prefix='jarvis_upload_')
    source_root = None

    try:
        top_level_candidates = []

        for file_obj, rel in zip(upload_files, relative_paths):
            rel_str = str(rel or '').strip()
            if not rel_str:
                continue

            rel_parts = [p for p in rel_str.replace('\\', '/').split('/') if p]
            if rel_parts:
                top_level_candidates.append(rel_parts[0])

            target_file = _safe_upload_destination(temp_root, rel_str)
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            file_obj.save(target_file)

        if not top_level_candidates:
            return jsonify({'ok': False, 'error': 'Uploaded folder appears empty.'}), 400

        root_name = top_level_candidates[0]
        if any(candidate != root_name for candidate in top_level_candidates):
            # Keep deterministic behavior by wrapping mixed roots into one folder
            root_name = name or 'uploaded-project'
            wrapped_root = os.path.join(temp_root, root_name)
            os.makedirs(wrapped_root, exist_ok=True)
            for entry in os.listdir(temp_root):
                if entry == root_name:
                    continue
                shutil.move(os.path.join(temp_root, entry), os.path.join(wrapped_root, entry))
            source_root = wrapped_root
        else:
            source_root = os.path.join(temp_root, root_name)

        if not os.path.isdir(source_root):
            return jsonify({'ok': False, 'error': 'Uploaded project folder is invalid.'}), 400

        ok, err = projects.add_project(
            name=name,
            friendly_name=friendly_name,
            path=source_root,
            custom_start=custom_start,
            storage_mode=storage_mode,
            destination_path=destination_path,
            tenant_id=user.get('tenant_id'),
            tenant_root=destination_path if role != 'platform_admin' else None,
        )

        if not ok:
            return jsonify({'ok': False, 'error': err or 'Project registration failed.'}), 400

        stream_log_to_ui("PROJECTS", f"Project '{name}' uploaded and registered successfully.", "text-emerald-400")
        _emit_projects_list()
        return jsonify({'ok': True})

    except Exception as e:
        return jsonify({'ok': False, 'error': f'Upload failed: {e}'}), 500
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

@socketio.on('connect')
def handle_client_connection():
    user = _get_authenticated_user()
    if not user:
        disconnect()
        return

    session_tenant = str((user.get('tenant_id') or '')).strip() or None
    user_role = normalize_role_name(user.get('role') or 'tenant_view_user')
    if user_role != 'platform_admin' and not session_tenant:
        disconnect()
        return

    sid = getattr(request, "sid", None)
    if sid:
        with _connected_socket_ids_lock:
            if sid in _connected_socket_ids:
                return
            _connected_socket_ids.add(sid)
    auth_user = _bind_socket_user(sid)
    if auth_user:
        stream_log_to_ui("SYSTEM", f"Authenticated {auth_user.get('role')} session attached: {auth_user.get('username')}", "text-emerald-400")
    else:
        stream_log_to_ui("SYSTEM", "Interface attachment successful. Dual-terminal mode active.", "text-emerald-400")


@socketio.on('disconnect')
def handle_client_disconnect(reason=None):
    sid = getattr(request, "sid", None)
    if sid:
        with _connected_socket_ids_lock:
            _connected_socket_ids.discard(sid)
        _socket_user_map.pop(sid, None)
        for key, proc in list(active_log_processes.items()):
            if isinstance(key, tuple) and key[0] == sid:
                try:
                    proc.terminate()
                except Exception:
                    pass
                active_log_processes.pop(key, None)

    disconnect_reason = str(reason or "client_disconnect")
    # Normal client navigation/reload disconnects are expected in browser sessions.
    if disconnect_reason not in {"client disconnect", "client_disconnect", "transport close"}:
        stream_log_to_ui("SYSTEM", f"Client disconnected: {disconnect_reason}", "text-amber-400")

@socketio.on('ui_command')
def handle_incoming_ui_command(data):
    """Processes commands typed directly into the Web UI input box."""
    user = _get_authenticated_user()
    if not user:
        return {'ok': False, 'error': 'Authentication required.'}

    role = normalize_role_name((user.get('role') or 'tenant_view_user'))
    if role in {'tenant_view_user'}:
        return {'ok': False, 'error': 'Permission denied.'}
    if not _require_permission('manage_platform_settings') and not _require_permission('configure_tenant_settings'):
        return {'ok': False, 'error': 'Permission denied.'}

    command_text = (data or {}).get('command', '')

    if role == 'tenant_admin':
        command_result = _authorize_tenant_ui_command(user, command_text, _ui_command_callback)
        if command_result.get('log_target'):
            _emit_to_request('log_stream_intent', {'service': command_result['log_target']})
        for item in command_result.get('results', []):
            callback_result = item.get('result')
            if isinstance(callback_result, dict) and callback_result.get('type') == 'start_result':
                _emit_to_request('project_start_result', {
                    'target': callback_result.get('target', item.get('name', '')),
                    'ok': bool(callback_result.get('ok')),
                    'message': callback_result.get('message', ''),
                })
        stream_log_to_ui(
            "UI-OVERRIDE",
            f"Tenant-scoped command {'executed' if command_result.get('ok') else 'denied'}.",
            "text-amber-400",
        )
        return command_result

    callback_result = None
    if _ui_command_callback:
        callback_result = _ui_command_callback(command_text)

    if command_text.startswith('sys_setting:'):
        if isinstance(callback_result, dict) and callback_result.get('type') == 'sys_setting' and callback_result.get('changed'):
            stream_log_to_ui("SETTINGS", f"Applied setting: {callback_result.get('key')}", "text-cyan-500")
        return

    if isinstance(callback_result, dict) and callback_result.get('type') == 'start_result':
        _emit_to_request('project_start_result', {
            'target': callback_result.get('target', ''),
            'ok': bool(callback_result.get('ok')),
            'message': callback_result.get('message', ''),
        })
        return

    stream_log_to_ui("UI-OVERRIDE", f"Executing text input: {command_text}", "text-amber-400")

# =====================================================================
# PROJECT REGISTRY MANAGEMENT (JSON-BACKED)
# =====================================================================
@socketio.on('get_projects')
def handle_get_projects():
    _emit_projects_list()
    _emit_to_request('project_preferences', {
        'core_project_path': _get_effective_core_project_path_for_user(_get_authenticated_user())
    })


@socketio.on('get_project_preferences')
def handle_get_project_preferences():
    _emit_to_request('project_preferences', {
        'core_project_path': _get_effective_core_project_path_for_user(_get_authenticated_user())
    })


@socketio.on('set_core_project_path')
def handle_set_core_project_path(data):
    user = _get_authenticated_user()
    if not _user_is_platform_admin(user):
        _emit_to_request('project_op_result', {'action': 'set_core_path', 'ok': False, 'error': 'Platform admin access required.'})
        return

    path = (data or {}).get('path', '')
    ok, err = projects.set_core_project_path(path)
    _emit_to_request('project_op_result', {'action': 'set_core_path', 'ok': ok, 'error': err})
    if ok:
        stream_log_to_ui("PROJECTS", f"Core Project Path set to: {projects.get_core_project_path()}", "text-emerald-400")
        _emit_to_request('project_preferences', {'core_project_path': projects.get_core_project_path()})
        _emit_projects_list()

@socketio.on('add_project')
def handle_add_project(data):
    user = _get_authenticated_user()
    if not _user_can_manage_projects(user):
        _emit_to_request('project_op_result', {'action': 'add', 'ok': False, 'error': 'Permission denied.'})
        return

    payload = data or {}
    storage_mode = payload.get('storage_mode', 'current')
    destination_path = payload.get('destination_path')
    source_path = payload.get('path')

    if normalize_role_name((user.get('role') or 'tenant_user')) != 'platform_admin':
        enforced = _enforce_tenant_admin_project_constraints(user, source_path=source_path, storage_mode=storage_mode, destination_path=destination_path)
        if not enforced['ok']:
            _emit_to_request('project_op_result', {'action': 'add', 'ok': False, 'error': enforced['error']})
            return
        storage_mode = 'core'
        destination_path = enforced['destination_path']
        payload['custom_start'] = None

    ok, err = projects.add_project(
        payload.get('name'),
        payload.get('friendly_name'),
        source_path,
        payload.get('custom_start'),
        storage_mode,
        destination_path,
        tenant_id=user.get('tenant_id') if user else None,
        tenant_root=destination_path if not _user_is_platform_admin(user) else None,
    )
    _emit_to_request('project_op_result', {'action': 'add', 'ok': ok, 'error': err})
    if ok:
        stream_log_to_ui("PROJECTS", f"Project '{payload.get('name')}' registered successfully.", "text-emerald-400")
        _emit_projects_list()


@socketio.on('update_project')
def handle_update_project(data):
    user = _get_authenticated_user()
    if not _user_can_manage_projects(user):
        _emit_to_request('project_op_result', {'action': 'update', 'ok': False, 'error': 'Permission denied.'})
        return

    data = data or {}
    name = data.get('name', '')
    current_project = _get_project_for_user(name, user, require_manage=True)
    if not current_project:
        _emit_to_request('project_op_result', {'action': 'update', 'ok': False, 'error': 'Project not found or access denied.'})
        return

    updates = {
        'name': data.get('new_name'),
        'friendly_name': data.get('friendly_name'),
        'path': data.get('path'),
        'custom_start': data.get('custom_start'),
    }

    if not _user_is_platform_admin(user):
        if updates.get('custom_start') is not None and str(updates.get('custom_start') or '').strip() != str(current_project.get('custom_start') or '').strip():
            _emit_to_request('project_op_result', {'action': 'update', 'ok': False, 'error': 'Tenant users cannot configure custom shell start commands.'})
            return
        updates['custom_start'] = current_project.get('custom_start')

    running_names = _get_running_service_names(live=True)
    running_names_lower = {n.lower() for n in running_names}
    is_running = str(name).lower() in running_names_lower

    if not _user_is_platform_admin(user) and updates.get('path') is not None:
        tenant_root = get_tenant_core_project_path(str(user.get('tenant_id') or '').strip())
        requested_path = str(updates.get('path') or current_project.get('path') or '').strip()
        if not _path_is_within_root(requested_path, tenant_root):
            _emit_to_request('project_op_result', {'action': 'update', 'ok': False, 'error': 'Project path must remain inside the assigned tenant project path.'})
            return

    dangerous_change = False
    if current_project:
        incoming_name = (updates.get('name') or '').strip()
        if incoming_name and incoming_name.lower() != current_project.get('name', '').lower():
            dangerous_change = True

        if updates.get('path') is not None:
            incoming_path = str(updates.get('path') or '').strip()
            current_path = str(current_project.get('path') or '').strip()
            if incoming_path and os.path.normcase(os.path.normpath(incoming_path)) != os.path.normcase(os.path.normpath(current_path)):
                dangerous_change = True

        if updates.get('custom_start') is not None:
            incoming_custom = str(updates.get('custom_start') or '').strip()
            current_custom = str(current_project.get('custom_start') or '').strip()
            if incoming_custom != current_custom:
                dangerous_change = True

    if is_running and dangerous_change:
        _emit_to_request('project_op_result', {
            'action': 'update',
            'ok': False,
            'error': 'Stop the running PM2 service before editing name/path/start command.'
        })
        return

    ok, err, _ = projects.update_project(name, updates)
    _emit_to_request('project_op_result', {'action': 'update', 'ok': ok, 'error': err})
    if ok:
        stream_log_to_ui("PROJECTS", f"Project '{name}' updated.", "text-emerald-400")
        _emit_projects_list()


@socketio.on('move_project_to_core')
def handle_move_project_to_core(data):
    user = _get_authenticated_user()
    if not _user_can_manage_projects(user):
        _emit_to_request('project_op_result', {'action': 'move_core', 'ok': False, 'error': 'Permission denied.'})
        return

    name = (data or {}).get('name', '')
    if not _get_project_for_user(name, user, require_manage=True):
        _emit_to_request('project_op_result', {'action': 'move_core', 'ok': False, 'error': 'Project not found or access denied.'})
        return
    running_names = _get_running_service_names(live=True)
    if str(name).lower() in {n.lower() for n in running_names}:
        _emit_to_request('project_op_result', {
            'action': 'move_core',
            'ok': False,
            'error': 'Stop the PM2 service before moving the project.'
        })
        return

    tenant_destination = None if _user_is_platform_admin(user) else get_tenant_core_project_path(user.get('tenant_id'))
    ok, err, _ = projects.move_project_to_core(name, destination_root=tenant_destination)
    _emit_to_request('project_op_result', {'action': 'move_core', 'ok': ok, 'error': err})
    if ok:
        stream_log_to_ui("PROJECTS", f"Project '{name}' moved to Core Project Path.", "text-emerald-400")
        _emit_projects_list()

@socketio.on('remove_project')
def handle_remove_project(data):
    user = _get_authenticated_user()
    if not _user_can_manage_projects(user):
        _emit_to_request('project_op_result', {'action': 'remove', 'ok': False, 'error': 'Permission denied.'})
        return

    name = (data or {}).get('name', '')
    if not _get_project_for_user(name, user, require_manage=True):
        _emit_to_request('project_op_result', {'action': 'remove', 'ok': False, 'error': 'Project not found or access denied.'})
        return
    ok = projects.remove_project(name)
    if ok:
        subprocess.run([PM2_EXECUTABLE, 'delete', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stream_log_to_ui("PROJECTS", f"Project '{name}' removed from registry.", "text-amber-400")
    _emit_to_request('project_op_result', {'action': 'remove', 'ok': ok, 'error': None if ok else f"Project '{name}' not found."})
    _emit_projects_list()


@socketio.on('delete_project_from_core')
def handle_delete_project_from_core(data):
    user = _get_authenticated_user()
    if not _user_can_manage_projects(user):
        _emit_to_request('project_op_result', {'action': 'delete_core', 'ok': False, 'error': 'Permission denied.'})
        return

    name = (data or {}).get('name', '')
    if not _get_project_for_user(name, user, require_manage=True):
        _emit_to_request('project_op_result', {'action': 'delete_core', 'ok': False, 'error': 'Project not found or access denied.'})
        return
    running_names = _get_running_service_names(live=True)
    if str(name).lower() in {n.lower() for n in running_names}:
        _emit_to_request('project_op_result', {
            'action': 'delete_core',
            'ok': False,
            'error': 'Stop the PM2 service before deleting project files from Core Project Path.'
        })
        _emit_projects_list()
        return

    tenant_root = None if _user_is_platform_admin(user) else get_tenant_core_project_path(user.get('tenant_id'))
    ok, err = projects.delete_project_from_core(name, core_project_path=tenant_root)
    if ok:
        subprocess.run([PM2_EXECUTABLE, 'delete', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stream_log_to_ui("PROJECTS", f"Project '{name}' deleted from Core Project Path and registry.", "text-amber-400")

    _emit_to_request('project_op_result', {
        'action': 'delete_core',
        'ok': ok,
        'error': err,
    })
    _emit_projects_list()

@socketio.on('browse_folders')
def handle_browse_folders(data):
    user = _get_authenticated_user()
    if not user:
        _emit_to_request('folder_listing', {'path': None, 'parent': None, 'dirs': [], 'files': [], 'error': 'Authentication required.'})
        return
    browse_path, error = _tenant_browse_path(user, (data or {}).get('path'))
    if error:
        _emit_to_request('folder_listing', {'path': None, 'parent': None, 'dirs': [], 'files': [], 'error': error})
        return
    listing = projects.list_folders(browse_path)
    if not _user_is_platform_admin(user):
        tenant_root = get_tenant_core_project_path(user.get('tenant_id'))
        listing['dirs'] = [path for path in listing.get('dirs', []) if _path_is_within_root(path, tenant_root)]
        if not _path_is_within_root(listing.get('parent'), tenant_root):
            listing['parent'] = None
    _emit_to_request('folder_listing', listing)

# =====================================================================
# APPLICATION SHUTDOWN
# =====================================================================
@socketio.on('shutdown_app')
def handle_shutdown_app():
    user = _get_authenticated_user()
    if not _user_is_platform_admin(user):
        _emit_to_request('system_event', {'ok': False, 'error': 'Platform admin access required.'})
        return

    stream_log_to_ui("SYSTEM", "Shutdown directive confirmed. Terminating core application...", "text-red-500 font-bold")

    def _shutdown():
        time.sleep(0.8)  # let the final log message flush to connected clients
        for name, proc in list(active_log_processes.items()):
            try:
                proc.terminate()
            except Exception:
                pass
        active_log_processes.clear()
        print("[SYSTEM] Shutdown complete. Exiting.")
        sys.stdout.flush()
        # os._exit ends the whole process even with live daemon threads and no attached terminal
        os._exit(0)

    threading.Thread(target=_shutdown, daemon=True).start()

# =====================================================================
# LIVE PM2 LOG STREAMING PIPELINE
# =====================================================================
@socketio.on('toggle_service_logs')
def handle_toggle_logs(data):
    user = _get_authenticated_user()
    service_name = str((data or {}).get('service') or '').strip()
    action = (data or {}).get('action')
    sid = getattr(request, 'sid', None)
    process_key = (sid, service_name)

    if not user or not _get_project_for_user(service_name, user):
        _emit_to_request('service_log_error', {'service': service_name, 'error': 'Project not found or access denied.'})
        return {'ok': False, 'error': 'Project not found or access denied.'}
    
    if action == 'stop':
        if process_key in active_log_processes:
            active_log_processes[process_key].terminate()
            del active_log_processes[process_key]
            stream_log_to_ui("LOG-MGR", f"Halted live telemetry pipe for {service_name}", "text-amber-400")
        return {'ok': True}
        
    if action == 'start':
        if process_key in active_log_processes:
            active_log_processes[process_key].terminate()
            
        stream_log_to_ui("LOG-MGR", f"Establishing dedicated log pipe for {service_name}...", "text-emerald-400")
        
        try:
            proc = subprocess.Popen(
                [PM2_EXECUTABLE, 'logs', service_name, '--raw', '--lines', '50'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            active_log_processes[process_key] = proc
            
            def stream_reader(p, name, target_sid, key, expected_user_id):
                for line in iter(p.stdout.readline, ''):
                    if not line: break
                    mapped_user = _socket_user_map.get(target_sid)
                    mapped_user_id = str((mapped_user or {}).get('id') or '').strip()
                    current_user = get_user_by_id(mapped_user_id) if mapped_user_id else None
                    current_role = normalize_role_name((current_user or {}).get('role') or 'tenant_view_user')
                    current_tenant_id = str((current_user or {}).get('tenant_id') or '').strip()
                    tenant_is_valid = current_role == 'platform_admin' or (current_tenant_id and get_tenant_by_id(current_tenant_id))
                    if mapped_user_id != expected_user_id or not current_user or not tenant_is_valid or not _get_project_for_user(name, current_user):
                        try:
                            p.terminate()
                        except Exception:
                            pass
                        break
                    socketio.emit('service_log_chunk', {'service': name, 'log': line.strip()}, room=target_sid)
                p.stdout.close()
                if key in active_log_processes and active_log_processes[key] == p:
                    del active_log_processes[key]
            
            expected_user_id = str(user.get('id') or '').strip()
            t = threading.Thread(target=stream_reader, args=(proc, service_name, sid, process_key, expected_user_id), daemon=True)
            t.start()
            return {'ok': True}
        except Exception as e:
            stream_log_to_ui("LOG-ERR", f"Failed to open pipe: {str(e)}", "text-red-500")
            return {'ok': False, 'error': 'Failed to open log stream.'}

    return {'ok': False, 'error': 'Invalid log action.'}

# =====================================================================
# LIVE UI TELEMETRY HEARTBEAT (FIXED FOR BALANCING SERVICE VISIBILITY)
# =====================================================================
def pm2_telemetry_loop():
    global _last_pm2_status_map
    while True:
        try:
            result = subprocess.run([PM2_EXECUTABLE, 'jlist'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    encoding='utf-8', errors='replace')

            payload = []
            processes = []
            parsed_live_snapshot = False
            if result.returncode == 0 and result.stdout.strip():
                # Scan lines in reverse to find the JSON payload, ignoring PM2 update nags
                for line in reversed(result.stdout.strip().split('\n')):
                    line = line.strip()
                    if line.startswith('[') and line.endswith(']'):
                        try:
                            processes = json.loads(line)
                            parsed_live_snapshot = True
                            break
                        except Exception:
                            continue
                
            # Create a rapid lookup map of current active processes in PM2
            if parsed_live_snapshot:
                pm2_status_map = {p.get("name"): p for p in processes if p.get("name")}
                _last_pm2_status_map = dict(pm2_status_map)
                running_now = {
                    p.get("name") for p in processes
                    if p.get("name") and p.get('pm2_env', {}).get('status') in {'online', 'launching'}
                }
                _set_running_service_names(running_now)
            else:
                pm2_status_map = dict(_last_pm2_status_map)

            pm2_status_map_ci = {
                str(name).strip().lower(): proc
                for name, proc in pm2_status_map.items()
                if name
            }

            project_list = projects.get_projects()
            project_names = [proj.get("name") for proj in project_list if proj.get("name")]
            project_name_set_ci = {str(name).strip().lower() for name in project_names}
            
            # 1. VALIDATE CORE INFRASTRUCTURE PROJECTS (Ghost-Card Protection)
            for proj in project_list:
                proj_name = proj["name"]
                proj_name_ci = str(proj_name).strip().lower()
                port = get_port_from_env(proj.get("path", ""))
                if proj_name_ci in pm2_status_map_ci:
                    p = pm2_status_map_ci[proj_name_ci]
                    payload.append(_build_pm2_service_payload(p, port))
                else:
                    # Avoid false "removed" flaps when PM2 snapshot is temporarily unavailable.
                    fallback_status = 'removed' if parsed_live_snapshot else 'unknown'
                    payload.append({
                        'name': proj_name,
                        'status': fallback_status,
                        'cpu': 0,
                        'memory': '0MB',
                        'port': port,
                    })
            
            # 2. CAPTURE DYNAMIC AD-HOC AMRs (Dynamic Virtual Services)
            for p in processes:
                name = p.get("name", "")
                if name.startswith("amr-service-") and str(name).strip().lower() not in project_name_set_ci:
                    payload.append(_build_pm2_service_payload(p, 'N/A'))

            # 3. KEEP NON-AMR, NON-REGISTRY PM2 SERVICES VISIBLE WITH STABLE ORDER
            extra_entries = []
            for name, p in pm2_status_map.items():
                if not name:
                    continue
                lower_name = str(name).strip().lower()
                if lower_name in project_name_set_ci:
                    continue
                if str(name).startswith("amr-service-"):
                    continue
                extra_entries.append((name, p))

            for name, p in sorted(extra_entries, key=lambda item: str(item[0]).lower()):
                payload.append(_build_pm2_service_payload(p, 'N/A'))

            host_metrics = pm2_manager.get_host_metrics()
            for sid in list(_connected_socket_ids):
                cached_user = _socket_user_map.get(sid)
                user_id = str((cached_user or {}).get('id') or '').strip()
                user = get_user_by_id(user_id) if user_id else None
                if not user:
                    _socket_user_map.pop(sid, None)
                    continue
                role = normalize_role_name(user.get('role') or 'tenant_view_user')
                tenant_id = str(user.get('tenant_id') or '').strip()
                if role != 'platform_admin' and (not tenant_id or not get_tenant_by_id(tenant_id)):
                    _socket_user_map.pop(sid, None)
                    continue
                _socket_user_map[sid] = user
                socketio.emit('pm2_telemetry', {'services': _filter_pm2_services_for_user(payload, user), 'host': host_metrics}, room=sid)

        except Exception:
            pass
            
        time.sleep(PM2_TELEMETRY_REFRESH_SECONDS)

def start_web_server():
    # Uses the dynamically imported variables from config.py
    print(f"[SERVER] Launching user interface engine on http://{SERVER_HOST}:{SERVER_PORT}")
    
    threading.Thread(target=pm2_telemetry_loop, daemon=True).start()
    pm2_manager.start_host_metrics_poller()
    
    socketio.run(app, host=SERVER_HOST, port=SERVER_PORT, debug=WEB_DEBUG, use_reloader=False)