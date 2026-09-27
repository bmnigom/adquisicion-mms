"""Configuracion local del equipo (sensor asignado), guardada junto a los datos."""
import json
import os
import re

from core import storage

DEFAULT_MAC = "E7:D7:CE:C3:E0:25"
MAC_PATTERN = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def _path() -> str:
    return os.path.join(storage.DATA_DIR, "configuracion.json")


def load() -> dict:
    """Configuracion guardada; un archivo danado o incompleto no impide arrancar."""
    config = {"mac_address": DEFAULT_MAC}
    try:
        with open(_path(), encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return config
    if isinstance(saved, dict):
        config.update(saved)
    mac = normalize_mac(config["mac_address"]) if isinstance(config["mac_address"], str) else None
    config["mac_address"] = mac or DEFAULT_MAC
    return config


def save(config: dict) -> None:
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def normalize_mac(text: str) -> str | None:
    mac = text.strip().upper().replace("-", ":")
    return mac if MAC_PATTERN.match(mac) else None
