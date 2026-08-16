import json
import os
import re
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from jarvis_assistant.config import (
    BASE_DIR,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USER_ID,
    DEFAULT_ADMIN_USERNAME,
    TENANT_CONFIG_DIR as DEFAULT_TENANT_CONFIG_DIR,
    TENANTS_FILE as DEFAULT_TENANTS_FILE,
    USER_CONFIG_DIR as DEFAULT_USER_CONFIG_DIR,
    USERS_FILE as DEFAULT_USERS_FILE,
)

ROLE_DEFINITIONS = {
    "platform_admin": {
        "label": "Platform Admin",
        "scope": "platform",
        "permissions": [
            "view_all_tenants",
            "view_all_projects",
            "view_all_project_files",
            "create_project_resources",
            "modify_project_resources",
            "delete_project_resources",
            "manage_tenant_users",
            "manage_platform_settings",
            "view_assigned_projects",
            "manage_users",
            "view_project_data",
        ],
    },
    "tenant_admin": {
        "label": "Tenant User Admin",
        "scope": "tenant",
        "permissions": [
            "view_assigned_projects",
            "view_project_data",
            "view_project_files",
            "create_project_resources",
            "modify_project_resources",
            "delete_project_resources",
            "manage_tenant_users",
            "configure_tenant_settings",
            "view_tenant_infrastructure",
        ],
    },
    "tenant_view_user": {
        "label": "Tenant View User",
        "scope": "tenant",
        "permissions": [
            "view_assigned_projects",
            "view_project_data",
            "view_project_files",
            "view_tenant_infrastructure",
        ],
    },
}

ROLE_ALIASES = {
    "admin": "platform_admin",
    "platform_admin": "platform_admin",
    "tenant_admin": "tenant_admin",
    "tenant_user_admin": "tenant_admin",
    "tenant_user": "tenant_view_user",
    "tenant_view_user": "tenant_view_user",
    "viewer": "tenant_view_user",
    "user": "tenant_view_user",
}


def normalize_role_name(role):
    if role is None:
        return "tenant_view_user"
    normalized = re.sub(r"[^a-z0-9]+", "_", str(role).strip().lower()).strip("_")
    if not normalized:
        return "tenant_view_user"
    return ROLE_ALIASES.get(normalized, normalized)


def _slugify(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "tenant"


def _get_users_file():
    return Path(os.getenv("JARVIS_USERS_FILE", str(DEFAULT_USERS_FILE)))


def _get_user_config_dir():
    return Path(os.getenv("JARVIS_USER_CONFIG_DIR", str(DEFAULT_USER_CONFIG_DIR)))


def _get_tenants_file():
    return Path(os.getenv("JARVIS_TENANTS_FILE", str(DEFAULT_TENANTS_FILE)))


def _get_tenant_config_dir():
    return Path(os.getenv("JARVIS_TENANT_CONFIG_DIR", str(DEFAULT_TENANT_CONFIG_DIR)))


def get_user_store_path(user_id=None):
    """Return the user store or a per-user settings path. For now the single admin uses the global config, but the path layout is future-ready for multi-user ownership."""
    users_file = _get_users_file()
    if user_id is None:
        users_file.parent.mkdir(parents=True, exist_ok=True)
        return users_file
    user_dir = _get_user_config_dir() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "settings.json"


def load_user_store():
    users_file = _get_users_file()
    if not users_file.exists():
        return {"users": []}

    try:
        with users_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {"users": []}

    if isinstance(data, dict) and isinstance(data.get("users"), list):
        return data
    return {"users": []}


def save_user_store(store):
    users_file = _get_users_file()
    users_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = users_file.with_suffix(users_file.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2)
    os.replace(tmp_path, users_file)


def _coerce_project_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        project_id = str(item).strip()
        if project_id and project_id not in cleaned:
            cleaned.append(project_id)
    return cleaned


def _normalize_user_record(user_record):
    if not isinstance(user_record, dict):
        return None

    user_id = str(user_record.get("id") or user_record.get("username") or "").strip()
    username = str(user_record.get("username") or user_id or "").strip()
    if not user_id or not username:
        return None

    role_name = normalize_role_name(user_record.get("role") or "tenant_user")
    if role_name not in ROLE_DEFINITIONS and role_name != "platform_admin":
        role_name = "tenant_user"

    user = {
        "id": user_id,
        "username": username,
        "role": role_name,
        "tenant_id": str(user_record.get("tenant_id") or "").strip() or None,
        "project_ids": _coerce_project_list(user_record.get("project_ids")),
        "permissions": list(user_record.get("permissions", []) or []),
    }

    if user_record.get("password_hash"):
        user["password_hash"] = str(user_record["password_hash"])
    elif user_record.get("password"):
        user["password_hash"] = generate_password_hash(str(user_record["password"]))
        user["password"] = str(user_record["password"])

    return user


def get_role_permissions(role):
    role_name = normalize_role_name(role)
    definition = ROLE_DEFINITIONS.get(role_name)
    if not definition:
        return []
    return list(definition.get("permissions", []))


def user_has_permission(user, permission, tenant_id=None, project_id=None):
    if not user:
        return False

    if permission == "manage_core_project_path":
        return False

    role_name = normalize_role_name(user.get("role") or "tenant_view_user")
    if role_name not in ROLE_DEFINITIONS:
        return False

    permissions = set(get_role_permissions(role_name))
    custom_permissions = user.get("permissions") or []
    permissions.update(str(item).strip() for item in custom_permissions if str(item).strip())

    if permission in permissions:
        return True

    if permission == "view_assigned_projects":
        return user_has_scope_access(user, tenant_id=tenant_id, project_id=project_id)

    if role_name == "platform_admin":
        return permission in permissions

    if role_name == "tenant_admin":
        if permission in {
            "view_assigned_projects",
            "view_project_data",
            "view_project_files",
            "create_project_resources",
            "modify_project_resources",
            "delete_project_resources",
            "manage_tenant_users",
            "configure_tenant_settings",
            "view_tenant_infrastructure",
        }:
            return user_has_scope_access(user, tenant_id=tenant_id, project_id=project_id)
        return False

    if role_name == "tenant_view_user":
        if permission in {"view_assigned_projects", "view_project_data", "view_project_files", "view_tenant_infrastructure"}:
            return user_has_scope_access(user, tenant_id=tenant_id, project_id=project_id)
        return False

    return False


def user_has_scope_access(user, tenant_id=None, project_id=None):
    if not user:
        return False

    role_name = normalize_role_name(user.get("role") or "tenant_view_user")
    if role_name == "platform_admin":
        return True

    user_tenant_id = str(user.get("tenant_id") or "").strip() or None
    user_project_ids = {str(item).strip() for item in (user.get("project_ids") or []) if str(item).strip()}

    if tenant_id is not None:
        tenant_id = str(tenant_id).strip() or None
    if project_id is not None:
        project_id = str(project_id).strip() or None

    if not user_tenant_id and not user_project_ids:
        return False

    if tenant_id is not None and user_tenant_id and tenant_id != user_tenant_id:
        return False

    if project_id is not None:
        if project_id in user_project_ids:
            return True
        return user_tenant_id is not None and tenant_id == user_tenant_id and role_name in {"tenant_admin", "tenant_view_user"}

    return bool(user_tenant_id) or bool(user_project_ids)


def _is_valid_password_hash(password_hash, password):
    if not password_hash:
        return False
    try:
        return check_password_hash(str(password_hash), str(password or ""))
    except (TypeError, ValueError):
        return False


def ensure_default_admin_user():
    users_file = _get_users_file()
    users_file.parent.mkdir(parents=True, exist_ok=True)
    store = load_user_store()
    users = store.get("users", [])
    valid_users = []
    for user in users:
        normalized = _normalize_user_record(user)
        if normalized:
            valid_users.append(normalized)
    store["users"] = valid_users

    admin = next((user for user in valid_users if user.get("id") == DEFAULT_ADMIN_USER_ID or user.get("username") == DEFAULT_ADMIN_USERNAME), None)
    if admin is None:
        admin = {
            "id": DEFAULT_ADMIN_USER_ID,
            "username": DEFAULT_ADMIN_USERNAME,
            "password_hash": generate_password_hash(DEFAULT_ADMIN_PASSWORD),
            "role": "platform_admin",
            "tenant_id": None,
            "project_ids": [],
        }
        valid_users.append(admin)
        store["users"] = valid_users
        save_user_store(store)
    else:
        if normalize_role_name(admin.get("role")) != "platform_admin":
            admin["role"] = "platform_admin"
        if "password_hash" not in admin and admin.get("password"):
            admin["password_hash"] = generate_password_hash(str(admin["password"]))
            admin.pop("password", None)
        if "password_hash" not in admin:
            admin["password_hash"] = generate_password_hash(DEFAULT_ADMIN_PASSWORD)
        elif admin.get("username") == DEFAULT_ADMIN_USERNAME and not _is_valid_password_hash(admin.get("password_hash"), DEFAULT_ADMIN_PASSWORD):
            admin["password_hash"] = generate_password_hash(DEFAULT_ADMIN_PASSWORD)
        admin.setdefault("tenant_id", None)
        admin.setdefault("project_ids", [])
        store["users"] = valid_users
        save_user_store(store)

    ensure_user_settings_root(DEFAULT_ADMIN_USER_ID)
    return store


def get_user_by_username(username):
    store = ensure_default_admin_user()
    lookup = str(username or "").strip()
    for user in store.get("users", []):
        if user.get("username") == lookup or user.get("id") == lookup:
            return dict(user)
    return None


def get_user_by_id(user_id):
    store = ensure_default_admin_user()
    lookup = str(user_id or "").strip()
    for user in store.get("users", []):
        if user.get("id") == lookup:
            return dict(user)
    return None


def verify_user(username, password):
    user = get_user_by_username(username)
    if user is None:
        return False
    password_hash = user.get("password_hash")
    if not password_hash:
        return False
    return check_password_hash(password_hash, str(password or ""))


def ensure_user_settings_root(user_id):
    user_dir = _get_user_config_dir() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    settings_path = user_dir / "settings.json"
    if not settings_path.exists():
        settings_path.write_text("{}", encoding="utf-8")
    return settings_path


def load_tenant_store():
    tenants_file = _get_tenants_file()
    if not tenants_file.exists():
        return {"tenants": []}
    try:
        with tenants_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {"tenants": []}
    if isinstance(data, dict) and isinstance(data.get("tenants"), list):
        return data
    return {"tenants": []}


def save_tenant_store(store):
    tenants_file = _get_tenants_file()
    tenants_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = tenants_file.with_suffix(tenants_file.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2)
    os.replace(tmp_path, tenants_file)


def get_tenant_by_id(tenant_id):
    store = load_tenant_store()
    lookup = str(tenant_id or "").strip()
    for tenant in store.get("tenants", []):
        if str(tenant.get("id") or "").strip() == lookup:
            return dict(tenant)
    return None


def get_tenant_user_store():
    user_store = load_user_store()
    by_tenant = {}
    for user in user_store.get("users", []):
        if not isinstance(user, dict):
            continue
        tenant_id = str(user.get("tenant_id") or "").strip()
        if not tenant_id:
            continue
        by_tenant.setdefault(tenant_id, []).append(dict(user))
    return by_tenant


def get_tenant_users(tenant_id):
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        return []
    users = []
    for user in load_user_store().get("users", []):
        if not isinstance(user, dict):
            continue
        if str(user.get("tenant_id") or "").strip() == tenant_id:
            users.append(dict(user))
    return users


def add_tenant_user(tenant_id, username, password, role="tenant_view_user", actor=None):
    actor_role = None
    if actor is not None:
        actor_role = normalize_role_name((actor or {}).get("role") if isinstance(actor, dict) else actor)
        if actor_role == "platform_admin":
            pass
        elif actor_role == "tenant_admin":
            actor_tenant_id = str((actor or {}).get("tenant_id") if isinstance(actor, dict) else "").strip()
            if actor_tenant_id != str(tenant_id or "").strip():
                raise PermissionError("Tenant User Admins can only manage users within their own tenant.")
        else:
            raise PermissionError("Only Platform Admins or Tenant User Admins can manage tenant users.")

    tenant_id = str(tenant_id or "").strip()
    username = str(username or "").strip()
    password = str(password or "").strip()
    role_name = normalize_role_name(role or "tenant_view_user")
    if not tenant_id:
        raise ValueError("Tenant id is required.")
    if not username:
        raise ValueError("Username is required.")
    if not password:
        raise ValueError("Password is required.")
    if role_name not in {"tenant_admin", "tenant_view_user"}:
        role_name = "tenant_view_user"
    if actor_role == "tenant_admin" and role_name == "tenant_admin":
        raise PermissionError("Tenant User Admins can only create view-only users.")

    store = load_user_store()
    if any(str(user.get("username") or "").strip().lower() == username.lower() for user in store.get("users", [])):
        raise ValueError(f"Username '{username}' is already in use.")

    user_id = f"{tenant_id}-{_slugify(username)}"
    suffix = 1
    while any(str(item.get("id") or "").strip() == user_id for item in store.get("users", [])):
        suffix += 1
        user_id = f"{tenant_id}-{_slugify(username)}-{suffix}"

    user_record = {
        "id": user_id,
        "username": username,
        "role": role_name,
        "tenant_id": tenant_id,
        "project_ids": [],
        "password_hash": generate_password_hash(password),
    }
    store.setdefault("users", []).append(user_record)
    save_user_store(store)
    ensure_user_settings_root(user_id)
    return build_session_user(user_record)


def update_tenant_user(tenant_id, user_id, username=None, password=None, role=None, actor=None):
    actor_role = None
    if actor is not None:
        actor_role = normalize_role_name((actor or {}).get("role") if isinstance(actor, dict) else actor)
        if actor_role not in {"platform_admin", "tenant_admin"}:
            raise PermissionError("Only Platform Admins or Tenant User Admins can manage tenant users.")
        if actor_role == "tenant_admin":
            actor_tenant_id = str((actor or {}).get("tenant_id") if isinstance(actor, dict) else "").strip()
            if actor_tenant_id != str(tenant_id or "").strip():
                raise PermissionError("Tenant User Admins can only manage users within their own tenant.")

    tenant_id = str(tenant_id or "").strip()
    user_id = str(user_id or "").strip()
    if not tenant_id or not user_id:
        raise ValueError("Tenant id and user id are required.")

    store = load_user_store()
    for user in store.get("users", []):
        if not isinstance(user, dict):
            continue
        if str(user.get("id") or "").strip() != user_id:
            continue
        if str(user.get("tenant_id") or "").strip() != tenant_id:
            raise ValueError("User does not belong to the specified tenant.")

        new_username = str(username or user.get("username") or "").strip()
        if not new_username:
            raise ValueError("Username is required.")
        if new_username.lower() != str(user.get("username") or "").strip().lower() and any(
            str(item.get("username") or "").strip().lower() == new_username.lower()
            for item in store.get("users", [])
            if str(item.get("id") or "").strip() != user_id
        ):
            raise ValueError(f"Username '{new_username}' is already in use.")
        user["username"] = new_username

        normalized_role = normalize_role_name(role or user.get("role") or "tenant_view_user")
        if normalized_role not in {"tenant_admin", "tenant_view_user"}:
            normalized_role = "tenant_view_user"
        if actor_role == "tenant_admin" and normalized_role == "tenant_admin":
            raise PermissionError("Tenant User Admins can only create or edit view-only users.")
        user["role"] = normalized_role

        if password is not None and str(password).strip():
            user["password_hash"] = generate_password_hash(str(password).strip())
        break
    else:
        raise ValueError("User not found.")

    save_user_store(store)
    updated = next(item for item in store.get("users", []) if str(item.get("id") or "").strip() == user_id)
    return build_session_user(updated)


def remove_tenant_user(tenant_id, user_id, actor=None):
    actor_role = None
    if actor is not None:
        actor_role = normalize_role_name((actor or {}).get("role") if isinstance(actor, dict) else actor)
        if actor_role not in {"platform_admin", "tenant_admin"}:
            raise PermissionError("Only Platform Admins or Tenant User Admins can manage tenant users.")
        if actor_role == "tenant_admin":
            actor_tenant_id = str((actor or {}).get("tenant_id") if isinstance(actor, dict) else "").strip()
            if actor_tenant_id != str(tenant_id or "").strip():
                raise PermissionError("Tenant User Admins can only manage users within their own tenant.")

    tenant_id = str(tenant_id or "").strip()
    user_id = str(user_id or "").strip()
    if not tenant_id or not user_id:
        raise ValueError("Tenant id and user id are required.")

    store = load_user_store()
    users = store.get("users", [])
    remaining = []
    removed = None
    for user in users:
        if not isinstance(user, dict):
            continue
        if str(user.get("id") or "").strip() == user_id and str(user.get("tenant_id") or "").strip() == tenant_id:
            removed = dict(user)
            continue
        remaining.append(user)
    if removed is None:
        raise ValueError("User not found.")

    store["users"] = remaining
    save_user_store(store)
    return removed


def set_tenant_core_project_path(tenant_id, core_path, actor=None):
    actor_role = None
    if actor is not None:
        actor_role = normalize_role_name((actor or {}).get("role") if isinstance(actor, dict) else actor)
        if actor_role != "platform_admin":
            raise PermissionError("Only Platform Admins can manage the core project path.")

    tenant_id = str(tenant_id or "").strip()
    normalized = str(core_path or "").strip()
    if not tenant_id:
        raise ValueError("Tenant id is required.")
    if not normalized:
        raise ValueError("Core project path is required.")

    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        raise ValueError("Tenant not found.")

    full_path = os.path.abspath(os.path.normpath(normalized))
    os.makedirs(full_path, exist_ok=True)

    store = load_tenant_store()
    for item in store.get("tenants", []):
        if str(item.get("id") or "").strip() == tenant_id:
            item["core_project_path"] = full_path
            break
    else:
        raise ValueError("Tenant not found.")

    save_tenant_store(store)
    return full_path


def ensure_tenant_core_project_path(tenant_id):
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        raise ValueError("Tenant id is required.")
    tenant_dir = _get_tenant_config_dir() / tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)
    core_path = tenant_dir / "core-project"
    core_path.mkdir(parents=True, exist_ok=True)
    return str(core_path)


def get_tenant_core_project_path(tenant_id):
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return None
    core_path = str(tenant.get("core_project_path") or "").strip()
    if not core_path:
        core_path = ensure_tenant_core_project_path(tenant_id)
        tenant_store = load_tenant_store()
        for item in tenant_store.get("tenants", []):
            if str(item.get("id") or "").strip() == str(tenant_id):
                item["core_project_path"] = core_path
                break
        save_tenant_store(tenant_store)
    return core_path


def create_tenant_registration(tenant_name, admin_username, admin_password, created_by=None, actor=None, core_project_path=None):
    actor_role = None
    if actor is not None:
        actor_role = normalize_role_name((actor or {}).get("role") if isinstance(actor, dict) else actor)
        if actor_role != "platform_admin":
            raise PermissionError("Only Platform Admins can register tenants.")
    if actor is None and created_by is not None:
        creator = get_user_by_id(str(created_by or "").strip()) or get_user_by_username(str(created_by or "").strip())
        if creator:
            actor_role = normalize_role_name(creator.get("role") or "")
            if actor_role != "platform_admin":
                raise PermissionError("Only Platform Admins can register tenants.")

    name = str(tenant_name or "").strip()
    username = str(admin_username or "").strip()
    password = str(admin_password or "").strip()
    if not name:
        raise ValueError("Tenant name is required.")
    if not username:
        raise ValueError("Tenant admin username is required.")
    if not password:
        raise ValueError("Tenant admin password is required.")

    store = load_user_store()
    if any(str(user.get("username") or "").strip().lower() == username.lower() for user in store.get("users", [])):
        raise ValueError(f"Username '{username}' is already in use.")

    tenant_store = load_tenant_store()
    tenant_id = _slugify(name)
    suffix = 1
    while any(str(item.get("id") or "").strip() == tenant_id for item in tenant_store.get("tenants", [])):
        suffix += 1
        tenant_id = f"{_slugify(name)}-{suffix}"

    requested_path = str(core_project_path or "").strip()
    if requested_path:
        core_path = os.path.abspath(os.path.normpath(requested_path))
        os.makedirs(core_path, exist_ok=True)
    else:
        core_path = ensure_tenant_core_project_path(tenant_id)
    tenant_record = {
        "id": tenant_id,
        "name": name,
        "core_project_path": core_path,
        "created_by": str(created_by or "platform_admin").strip() or "platform_admin",
        "created_at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "status": "active",
    }
    tenant_store.setdefault("tenants", []).append(tenant_record)
    save_tenant_store(tenant_store)

    user_record = {
        "id": f"{tenant_id}-admin",
        "username": username,
        "role": "tenant_admin",
        "tenant_id": tenant_id,
        "project_ids": [],
        "password_hash": generate_password_hash(password),
    }
    store.setdefault("users", []).append(user_record)
    save_user_store(store)
    ensure_user_settings_root(user_record["id"])

    return {
        "tenant_id": tenant_id,
        "tenant": tenant_record,
        "user": build_session_user(user_record),
    }


def build_session_user(user):
    if not user:
        return None
    role_name = normalize_role_name(user.get("role") or "tenant_user")
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "role": role_name,
        "tenant_id": str(user.get("tenant_id") or "").strip() or None,
        "project_ids": _coerce_project_list(user.get("project_ids")),
        "permissions": get_role_permissions(role_name),
    }
