"""Writes Decklet.log in the data folder: always on, trims itself to about 1 MB, hides the home folder as ~."""

import atexit
import faulthandler
import locale
import logging
import os
import platform
import re
import subprocess
import sys
import threading
from pathlib import Path

from . import APP_NAME
from ._version import __version__

LOG_NAME = f"{APP_NAME}.log"
MAX_BYTES = 1_000_000
KEEP_BYTES = 500_000
SEPARATOR = "=" * 72
ENDED = "Session ended"

log = logging.getLogger("decklet.app")
_state = {"path": None, "ended": False, "fault_file": None}


class TrimmedFileHandler(logging.FileHandler):
    """One log file that drops its oldest lines when it grows past max_bytes."""

    def __init__(self, path, max_bytes=MAX_BYTES, keep_bytes=KEEP_BYTES):
        super().__init__(path, encoding="utf-8")
        self.max_bytes, self.keep_bytes = max_bytes, keep_bytes
        self._trim()

    def emit(self, record):
        super().emit(record)
        try:
            if self.stream and os.fstat(self.stream.fileno()).st_size > self.max_bytes:
                self._trim()
        except OSError:
            pass

    def _trim(self):
        self.stream.close()
        path = Path(self.baseFilename)
        if path.exists() and path.stat().st_size > self.max_bytes:
            tail = path.read_bytes()[-self.keep_bytes :]
            tail = tail[tail.find(b"\n") + 1 :]
            path.write_bytes(b"--- older entries removed ---\n" + tail)
        self.stream = self._open()


def home_pattern(home: str | None = None) -> re.Pattern:
    """Matches the home folder with either slash direction, ignoring case on Windows."""
    home = (home or str(Path.home())).rstrip("/\\")
    parts = [re.escape(p) for p in re.split(r"[\\/]", home)]
    flags = re.IGNORECASE if os.name == "nt" or re.match(r"^[A-Za-z]:", home) else 0
    return re.compile(r"[\\/]".join(parts), flags)


class PrivateFormatter(logging.Formatter):
    """Formats as usual, then replaces the home folder with ~ in the whole text, tracebacks included."""

    def __init__(self, home: str | None = None):
        super().__init__("%(asctime)s %(utcoffset)s %(levelname)-7s [%(area)s] %(message)s")
        self._home = home_pattern(home)

    def formatTime(self, record, datefmt=None):
        import time

        t = time.localtime(record.created)
        return time.strftime("%Y-%m-%d %H:%M:%S", t) + f".{int(record.msecs):03d}"

    def format(self, record):
        import time

        off = time.localtime(record.created).tm_gmtoff
        sign = "+" if off >= 0 else "-"
        off = abs(off)
        record.utcoffset = f"{sign}{off // 3600:02d}:{off % 3600 // 60:02d}"
        name = record.name
        record.area = name.split(".", 1)[1] if name.startswith("decklet.") else name
        return self._home.sub("~", super().format(record))


def build_kind(version: str = __version__) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", version):
        return "release"
    if re.fullmatch(r"\d+\.\d+\.\d+-[a-z0-9-]+\.\d+", version):
        return "branch build"
    return "development"


def header_lines(data_dir: Path, settings: dict) -> list[str]:
    frozen = bool(getattr(sys, "frozen", False))
    try:
        import webview

        webview_v = getattr(webview, "__version__", "") or _pkg_version("pywebview")
    except Exception:  # noqa: BLE001
        webview_v = "not available"
    lang = _language()
    lines = [
        f"{APP_NAME} v{__version__} ({build_kind()}, {'built app' if frozen else 'from source'})",
        f"OS: {platform.platform()} ({platform.machine()})",
        f"Python {platform.python_version()}, pywebview {webview_v}",
        f"Language/region: {lang[0] or 'unknown'} ({lang[1] or 'unknown encoding'})",
        f"Data folder: {data_dir}",
    ]
    changed = {k: v for k, v in settings.items() if v}
    lines.append(f"Settings changed from default: {changed or 'none'}")
    return lines


def _language() -> tuple[str | None, str | None]:
    lang = locale.getlocale()
    if not lang[0] and platform.system() == "Darwin":
        try:  # an .app has no LANG variable; ask macOS instead
            from Foundation import NSLocale

            return str(NSLocale.currentLocale().localeIdentifier()), "UTF-8"
        except Exception:  # noqa: BLE001 - only used for the log header
            return lang
    return lang


def _pkg_version(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:  # noqa: BLE001
        return "unknown"


def previous_session_open(path: Path) -> bool:
    """True when the last session in the file has no 'Session ended' line, so it crashed or was forced to quit."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    idx = text.rfind(SEPARATOR)
    if idx < 0:
        return False
    return ENDED not in text[idx:]


def setup(data_dir: Path, settings: dict | None = None) -> Path | None:
    """Start logging first thing at startup. Never raises: the app carries on if the file can't be written."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    path = data_dir / LOG_NAME
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        crashed = path.exists() and previous_session_open(path)
        handler = TrimmedFileHandler(path)
        handler.setFormatter(PrivateFormatter())
        root.addHandler(handler)
        _state["path"] = path
    except OSError:
        return None

    logging.captureWarnings(True)
    for noisy in ("werkzeug", "PIL", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    handler.stream.write(SEPARATOR + "\n")
    handler.flush()
    for line in header_lines(data_dir, settings or {}):
        log.info(line)
    if crashed:
        log.warning("The previous session did not close normally")

    def excepthook(exc_type, exc, tb):
        logging.getLogger("decklet.crash").error("Unhandled error", exc_info=(exc_type, exc, tb))

    def thread_excepthook(args):
        logging.getLogger("decklet.crash").error(
            "Unhandled error in thread %s",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
    try:
        f = open(path, "a", encoding="utf-8")  # noqa: SIM115 - kept open for faulthandler
        faulthandler.enable(file=f)
        _state["fault_file"] = f
    except (OSError, ValueError, RuntimeError):
        pass
    atexit.register(end_session)
    return path


def end_session() -> None:
    if _state["ended"] or not _state["path"]:
        return
    _state["ended"] = True
    log.info(ENDED)
    for h in logging.getLogger().handlers:
        h.flush()


def log_path() -> Path | None:
    return _state["path"]


def flush() -> None:
    for h in logging.getLogger().handlers:
        h.flush()


# ---------- View Logs ----------


def file_manager_name(system: str | None = None) -> str:
    system = system or platform.system()
    return {"Darwin": "Finder", "Windows": "File Explorer"}.get(system, "the file manager")


def reveal_command(path: Path, system: str | None = None) -> list[str]:
    system = system or platform.system()
    if system == "Darwin":
        return ["open", "-R", str(path)]
    if system == "Windows":
        return ["explorer", f"/select,{path}"]
    return ["xdg-open", str(path.parent)]


def reveal(path: Path, system: str | None = None, popen=subprocess.Popen) -> None:
    """Show the file in the file manager without a shell and without waiting. Raises OSError if it can't start."""
    flush()
    cmd = reveal_command(path, system)
    popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.info("View Logs: ran %s", cmd[0])
