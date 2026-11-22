"""Builds the Decklet brand images from the SVG masters in assets/icon/.

Writes:
  assets/icon/decklet.png   1024 x 1024 (Linux build icon, docs)
  assets/icon/decklet.ico   16 to 256 px (Windows build icon)
  assets/icon/decklet.icns  16 to 1024 px, with Retina sizes (macOS build icon)
  decklet/icon.png          512 x 512 window icon, bundled in the app
  assets/banner.png         README banner, 1280 x 320 at 2x
  assets/brand-board.png    brand board from assets/brand.json (layout in assets/brand_board.py)
  assets/social-card.png    GitHub social preview, 1280 x 640, in GitHub's repo-card layout, with the tagline
                            closer to the name than the shared template

Sizes 32 px and smaller come from decklet-small.svg; larger sizes come from decklet.svg.
The name uses Inter from decklet/web/fonts (the app's UI font). The tagline uses the app's
monospace stack (Menlo on macOS, Consolas on Windows, DejaVu Sans Mono on Linux).

Run from the project root, in an environment with the "brand" extra installed:
  pip install -e ".[brand]"
  python assets/make_assets.py
"""

import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageChops
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICON_DIR = ASSETS / "icon"
MASTER = ICON_DIR / "decklet.svg"
SMALL_MASTER = ICON_DIR / "decklet-small.svg"
SMALL_MAX = 32  # sizes up to this use the small master

ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]

# Brand. Colours are the app's tokens in decklet/web/index.html.
NAME = "Decklet"
TAGLINE = "Your business cards, in 3D."
SUBLINE = "Windows · macOS · Linux"
BG_DEEP = "#12110f"  # --deep, the darkest background
BORDER = QColor(239, 233, 222, 36)  # --line2, text colour at 14%
TEXT = "#efe9de"
TEXT_2 = "#aaa398"
TEXT_3 = "#8a847a"
FONT_DIR = ROOT / "decklet" / "web" / "fonts"
UI_FONT_FILE = FONT_DIR / "inter-latin-600-normal.woff2"
MONO = ["SF Mono", "Menlo", "Cascadia Mono", "Consolas", "DejaVu Sans Mono"]


def render_svg(svg: Path, size: int) -> Image.Image:
    """Render an SVG to a square RGBA Pillow image."""
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise SystemExit(f"Could not read {svg}")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return qimage_to_pil(image)


def icon(size: int) -> Image.Image:
    """The icon at one size. Renders at 4x and scales down for clean small sizes."""
    master = SMALL_MASTER if size <= SMALL_MAX else MASTER
    big = render_svg(master, max(size * 4, 256))
    return big.resize((size, size), Image.Resampling.LANCZOS)


def make_icns(out: Path) -> None:
    """Write the .icns. On macOS, iconutil writes every size including 16 and 32 px at 1x;
    elsewhere Pillow writes the set it supports (macOS scales the rest)."""
    if shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "decklet.iconset"
            iconset.mkdir()
            for s in ICNS_SIZES[:-1]:
                icon(s).save(iconset / f"icon_{s}x{s}.png")
                icon(s * 2).save(iconset / f"icon_{s}x{s}@2x.png")
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
    else:
        images = [icon(s) for s in ICNS_SIZES]
        images[-1].save(out, append_images=images[:-1])


def make_icons() -> list[Path]:
    full = icon(1024)
    full.save(ICON_DIR / "decklet.png")
    icon(512).save(ROOT / "decklet" / "icon.png")

    ico = [icon(s) for s in ICO_SIZES]
    ico[-1].save(ICON_DIR / "decklet.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=ico[:-1])

    make_icns(ICON_DIR / "decklet.icns")

    return [
        ICON_DIR / "decklet.png",
        ICON_DIR / "decklet.ico",
        ICON_DIR / "decklet.icns",
        ROOT / "decklet" / "icon.png",
    ]


def register_woff2(path: Path) -> int:
    """Register a bundled WOFF2 font with Qt. Qt can't read WOFF2, so convert it to TTF in memory first."""
    font = TTFont(str(path))
    font.flavor = None
    data = BytesIO()
    font.save(data)
    return QFontDatabase.addApplicationFontFromData(QByteArray(data.getvalue()))


def load_ui_font() -> str:
    """Register Inter 400, 500 and 600 (the app's UI font) and return its family name."""
    for weight in (400, 500):
        register_woff2(FONT_DIR / f"inter-latin-{weight}-normal.woff2")
    font_id = register_woff2(UI_FONT_FILE)
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise SystemExit(f"Could not load {UI_FONT_FILE}")
    return families[0]


def qfont(families: list[str], px: float, weight: QFont.Weight) -> QFont:
    available = set(QFontDatabase.families())
    f = QFont()
    f.setFamilies([x for x in families if x in available] or families)
    f.setPixelSize(round(px))
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def new_canvas(w: int, h: int, scale: int, fill: QColor) -> tuple[QImage, QPainter]:
    image = QImage(w * scale, h * scale, QImage.Format.Format_ARGB32)
    image.fill(fill)
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    painter.scale(scale, scale)
    return image, painter


def draw_svg(painter: QPainter, svg: Path, rect: QRectF) -> None:
    QSvgRenderer(str(svg)).render(painter, rect)


def make_banner(ui: str) -> Path:
    """1280 x 320 (2x): icon left, name and tagline right, centred as one group on a rounded panel."""
    w, h, scale = 1280, 320, 2
    image, p = new_canvas(w, h, scale, QColor(0, 0, 0, 0))
    p.setPen(QPen(BORDER, 1))
    p.setBrush(QColor(BG_DEEP))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 24, 24)

    icon_size, gap, line_gap = 176, 36, 22
    name_font = qfont([ui], 96, QFont.Weight.DemiBold)
    tag_font = qfont(MONO, 24, QFont.Weight.Normal)
    nm, tm = QFontMetrics(name_font), QFontMetrics(tag_font)
    text_w = max(nm.horizontalAdvance(NAME), tm.horizontalAdvance(TAGLINE))
    left = (w - (icon_size + gap + text_w)) / 2
    draw_svg(p, MASTER, QRectF(left, (h - icon_size) / 2, icon_size, icon_size))

    # The text block runs from the name's cap height to the tagline's baseline.
    block = nm.capHeight() + line_gap + tm.capHeight() + 10
    top = (h - block) / 2
    x = left + icon_size + gap
    p.setFont(name_font)
    p.setPen(QColor(TEXT))
    p.drawText(QPointF(x - 3, top + nm.capHeight()), NAME)
    p.setFont(tag_font)
    p.setPen(QColor(TEXT_2))
    p.drawText(QPointF(x, top + block), TAGLINE)
    p.end()
    out = ASSETS / "banner.png"
    image.save(str(out))
    return out


def make_social_card(ui: str) -> Path:
    """1280 x 640, full bleed, GitHub's repo-card layout. Fails if anything leaves the 80 px safe area.

    Decklet change to the template: the tagline baseline sits 76 px under the icon tile and the
    subline 44 px under that (template: fixed baselines at 420 and 476), and the group is centred vertically.
    """
    w, h, safe = 1280, 640, 80
    icon_size, icon_gap = 168, 40
    tagline_gap, subline_gap = 76, 44
    inset = icon_size * 100 / 1024  # the master's transparent margin around the tile
    image, p = new_canvas(w, h, 1, QColor(BG_DEEP))

    name_font = qfont([ui], 112, QFont.Weight.DemiBold)
    name_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98)
    nm = QFontMetrics(name_font)
    # Visible group: the icon tile's top edge to the subline's baseline.
    name_below_top = icon_size / 2 + nm.capHeight() / 2  # name baseline, measured from icon_top
    group = (icon_size - 2 * inset) + tagline_gap + subline_gap
    icon_top = (h - group) / 2 - inset
    name_baseline = icon_top + name_below_top
    tagline_baseline = icon_top + icon_size - inset + tagline_gap
    left = (w - (icon_size + icon_gap + nm.horizontalAdvance(NAME))) / 2
    draw_svg(p, MASTER, QRectF(left, icon_top, icon_size, icon_size))
    p.setFont(name_font)
    p.setPen(QColor(TEXT))
    nudge = 112 * 0.035  # side bearing, so the gap to the icon looks even
    p.drawText(QPointF(left + icon_size + icon_gap - nudge, name_baseline), NAME)

    for text, px, color, baseline in (
        (TAGLINE, 34, TEXT_2, tagline_baseline),
        (SUBLINE, 24, TEXT_3, tagline_baseline + subline_gap),
    ):
        f = qfont(MONO, px, QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QPointF((w - QFontMetrics(f).horizontalAdvance(text)) / 2, baseline), text)
    p.end()

    pil = qimage_to_pil(image)
    bg = Image.new("RGBA", pil.size, BG_DEEP)
    x0, y0, x1, y1 = ImageChops.difference(pil.convert("RGB"), bg.convert("RGB")).getbbox()
    if x0 < safe or y0 < safe or x1 > w - safe or y1 > h - safe:
        raise SystemExit(f"Social card content {x0},{y0}-{x1},{y1} is outside the {safe} px safe area")
    out = ASSETS / "social-card.png"
    image.save(str(out))
    return out


def qimage_to_pil(image: QImage) -> Image.Image:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(BytesIO(bytes(data))).convert("RGBA")


def make_brand_board() -> Path:
    """The brand board, drawn by brand_board.py from brand.json."""
    import json

    from brand_board import Board, contrast  # assets/ is on sys.path when run as a script

    spec_path = ASSETS / "brand.json"
    board = Board(json.loads(spec_path.read_text("utf-8")), ASSETS)
    out = ASSETS / "brand-board.png"
    board.render().save(str(out))
    for key, t in board.themes.items():
        for token in ("text", "text_secondary"):
            if (ratio := contrast(t[token], t["bg"])) < 4.5:
                print(f"Warning: {key} {token} is {ratio:.1f}:1 on the background, below 4.5:1")
    return out


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841  (Qt needs an app for rendering)
    ui = load_ui_font()
    for path in [*make_icons(), make_banner(ui), make_social_card(ui), make_brand_board()]:
        print("Wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
