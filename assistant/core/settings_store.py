"""Persistence and normalization of the UI/voice settings file."""
import json
import os

from assistant.config import SETTINGS_FILE, DEFAULT_PM2_FIELD_CONFIG

SETTINGS_SCHEMA = {
    "engine": "browser",
    "mic": False,
    "speaker": False,
    "autolisten": False,
    "voiceURI": "",
    "volume": 1.0,
    "rate": 1.0,
}

SETTINGS_ALIASES = {
    "voiceuri": "voiceURI",
}


def coerce_setting_value(key, raw_value):
    if not isinstance(raw_value, str):
        return raw_value

    lower = raw_value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False

    if key in {"volume", "rate"}:
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return raw_value

    # Preserve string representation for numeric-like values expected by UI sliders.
    return raw_value


def normalize_pm2_settings(raw_pm2):
    default_fields = dict(DEFAULT_PM2_FIELD_CONFIG)
    normalized = {
        "refresh_seconds": 5,
        "fields": dict(default_fields),
    }

    if not isinstance(raw_pm2, dict):
        return normalized

    refresh_seconds = raw_pm2.get("refresh_seconds", normalized["refresh_seconds"])
    try:
        normalized["refresh_seconds"] = max(1, int(refresh_seconds))
    except (TypeError, ValueError):
        normalized["refresh_seconds"] = 5

    fields = raw_pm2.get("fields", {})
    if isinstance(fields, dict):
        for field_name in default_fields:
            if field_name not in fields:
                continue
            value = fields[field_name]
            if isinstance(value, str):
                normalized_value = value.strip().lower() in {"1", "true", "yes", "on"}
            else:
                normalized_value = bool(value)
            normalized["fields"][field_name] = normalized_value

    return normalized


def normalize_settings(raw_settings):
    normalized = dict(SETTINGS_SCHEMA)

    if not isinstance(raw_settings, dict):
        return normalized

    merged = dict(raw_settings)
    for old_key, new_key in SETTINGS_ALIASES.items():
        if new_key not in merged and old_key in merged:
            merged[new_key] = merged[old_key]

    for key in SETTINGS_SCHEMA:
        if key in merged:
            normalized[key] = coerce_setting_value(key, merged[key])

    for key, value in merged.items():
        if key not in normalized and key != "pm2":
            normalized[key] = value

    if "pm2" in merged:
        normalized["pm2"] = normalize_pm2_settings(merged["pm2"])

    if normalized["engine"] not in {"browser", "legacy"}:
        normalized["engine"] = SETTINGS_SCHEMA["engine"]

    for key in ("mic", "speaker", "autolisten"):
        normalized[key] = bool(normalized[key])

    if not isinstance(normalized["voiceURI"], str):
        normalized["voiceURI"] = str(normalized["voiceURI"])

    try:
        normalized["volume"] = float(normalized["volume"])
    except (TypeError, ValueError):
        normalized["volume"] = SETTINGS_SCHEMA["volume"]

    try:
        normalized["rate"] = float(normalized["rate"])
    except (TypeError, ValueError):
        normalized["rate"] = SETTINGS_SCHEMA["rate"]

    return normalized


def load_settings():
    settings = dict(SETTINGS_SCHEMA)

    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
                settings = normalize_settings(loaded)
        except Exception:
            # Keep safe defaults when the file is malformed instead of forcing mic/speaker true.
            pass

    return settings


def persist_settings(settings):
    normalized = normalize_settings(settings)

    if "pm2" not in normalized and SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as existing_handle:
                existing = json.load(existing_handle)
            if isinstance(existing, dict) and "pm2" in existing:
                normalized["pm2"] = normalize_pm2_settings(existing.get("pm2", {}))
        except Exception:
            pass

    tmp_path = SETTINGS_FILE.with_suffix(SETTINGS_FILE.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(normalized, f)
    os.replace(tmp_path, SETTINGS_FILE)
