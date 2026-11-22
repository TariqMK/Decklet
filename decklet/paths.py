"""Finds the app's data folder (next to the app, so it is portable), its bundled files, and keeps settings.json."""

import json
import logging
import os
import sys
from pathlib import Path

from . import APP_NAME

log = logging.getLogger(__name__)

DATA_DIR_NAME = f"{APP_NAME}-data"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_location() -> Path:
    """The folder the user sees the app in: beside the .exe, beside the .app on macOS, or the project root from source."""
    if is_frozen():
        exe = Path(sys.executable).resolve()
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent.parent
        return exe.parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("DECKLET_DATA_DIR")
    return Path(override) if override else app_location() / DATA_DIR_NAME


def resource_dir() -> Path:
    """Where bundled files (web page, fonts, icon) live: the PyInstaller temp folder when frozen, else the package."""
    if is_frozen():
        return Path(sys._MEIPASS) / "decklet"
    return Path(__file__).resolve().parent


def ensure_data_dir() -> Path:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- settings ----------

DEFAULT_SETTINGS = {"root": "", "root_abs": ""}


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> dict:
    p = settings_path()
    data = dict(DEFAULT_SETTINGS)
    if not p.exists():
        log.info("No settings file yet; using defaults")
        return data
    try:
        loaded = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update({k: v for k, v in loaded.items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError) as e:
        log.warning("Could not read %s (%s); using defaults", p.name, e)
    return data


def save_settings(data: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def store_root(settings: dict, root: Path) -> dict:
    """Keep the cards folder both relative to the data folder (survives moving app and cards together) and absolute."""
    root = root.resolve()
    try:
        rel = os.path.relpath(root, data_dir().resolve())
    except ValueError:  # different drive on Windows
        rel = ""
    return {**settings, "root": rel, "root_abs": str(root)}


def resolve_root(settings: dict) -> Path | None:
    """The cards folder from settings, trying the relative path first, then the absolute one."""
    candidates = []
    if settings.get("root"):
        candidates.append((data_dir() / settings["root"]).resolve())
    if settings.get("root_abs"):
        candidates.append(Path(settings["root_abs"]))
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0] if candidates else None
