import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from .domain import RISK_PROFILES, finite

DEFAULTS = {
    "risk_profile": "Balanced", "risk_thresholds": dict(RISK_PROFILES["Balanced"]),
    "catalog_interval_minutes": 60, "global_priority": 3,
    "in_app": True, "desktop": False, "sound": False, "sound_path": "", "highlight": True,
    "notify_existing": False, "notify_new": True, "notify_price": True,
    "notification_limit": 5, "notification_statuses": ["ingame", "online"],
    "seller_priority": ["ingame", "online", "offline", "unknown"],
    "retention_days": 180, "dense_table": True,
}


def paths():
    home = Path.home()
    result = {
        "data": Path(os.getenv("XDG_DATA_HOME", home / ".local/share")) / "rivenscope",
        "state": Path(os.getenv("XDG_STATE_HOME", home / ".local/state")) / "rivenscope",
        "config": Path(os.getenv("XDG_CONFIG_HOME", home / ".config")) / "rivenscope",
        "cache": Path(os.getenv("XDG_CACHE_HOME", home / ".cache")) / "rivenscope",
    }
    for path in result.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return result


def configure_logging(state):
    handler = RotatingFileHandler(state / "rivenscope.log", maxBytes=2_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)


def validate_settings(data):
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError("Unknown settings or invalid format")
    merged = dict(DEFAULTS) | data
    if merged["risk_profile"] not in RISK_PROFILES:
        raise ValueError("Unknown risk mode")
    thresholds = merged["risk_thresholds"]
    if not isinstance(thresholds, dict) or set(thresholds) != set(RISK_PROFILES["Balanced"]):
        raise ValueError("Invalid risk thresholds")
    for k, v in thresholds.items():
        finite(v, k, 0)
    if thresholds["discount"] > 100 or thresholds["confidence"] > 100 or not 5 <= thresholds["samples"] <= 10000 or not 1 <= thresholds["max_age_hours"] <= 8760:
        raise ValueError("Risk thresholds out of range")
    for name, (low, high) in {"catalog_interval_minutes": (60, 1440), "global_priority": (1, 10),
                             "notification_limit": (1, 60), "retention_days": (7, 3650)}.items():
        value = merged[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"Invalid {name}")
    for name in ("in_app", "desktop", "sound", "highlight", "notify_existing", "notify_new", "notify_price", "dense_table"):
        if type(merged[name]) is not bool:
            raise ValueError(f"Invalid {name}")
    if not isinstance(merged["sound_path"], str) or len(merged["sound_path"]) > 4096:
        raise ValueError("Invalid sound path")
    for key in ("notification_statuses", "seller_priority"):
        value = merged[key]
        if not isinstance(value, list) or any(v not in {"ingame", "online", "offline", "unknown"} for v in value) or len(set(value)) != len(value):
            raise ValueError("Invalid status preferences")
    return merged
