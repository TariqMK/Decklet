"""The local Flask server behind the window: serves the page, card images and a small JSON API on 127.0.0.1 only."""

import json
import logging
import platform
import secrets
import threading
import urllib.parse
import webbrowser
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

from . import APP_NAME, REPOSITORY, app_log, images, paths, update_check
from .library import Library, LibraryError

log = logging.getLogger(__name__)

ISSUES_URL = f"https://github.com/{REPOSITORY}/issues/new"
SIDES = ("front", "back")


def os_label(system: str | None = None, release: str | None = None, mac_ver: str | None = None) -> str:
    system = system or platform.system()
    if system == "Darwin":
        return f"macOS {mac_ver if mac_ver is not None else platform.mac_ver()[0]}".strip()
    if system == "Windows":
        return f"Windows {release if release is not None else platform.release()}".strip()
    if system == "Linux":
        try:
            name = platform.freedesktop_os_release().get("PRETTY_NAME", "")
        except OSError:
            name = ""
        return name or f"Linux {release if release is not None else platform.release()}"
    return system


def report_url(version: str, os_name: str) -> str:
    """The bug form with only the version and OS filled in."""
    q = urllib.parse.urlencode({"template": "bug.yml", "version": version, "os": os_name})
    return f"{ISSUES_URL}?{q}"


class Backend:
    """Holds the state the API works on. `window` is set by the desktop shell for native dialogs."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.cache_dir = data_dir / "cache"
        self.settings = paths.load_settings()
        self.library = Library(paths.resolve_root(self.settings))
        self.token = secrets.token_urlsafe(24)
        self.window = None
        self.port = 0
        self.last_release_url = update_check.RELEASES_PAGE
        self._update_lock = threading.Lock()

    def set_root(self, root: Path) -> None:
        old = self.settings.get("root_abs")
        self.settings = paths.store_root(self.settings, root)
        paths.save_settings(self.settings)
        self.library.root = root.resolve()
        log.info("Setting changed: cards folder %s -> %s", old or "(none)", self.settings["root_abs"])


def create_app(backend: Backend) -> Flask:
    web = paths.resource_dir() / "web"
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

    @app.before_request
    def guard():
        # Only the app's own window may talk to this server: block other hosts (DNS rebinding) and other pages.
        host = (request.host or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            abort(403)
        if request.path.startswith("/api/") and request.headers.get("X-Decklet-Token") != backend.token:
            abort(403)

    @app.errorhandler(LibraryError)
    def library_error(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(Exception)
    def unexpected(e):
        if isinstance(getattr(e, "code", None), int):
            return e
        log.error("Request %s %s failed", request.method, request.path, exc_info=e)
        return jsonify(error=f"Something went wrong: {e}"), 500

    # ---------- page ----------

    @app.get("/")
    def index():
        html = (web / "index.html").read_text(encoding="utf-8")
        html = html.replace("__DECKLET_TOKEN__", backend.token)
        resp = Response(html, mimetype="text/html")
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'"
        )
        return resp

    @app.get("/fonts/<name>")
    def fonts(name):
        p = (web / "fonts" / name).resolve()
        if p.parent != (web / "fonts").resolve() or not p.is_file():
            abort(404)
        return send_file(p, max_age=86400)

    # ---------- images ----------

    def card_image(card_id: str, side: str) -> Path:
        if side not in SIDES:
            abort(404)
        try:
            card = backend.library.get(card_id)
        except LibraryError:
            abort(404)
        src = getattr(card, side)
        if src is None or not src.is_file():
            abort(404)
        return src

    @app.get("/media/<kind>/<side>/<path:card_id>")
    def media(kind, side, card_id):
        src = card_image(card_id, side)
        try:
            if kind == "thumb":
                out = images.thumbnail(src, backend.cache_dir)
            elif kind == "full":
                out = images.display_file(src, backend.cache_dir)
            else:
                abort(404)
        except OSError as e:
            log.warning("Could not read image %s/%s: %s", card_id, src.name, e)
            abort(415)
        return send_file(out, max_age=0, conditional=True)

    # ---------- state ----------

    @app.get("/api/state")
    def state():
        lib = backend.library
        return jsonify(
            app=APP_NAME,
            version=update_check.display_version(),
            root=str(lib.root) if lib.root else "",
            root_ok=lib.root_ok(),
            file_manager=app_log.file_manager_name(),
            can_choose=backend.window is not None,
        )

    @app.get("/api/cards")
    def cards():
        lib = backend.library
        if not lib.root_ok():
            if lib.root:
                log.warning("Cards folder is missing: %s", lib.root)
            return jsonify(cards=[], root_ok=False)
        return jsonify(cards=[c.to_json() for c in lib.rescan()], root_ok=True)

    def read_form() -> tuple[dict, dict]:
        try:
            details = json.loads(request.form.get("details", "{}"))
        except ValueError:
            raise LibraryError("The card details could not be read.") from None
        if not isinstance(details, dict):
            raise LibraryError("The card details could not be read.")
        imgs = {}
        for side in SIDES:
            f = request.files.get(side)
            if f and f.filename:
                imgs[side] = (f.filename, f.read())
        return details, imgs

    @app.post("/api/cards")
    def add_card():
        details, imgs = read_form()
        card = backend.library.add(details, imgs)
        return jsonify(card=card.to_json())

    @app.put("/api/cards/<path:card_id>")
    def update_card(card_id):
        details, imgs = read_form()
        card = backend.library.update(card_id, details, imgs)
        return jsonify(card=card.to_json())

    @app.delete("/api/cards/<path:card_id>")
    def delete_card(card_id):
        moved_as = backend.library.delete(card_id)
        return jsonify(ok=True, moved_as=moved_as)

    @app.post("/api/choose-folder")
    def choose_folder():
        if backend.window is None:
            raise LibraryError("Choosing a folder needs the Decklet window.")
        import webview

        start = str(backend.library.root or Path.home())
        result = backend.window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
        if not result:
            return jsonify(changed=False)
        root = Path(result[0] if isinstance(result, (list, tuple)) else result)
        if not root.is_dir():
            raise LibraryError("That folder can't be opened.")
        backend.set_root(root)
        return jsonify(changed=True, root=str(root))

    # ---------- help ----------

    @app.post("/api/view-logs")
    def view_logs():
        p = app_log.log_path()
        if p is None:
            return jsonify(ok=False, path=str(backend.data_dir / app_log.LOG_NAME))
        try:
            app_log.reveal(p)
        except OSError as e:
            log.warning("View Logs failed: %s", e)
            return jsonify(ok=False, path=str(p))
        return jsonify(ok=True, path=str(p))

    @app.post("/api/update-check")
    def update():
        if not backend._update_lock.acquire(blocking=False):
            return jsonify(error="A check is already running."), 409
        try:
            log.info("Update check started")
            info = update_check.check()
            backend.last_release_url = info.url
            headline, detail = update_check.summary(info)
            log.info("Update check result: %s", headline)
            return jsonify(
                headline=headline,
                detail=detail,
                newer=info.newer,
                latest=info.latest,
                offers_page=info.offers_page,
                notes=info.notes if info.offers_page else "",
            )
        except update_check.UpdateError as e:
            log.info("Update check failed: %s", e)
            return jsonify(error=str(e)), 502
        finally:
            backend._update_lock.release()

    @app.post("/api/open")
    def open_link():
        """Open one of a few known GitHub pages in the user's browser. Nothing else can be opened."""
        what = (request.get_json(silent=True) or {}).get("what")
        if what == "release":
            url = backend.last_release_url
        elif what == "report":
            url = report_url(update_check.display_version(), os_label())
        else:
            abort(400)
        if not url.startswith("https://github.com/"):
            url = update_check.RELEASES_PAGE
        webbrowser.open(url)
        log.info("Opened %s page in the browser", what)
        return jsonify(ok=True)

    @app.post("/api/log")
    def ui_log():
        """Errors from the page itself, so a windowed build still records them."""
        data = request.get_json(silent=True) or {}
        msg = str(data.get("message", ""))[:2000]
        logging.getLogger("decklet.ui").error("%s", msg)
        return jsonify(ok=True)

    return app


def make_local_server(app: Flask):
    """A threaded server on 127.0.0.1 with a free port.

    http.server's server_bind() does a reverse DNS lookup (socket.getfqdn), which can hang for 30 s or more
    on macOS and on slow networks. This version binds without it.
    """
    import socketserver

    from werkzeug.serving import ThreadedWSGIServer

    class LocalServer(ThreadedWSGIServer):
        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            self.server_name = "127.0.0.1"
            self.server_port = self.socket.getsockname()[1]

    return LocalServer("127.0.0.1", 0, app)


def start_server(app: Flask) -> tuple[int, threading.Thread]:
    srv = make_local_server(app)
    t = threading.Thread(target=srv.serve_forever, name="server", daemon=True)
    t.start()
    log.info("Server listening on 127.0.0.1:%d", srv.server_port)
    return srv.server_port, t
