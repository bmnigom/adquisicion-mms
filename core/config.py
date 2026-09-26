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
    config = {"mac_address": DEFAULT_MAC}
    try:
        with open(_path(), encoding="utf-8") as f:
            config.update(json.load(f))
    except (OSError, ValueError):
        pass
    return config


def save(config: dict) -> None:
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def normalize_mac(text: str) -> str | None:
    mac = text.strip().upper().replace("-", ":")
    return mac if MAC_PATTERN.match(mac) else None
