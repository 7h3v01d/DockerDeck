"""
DockerDeck – services/settings_service.py

Persistent settings and deploy preset management.

Responsibilities
----------------
- Load/save user preferences (theme, defaults, etc.)
- Load/save deploy presets
- Handle corrupt/missing files gracefully with clear error reporting
- Expose typed accessors — no raw JSON elsewhere in the codebase

Import boundary: NO tkinter, NO docker_service.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("dockerdeck.settings")

# ── Paths ─────────────────────────────────────
APP_DIR      = Path.home() / ".dockerdeck"
PRESETS_PATH = APP_DIR / "presets.json"
SETTINGS_PATH = APP_DIR / "settings.json"


def _ensure_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


# ── Default settings ──────────────────────────
DEFAULTS: Dict[str, Any] = {
    "show_all_containers": False,
    "logs_tail":           100,
    "daemon_poll_interval": 12,
    "theme":               "dark",
}


class SettingsService:
    """
    Loads, merges, and saves user settings and deploy presets.

    All methods return safe defaults on failure — the app must never
    crash due to a corrupt config file.
    """

    def __init__(self) -> None:
        _ensure_dir()
        self._settings: Dict[str, Any] = self._load_settings()
        self._presets:  Dict[str, Any] = self._load_presets()

    # ── Settings ──────────────────────────────

    def _load_settings(self) -> Dict[str, Any]:
        merged = dict(DEFAULTS)
        if SETTINGS_PATH.exists():
            try:
                data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                merged.update(data)
                logger.debug("Settings loaded from %s", SETTINGS_PATH)
            except Exception as exc:
                logger.warning("Could not load settings (%s); using defaults.", exc)
        return merged

    def save_settings(self) -> None:
        _ensure_dir()
        try:
            SETTINGS_PATH.write_text(
                json.dumps(self._settings, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.error("Could not save settings: %s", exc)
            raise

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._settings[key] = value

    # ── Presets ───────────────────────────────

    def _load_presets(self) -> Dict[str, Any]:
        # Migrate from old single-file location
        old_path = Path.home() / ".dockerdeck_presets.json"
        if old_path.exists() and not PRESETS_PATH.exists():
            try:
                _ensure_dir()
                PRESETS_PATH.write_bytes(old_path.read_bytes())
                old_path.unlink()
                logger.info("Migrated presets from %s to %s", old_path, PRESETS_PATH)
            except Exception as exc:
                logger.warning("Preset migration failed: %s", exc)

        if PRESETS_PATH.exists():
            try:
                data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
                logger.debug("Presets loaded: %d entries", len(data))
                return data
            except Exception as exc:
                logger.warning(
                    "Could not load presets (%s); starting with empty presets.", exc
                )
        return {}

    @property
    def presets(self) -> Dict[str, Any]:
        return self._presets

    def save_preset(self, name: str, values: Dict[str, Any]) -> None:
        """Save a named preset. Raises OSError on disk failure."""
        self._presets[name] = values
        self._persist_presets()
        logger.info("Preset saved: %s", name)

    def delete_preset(self, name: str) -> None:
        self._presets.pop(name, None)
        self._persist_presets()
        logger.info("Preset deleted: %s", name)

    def _persist_presets(self) -> None:
        _ensure_dir()
        PRESETS_PATH.write_text(
            json.dumps(self._presets, indent=2), encoding="utf-8"
        )


# ── Singleton ─────────────────────────────────
settings = SettingsService()
