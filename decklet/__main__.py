"""Starts Decklet: logging first, then the local server, then the desktop window (pywebview)."""

import html
import logging
import platform
import sys
import time

from decklet import APP_NAME, app_log, paths
from decklet.server import Backend, create_app, start_server

# ===================== CONFIG =====================
WINDOW_SIZE = (1320, 860)  # starting window size in px
MIN_SIZE = (900, 600)  # smallest window size in px
BACKGROUND = "#161616"  # window colour before the page loads
# ==================================================

log = logging.getLogger("decklet.main")


def main() -> None:
    if "--self-test" in sys.argv[1:]:
        from decklet import self_test

        sys.exit(self_test.run())
    started = time.monotonic()
    data_dir = paths.data_dir()
    try:
        paths.ensure_data_dir()
    except OSError as e:
        # The folder next to the app can't be written (for example under Program Files).
        _fatal(
            f"{APP_NAME} keeps its settings in a folder next to the app, but can't create it:\n\n"
            f"{data_dir}\n\n{e}\n\nMove {APP_NAME} to a folder you can write to, such as Documents."
        )
        return
    settings = paths.load_settings()
    app_log.setup(data_dir, settings)

    import webview  # imported after logging, so a failing GUI library is recorded

    backend = Backend(data_dir)
    app = create_app(backend)
    port, _ = start_server(app)
    backend.port = port

    window = webview.create_window(
        APP_NAME,
        f"http://127.0.0.1:{port}/",
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=MIN_SIZE,
        background_color=BACKGROUND,
        text_select=True,
    )
    backend.window = window

    def on_loaded():
        try:
            screens = webview.screens
            log.info("Screens: %d (%s)", len(screens), ", ".join(f"{s.width}x{s.height}" for s in screens))
        except Exception as e:  # noqa: BLE001 - screen info is only for the log
            log.info("Screens: unknown (%s)", e)
        log.info("Window loaded; startup took %.2f s", time.monotonic() - started)

    window.events.loaded += on_loaded

    def on_closed():
        log.info("Window closed")
        app_log.end_session()  # macOS can end the process before webview.start() returns

    window.events.closed += on_closed

    gui = "qt" if platform.system() == "Linux" else None
    try:
        # storage_path keeps the web view's own files in the data folder, not AppData.
        webview.start(
            gui=gui,
            private_mode=False,
            storage_path=str(data_dir / "webview"),
            icon=window_icon(),
        )
    finally:
        app_log.end_session()


def window_icon(system: str | None = None) -> str | None:
    """The PNG window icon for Linux. Windows takes the icon from the .exe and macOS from the .app.

    On Windows, pywebview loads this file with .NET's Icon(), which accepts only .ico files. A PNG makes it
    fail before the window is shown, so the app quits with no window.
    """
    if (system or platform.system()) == "Windows":
        return None
    return str(paths.resource_dir() / "icon.png")


def _fatal(message: str) -> None:
    print(message, file=sys.stderr)
    try:
        import webview

        webview.create_window(
            f"{APP_NAME} can't start", html=f"<pre style='padding:20px'>{html.escape(message)}</pre>"
        )
        webview.start()
    except Exception as e:  # noqa: BLE001 - the message is already on stderr
        print(f"Could not show the error window: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
