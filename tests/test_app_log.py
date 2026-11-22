"""Tests for the self-trimming log file, home-folder hiding, the session header and View Logs."""

import logging
import subprocess
import threading

import pytest

from decklet import app_log


@pytest.fixture
def fresh_root_logger():
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers = []
    app_log._state.update(path=None, ended=False)
    yield
    for h in root.handlers:
        h.close()
    root.handlers = saved


def test_trim_keeps_newest_lines_at_a_line_boundary(tmp_path):
    p = tmp_path / "x.log"
    p.write_text("".join(f"line {i:05d}\n" for i in range(3000)), encoding="utf-8")
    h = app_log.TrimmedFileHandler(p, max_bytes=10_000, keep_bytes=4_000)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "--- older entries removed ---"
    assert lines[1].startswith("line ") and lines[-1] == "line 02999"
    h.emit(logging.LogRecord("t", logging.INFO, "", 0, "after trim", None, None))
    h.flush()
    assert p.read_text(encoding="utf-8").rstrip().endswith("after trim")
    h.close()


def test_trim_happens_when_a_write_passes_the_limit(tmp_path):
    p = tmp_path / "x.log"
    h = app_log.TrimmedFileHandler(p, max_bytes=2_000, keep_bytes=800)
    h.setFormatter(logging.Formatter("%(message)s"))
    for i in range(600):
        h.emit(logging.LogRecord("t", logging.INFO, "", 0, f"entry {i}", None, None))
    h.close()
    assert p.stat().st_size < 2_100
    assert p.read_text(encoding="utf-8").splitlines()[0] == "--- older entries removed ---"


@pytest.mark.parametrize(
    "home,text,expected",
    [
        ("/Users/tariq", "open /Users/tariq/Cards/x.jpg", "open ~/Cards/x.jpg"),
        (r"C:\Users\Tariq", r"read c:\users\tariq\Cards and C:/Users/Tariq/x", r"read ~\Cards and ~/x"),
    ],
)
def test_home_folder_becomes_tilde(home, text, expected):
    assert app_log.home_pattern(home).sub("~", text) == expected


def test_formatter_hides_home_in_tracebacks():
    f = app_log.PrivateFormatter(home="/Users/tariq")
    try:
        raise OSError("/Users/tariq/secret.json missing")
    except OSError:
        import sys

        rec = logging.LogRecord("decklet.library", logging.ERROR, "", 0, "failed", None, sys.exc_info())
    out = f.format(rec)
    assert "/Users/tariq" not in out and "~/secret.json" in out and "[library]" in out
    assert "ERROR" in out


def test_header_has_version_build_kind_and_os(tmp_path):
    text = "\n".join(app_log.header_lines(tmp_path, {"root": ""}))
    assert "Decklet v0.0.0.dev0 (development, from source)" in text and "OS:" in text


@pytest.mark.parametrize(
    "v,kind", [("1.2.3", "release"), ("1.2.3-new-sync.1", "branch build"), ("0.0.0.dev0", "development")]
)
def test_build_kind(v, kind):
    assert app_log.build_kind(v) == kind


def test_unclosed_previous_session_logs_a_warning(tmp_path, fresh_root_logger):
    p = tmp_path / "Decklet.log"
    p.write_text(app_log.SEPARATOR + "\nsomething\n", encoding="utf-8")
    app_log.setup(tmp_path, {})
    app_log.end_session()
    text = p.read_text(encoding="utf-8")
    assert "The previous session did not close normally" in text and text.rstrip().endswith("Session ended")
    app_log._state["ended"] = False
    app_log.setup(tmp_path, {})
    assert text.count("did not close normally") == p.read_text(encoding="utf-8").count(
        "did not close normally"
    )


def test_unhandled_errors_reach_the_file(tmp_path, fresh_root_logger):
    import sys

    saved = sys.excepthook, threading.excepthook
    try:
        app_log.setup(tmp_path, {})

        def boom():
            raise ValueError("thread boom")

        t = threading.Thread(target=boom)
        t.start()
        t.join()
        try:
            raise KeyError("main boom")
        except KeyError:
            sys.excepthook(*sys.exc_info())
        app_log.flush()
        text = (tmp_path / "Decklet.log").read_text(encoding="utf-8")
        assert "thread boom" in text and "main boom" in text and "Traceback" in text
    finally:
        sys.excepthook, threading.excepthook = saved


@pytest.mark.parametrize(
    "system,cmd",
    [
        ("Darwin", ["open", "-R", "/d/Decklet.log"]),
        ("Windows", ["explorer", "/select,/d/Decklet.log"]),
        ("Linux", ["xdg-open", "/d"]),
    ],
)
def test_reveal_command(system, cmd):
    from pathlib import Path

    assert app_log.reveal_command(Path("/d/Decklet.log"), system) == cmd


def test_reveal_runs_without_shell_and_raises_on_failure(tmp_path):
    calls = []
    app_log.reveal(tmp_path / "a.log", "Darwin", popen=lambda cmd, **kw: calls.append((cmd, kw)))
    assert calls[0][0][0] == "open" and "shell" not in calls[0][1]
    assert calls[0][1]["stdout"] is subprocess.DEVNULL

    def fail(*a, **k):
        raise FileNotFoundError("xdg-open")

    with pytest.raises(OSError):
        app_log.reveal(tmp_path / "a.log", "Linux", popen=fail)


def test_file_manager_name():
    assert app_log.file_manager_name("Darwin") == "Finder"
    assert app_log.file_manager_name("Windows") == "File Explorer"
    assert app_log.file_manager_name("Linux") == "the file manager"
