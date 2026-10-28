import json
import os
import time
from pathlib import Path

# =====================================================================
# SERVER & NETWORK CONFIGURATION
# =====================================================================
BASE_DIR = Path(__file__).resolve().parents[2]

# Project timezone is UTC; browsers convert timestamps to the user's local zone.
os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()


def _load_env_file(path):
    """Load KEY=VALUE lines from a .env file without overriding real environment variables."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


_load_env_file(BASE_DIR / ".env")


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_socket_path(value):
    path = (value or "/qcc.io").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return path


SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = _env_int("SERVER_PORT", 9999)
SECRET_KEY = os.getenv("SECRET_KEY", "jarvis_secret_system_token_9999")
SOCKET_PATH = _normalize_socket_path(os.getenv("SOCKET_PATH", "/qcc.io"))
WEB_DEBUG = _env_bool("WEB_DEBUG", True)
ASSISTANT_LOG_LABEL = os.getenv("LOG_LABEL", "QUASON").strip() or "QUASON"

# Upload limits are tunable via env to support large local project imports.
UPLOAD_MAX_CONTENT_BYTES = _env_int("MAX_UPLOAD_BYTES", 1024 * 1024 * 1024)
UPLOAD_MAX_FORM_MEMORY_BYTES = _env_int("MAX_FORM_MEMORY_BYTES", 8 * 1024 * 1024)
UPLOAD_MAX_FORM_PARTS = _env_int("MAX_FORM_PARTS", 200000)

PM2_EXECUTABLE = os.getenv("PM2_EXECUTABLE", "pm2.cmd" if os.name == "nt" else "pm2")

# =====================================================================
# PROJECT DEFINITIONS
# =====================================================================
PROJECTS_FILE = Path(os.getenv("PROJECTS_FILE", BASE_DIR / "projects.json"))
SETTINGS_FILE = Path(os.getenv("SETTINGS_FILE", BASE_DIR / "settings.json"))
USERS_FILE = Path(os.getenv("USERS_FILE", BASE_DIR / "users.json"))
USER_CONFIG_DIR = Path(os.getenv("USER_CONFIG_DIR", BASE_DIR / "users"))
TENANTS_FILE = Path(os.getenv("TENANTS_FILE", BASE_DIR / "tenants.json"))
TENANT_CONFIG_DIR = Path(os.getenv("TENANT_CONFIG_DIR", BASE_DIR / "tenants"))
DEFAULT_ADMIN_USER_ID = "admin"
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# Dependency probes can be overridden per deployment without code changes.
ENABLE_PREFLIGHT_CHECKS = _env_bool("ENABLE_PREFLIGHT", True)

if os.name == "nt":
    APACHE_HTTPD_PATH = os.getenv("APACHE_HTTPD_PATH", r"C:\xampp\apache\bin\httpd.exe")
    APACHE_CHECK_CMD = os.getenv("APACHE_CHECK_CMD", 'tasklist /FI "IMAGENAME eq httpd.exe"')
    APACHE_START_CMD = os.getenv("APACHE_START_CMD", "net start Apache2.4")
    REDIS_CHECK_CMD = os.getenv("REDIS_CHECK_CMD", "wsl -e redis-cli ping")
    REDIS_START_CMD = os.getenv("REDIS_START_CMD", "wsl -e sudo service redis-server start")
else:
    APACHE_HTTPD_PATH = os.getenv("APACHE_HTTPD_PATH", "")
    APACHE_CHECK_CMD = os.getenv("APACHE_CHECK_CMD", "")
    APACHE_START_CMD = os.getenv("APACHE_START_CMD", "")
    REDIS_CHECK_CMD = os.getenv("REDIS_CHECK_CMD", "redis-cli ping")
    REDIS_START_CMD = os.getenv("REDIS_START_CMD", "redis-server --daemonize yes")

RABBITMQ_CONTAINER_NAME = os.getenv("RABBITMQ_CONTAINER", "rabbitmq")

DEFAULT_PM2_FIELD_CONFIG = {
    "name": True,
    "status": True,
    "cpu": True,
    "memory": True,
    "port": True,
    "uptime": True,
    "restarts": True,
    "user": False,
    "watching": True,
    "pid": False,
    "namespace": False,
    "mode": False,
    "version": False,
}


def _coerce_bool(value, default):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _load_pm2_config():
    pm2_config = {
        "refresh_seconds": 5,
        "fields": dict(DEFAULT_PM2_FIELD_CONFIG),
    }

    settings_path = Path(os.getenv("SETTINGS_FILE", BASE_DIR / "settings.json"))
    if settings_path.exists():
        try:
            with settings_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                external_pm2 = data.get("pm2", {})
                if isinstance(external_pm2, dict):
                    refresh_seconds = external_pm2.get("refresh_seconds", pm2_config["refresh_seconds"])
                    try:
                        pm2_config["refresh_seconds"] = int(refresh_seconds)
                    except (TypeError, ValueError):
                        pass

                    external_fields = external_pm2.get("fields", {})
                    if isinstance(external_fields, dict):
                        for field_name, default_value in DEFAULT_PM2_FIELD_CONFIG.items():
                            if field_name in external_fields:
                                pm2_config["fields"][field_name] = _coerce_bool(
                                    external_fields[field_name],
                                    default_value,
                                )
        except Exception:
            pass

    env_refresh = os.getenv("PM2_REFRESH_SECONDS")
    if env_refresh is not None:
        pm2_config["refresh_seconds"] = _env_int("PM2_REFRESH_SECONDS", pm2_config["refresh_seconds"])

    for field_name, default_value in DEFAULT_PM2_FIELD_CONFIG.items():
        env_name = f"PM2_SHOW_{field_name.upper()}"
        if env_name in os.environ:
            pm2_config["fields"][field_name] = _env_bool(env_name, default_value)

    pm2_config["refresh_seconds"] = max(1, int(pm2_config["refresh_seconds"]))
    config = {
        "pm2": pm2_config,
        "refresh_seconds": pm2_config["refresh_seconds"],
        "fields": pm2_config["fields"],
    }
    return config


PM2_CONFIG = _load_pm2_config()
PM2_TELEMETRY_REFRESH_SECONDS = int(PM2_CONFIG.get("refresh_seconds", PM2_CONFIG.get("pm2", {}).get("refresh_seconds", 5)))
PM2_FIELDS = dict(PM2_CONFIG.get("fields", PM2_CONFIG.get("pm2", {}).get("fields", DEFAULT_PM2_FIELD_CONFIG)))
# Backward-compatible alias for older imports.
PM2_TELEMETRY_FIELDS = PM2_FIELDS

FRONTEND_CONFIG = {
    "SOCKET_PATH": SOCKET_PATH,
    "ASSISTANT_LOG_LABEL": ASSISTANT_LOG_LABEL,
}

# =====================================================================
# UTILITY FUNCTIONS
# =====================================================================
def get_port_from_env(path, default_port=3000):
    """Extracts the PORT variable from a local .env file if it exists."""
    env_path = Path(path) / ".env"
    if not env_path.exists():
        return default_port
        
    try:
        with env_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith('PORT='):
                    port_str = line.strip().split('=', 1)[1]
                    port_str = port_str.replace('"', '').replace("'", "")
                    return int(port_str)
    except Exception:
        pass
        
    return default_port