"""Tests for the startup code in decklet/__main__.py."""

from decklet.__main__ import window_icon


def test_no_png_window_icon_on_windows():
    # pywebview on Windows loads the icon with .NET's Icon(), which fails on a PNG and stops the window opening.
    assert window_icon("Windows") is None


def test_png_window_icon_on_linux_and_macos():
    for system in ("Linux", "Darwin"):
        icon = window_icon(system)
        assert icon is not None and icon.endswith("icon.png")
