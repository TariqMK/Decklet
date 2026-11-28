"""--self-test: proves a build can start. Loads everything a build could be missing, then prints "Decklet vX.Y.Z".

It checks the web page, fonts and icon, the local server, image handling (Pillow, HEIC, OpenCV corner detection),
the certificate check used by the update check, and the platform's web view library. It shows no window, never
goes online and writes only to a temporary folder. Exit code 0 means everything loaded; 1 means something failed.
"""

import contextlib
import io
import os
import platform
import shutil
import sys
import tempfile
import traceback
from pathlib import Path


def _say(text: str) -> None:
    # A windowed Windows build has no console, so sys.stdout can be None.
    with contextlib.suppress(Exception):
        if sys.stdout is not None:
            print(text, flush=True)


def _sample_card() -> bytes:
    """A made-up card photo: a light card on a dark table, so corner detection has something to find."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 420), (25, 30, 35))
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 70, 540, 350), fill=(230, 225, 215))
    for y in range(100, 330, 40):
        draw.rectangle((140, y, 420, y + 6), fill=(40, 40, 50))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _check_web_view() -> None:
    """Load the web view library this platform uses, without opening a window."""
    import webview

    system = platform.system()
    if system == "Linux":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from qtpy.QtWebEngineWidgets import QWebEngineView  # noqa: F401 - loads Qt WebEngine's native libraries
        from qtpy.QtWidgets import QApplication

        QApplication.instance() or QApplication([sys.argv[0]])
    elif system == "Windows":
        import clr  # noqa: F401 - pythonnet, which loads the WebView2 control
        import webview.platforms.winforms
    elif system == "Darwin":
        import webview.platforms.cocoa  # noqa: F401


def run() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="decklet-self-test-"))
    os.environ["DECKLET_DATA_DIR"] = str(tmp / "data")  # never write beside the build
    try:
        return _run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(tmp: Path) -> int:
    from decklet import APP_NAME, paths
    from decklet.update_check import display_version

    failures: list[str] = []

    def step(name, fn):
        try:
            fn()
            _say(f"ok   {name}")
        except Exception as e:  # noqa: BLE001 - every failure is reported, then the test goes on
            failures.append(name)
            _say(f"FAIL {name}: {e}")
            _say(traceback.format_exc().rstrip())

    def bundled_files():
        res = paths.resource_dir()
        for rel in ("web/index.html", "icon.png"):
            if not (res / rel).is_file():
                raise FileNotFoundError(rel)
        fonts = list((res / "web" / "fonts").glob("*.woff2"))
        if len(fonts) < 10:
            raise FileNotFoundError(f"only {len(fonts)} fonts in web/fonts")

    def server_and_images():
        from decklet.server import Backend, create_app

        cards = tmp / "cards" / "Sample Person"
        cards.mkdir(parents=True)
        (cards / "front.png").write_bytes(_sample_card())
        paths.ensure_data_dir()
        backend = Backend(paths.data_dir())
        backend.set_root(cards.parent)
        client = create_app(backend).test_client()
        page = client.get("/")
        if page.status_code != 200 or backend.token not in page.get_data(as_text=True):
            raise RuntimeError(f"page: {page.status_code}")
        if client.get("/fonts/inter-latin-400-normal.woff2").status_code != 200:
            raise RuntimeError("font not served")
        token = {"X-Decklet-Token": backend.token}
        people = client.get("/api/cards", headers=token).get_json()["cards"]
        if [p["id"] for p in people] != ["Sample Person"]:
            raise RuntimeError(f"scan: {people}")
        corners = client.get("/api/corners?p=Sample+Person&c=", headers=token).get_json()
        if corners["front"]["auto"] == [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]:
            raise RuntimeError("OpenCV found no card corners")
        for kind in ("thumb", "full"):
            r = client.get(f"/media/{kind}/front/Sample%20Person?c=")
            if r.status_code != 200 or not r.mimetype.startswith("image/"):
                raise RuntimeError(f"{kind} image: {r.status_code}")

    def heic():
        import pillow_heif
        from PIL import Image

        pillow_heif.register_heif_opener()
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (200, 180, 120)).save(buf, "HEIF")
        buf.seek(0)
        if Image.open(buf).size != (64, 48):
            raise RuntimeError("HEIC round trip changed the size")

    def certificates():
        import ssl

        import truststore

        truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    step("bundled files (page, fonts, icon)", bundled_files)
    step("local server, scan, corners and images", server_and_images)
    step("HEIC images", heic)
    step("certificate check (update check)", certificates)
    step(f"web view ({platform.system()})", _check_web_view)

    if failures:
        _say(f"Self-test failed: {', '.join(failures)}")
        return 1
    _say(f"{APP_NAME} {display_version()}")
    return 0
