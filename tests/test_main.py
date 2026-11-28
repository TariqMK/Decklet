"""Tests for the startup code in decklet/__main__.py."""

from decklet.__main__ import window_icon


def test_no_png_window_icon_on_windows():
    # pywebview on Windows loads the icon with .NET's Icon(), which fails on a PNG and stops the window opening.
    assert window_icon("Windows") is None


def test_png_window_icon_on_linux_and_macos():
    for system in ("Linux", "Darwin"):
        icon = window_icon(system)
        assert icon is not None and icon.endswith("icon.png")


def test_self_test_passes_from_source(tmp_path):
    # The release workflow runs --self-test on every build. This keeps it working from source too.
    import os
    import subprocess
    import sys

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    r = subprocess.run(
        [sys.executable, "-m", "decklet", "--self-test"],
        check=False, capture_output=True, text=True, timeout=120, cwd=tmp_path, env=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().splitlines()[-1].startswith("Decklet v")
