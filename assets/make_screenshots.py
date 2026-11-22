"""Retakes the README screenshots from the real Decklet page, filled with made-up sample cards.

Writes assets/screenshots/<view>-dark.png at 2x (Decklet has a dark theme only) and
assets/gifs/turn-card.gif (a card turning over in the 3D viewer):
  gallery   the gallery with nine people
  cards     the second card of a person with two cards
  details   the info panel on its own
  corners   the Adjust corners view on a phone-style photo

How it works: it draws fictional business cards (names, companies, .example domains and Ofcom drama
phone numbers), puts them in a temporary cards folder, starts Decklet's own server with its data
folder in a temporary folder too, and captures the page in headless Chromium. Nothing from your own
cards folder or settings is read, and nothing goes online.

Run from the project root, in an environment with the "brand" extra installed:
  pip install -e ".[brand]"
  playwright install chromium
  python assets/make_screenshots.py
"""

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "screenshots"
FONTS = ROOT / "decklet" / "web" / "fonts"
VIEWPORT = {"width": 1120, "height": 720}
SCALE = 2
CARD = (1050, 600)  # card face in px, 3.5 x 2 in

# ---------- sample cards (all made up) ----------

# Each person: folder name, card.json, design, and optional extra cards (subfolder name, card.json, design).
PEOPLE = [
    {
        "folder": "Grace Liu",
        "card": {
            "name": "Grace Liu",
            "company": "Ledger & Lamp Books",
            "role": "Bookseller",
            "email": "grace@ledgerlamp.example",
            "phone": "+44 20 7946 0318",
            "website": "ledgerlamp.example",
            "met_at": "Leeds Book Fair",
            "met_date": "2026-03-14",
            "tags": ["books", "events"],
        },
        "design": ("plain", "#f6f1e4", "#3b2f1e", "#e3b448", "L&L"),
    },
    {
        "folder": "Daniel Price",
        "card": {
            "name": "Daniel Price",
            "company": "Harbour Sailing School",
            "role": "Senior instructor",
            "email": "dan@harboursailing.example",
            "phone": "+44 117 496 0452",
            "website": "harboursailing.example",
            "tags": ["sailing"],
        },
        "design": ("waves", "#ffffff", "#1f5f8b", "#1f5f8b", "HSS"),
    },
    {
        "folder": "Aiko Tanaka",
        "card": {
            "name": "Aiko Tanaka",
            "company": "Kumo Tea House",
            "role": "Owner",
            "email": "aiko@kumotea.example",
            "phone": "+44 161 496 0720",
            "address": "14 Mill Lane, Manchester",
            "tags": ["tea", "suppliers"],
        },
        "design": ("circles", "#eef1ec", "#24584f", "#24584f", "Kumo"),
    },
    {
        "folder": "Sam Hollis",
        "card": {
            "name": "Sam Hollis",
            "company": "Hollis Letterpress",
            "role": "Printer",
            "email": "sam@hollispress.example",
            "phone": "+44 113 496 0915",
            "website": "hollispress.example",
            "tags": ["print", "suppliers"],
            "notes": "Quoted for 500 cards on cotton stock.",
        },
        "design": ("square", "#f7f2e8", "#b3362b", "#b3362b", "H"),
    },
    {
        "folder": "Lena Fischer",
        "card": {
            "name": "Lena Fischer",
            "company": "Fischer & Moss",
            "role": "Partner, solicitor",
            "email": "l.fischer@fischermoss.example",
            "phone": "+44 20 7946 0581",
            "address": "2 Temple Row, Birmingham",
            "tags": ["legal"],
        },
        "design": ("serif", "#fbf8f1", "#6b2234", "#6b2234", "F&M"),
    },
    {
        "folder": "Jonas Weber",
        "card": {
            "name": "Jonas Weber",
            "company": "Weber Cycles",
            "role": "Head mechanic",
            "email": "jonas@webercycles.example",
            "phone": "+44 131 496 0264",
            "website": "webercycles.example",
            "tags": ["bikes"],
        },
        "design": ("dark", "#1d1c1b", "#f0ebe1", "#e0703a", "WC"),
    },
    {
        "folder": "Priya Natarajan",
        "card": {
            "name": "Priya Natarajan",
            "company": "Northlight Optics",
            "role": "Lead optical engineer",
            "email": "priya@northlight.example",
            "phone": "+44 1223 496 077",
            "website": "northlight.example",
            "met_at": "Photonics Expo",
            "met_date": "2026-09-22",
            "tags": ["engineering", "conference"],
        },
        "design": ("lens", "#ffffff", "#1f2f4d", "#1f2f4d", "N"),
    },
    {
        "folder": "Tomás Rivera",
        "card": {
            "name": "Tomás Rivera",
            "company": "Rivera & Hale Bakery",
            "role": "Head baker",
            "email": "tomas@riverahale.example",
            "phone": "+44 117 496 0833",
            "address": "7 Quay Street, Bristol",
            "tags": ["food", "suppliers"],
            "notes": "Does wholesale sourdough from March.",
        },
        "design": ("stamp", "#c9a37b", "#3a2616", "#3a2616", "R&H"),
        "photo": True,  # photographed on a desk, so the Adjust corners view has something to show
    },
    {
        "folder": "Maya Okafor",
        "card": {
            "name": "Maya Okafor",
            "company": "City Parks Trust",
            "role": "Project designer",
            "email": "m.okafor@cityparks.example",
            "phone": "+44 20 7946 0904",
            "website": "cityparks.example",
            "met_at": "Garden Design Week",
            "met_date": "2026-05-18",
            "tags": ["design", "landscape"],
            "notes": "Interested in the courtyard project. Follow up in June.",
        },
        "design": ("plain", "#ffffff", "#2e5d34", "#7aa35a", "CPT"),
        # Her newer card, in a subfolder. The newest card is the one the gallery shows.
        "extra": [
            (
                "Fernhill Landscape Studio",
                {
                    "company": "Fernhill Landscape Studio",
                    "role": "Landscape architect",
                    "email": "maya@fernhill.example",
                    "phone": "+44 20 7946 0127",
                    "website": "fernhill.example",
                    "address": "9 Orchard Yard, London",
                },
                ("leaf", "#f4f1ea", "#2f4a3a", "#2f4a3a", "Fernhill"),
            ),
        ],
    },
]


def ttf(name: str, tmp: Path) -> Path:
    """Convert one of the app's bundled WOFF2 fonts to TTF, so Pillow can draw with it."""
    out = tmp / name.replace(".woff2", ".ttf")
    if not out.exists():
        f = TTFont(str(FONTS / name))
        f.flavor = None
        f.save(str(out))
    return out


class Type:
    def __init__(self, tmp: Path):
        self.files = {
            "sans": ttf("inter-latin-400-normal.woff2", tmp),
            "sans5": ttf("inter-latin-500-normal.woff2", tmp),
            "sans6": ttf("inter-latin-600-normal.woff2", tmp),
            "serif": ttf("cormorant-garamond-latin-600-normal.woff2", tmp),
        }
        # latin-ext holds letters such as "á" in Tomás
        self.ext = {
            "sans": ttf("inter-latin-ext-400-normal.woff2", tmp),
            "sans6": ttf("inter-latin-ext-600-normal.woff2", tmp),
            "serif": ttf("cormorant-garamond-latin-ext-600-normal.woff2", tmp),
        }

    def font(self, kind: str, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.files[kind]), size)

    def text(self, d: ImageDraw.ImageDraw, xy, s: str, kind: str, size: int, fill, anchor="ls"):
        """Draw text, switching to the latin-ext font for characters the latin file lacks."""
        main = self.font(kind, size)
        ext = ImageFont.truetype(str(self.ext.get(kind, self.files[kind])), size)
        cmap = TTFont(str(self.files[kind])).getBestCmap()
        if all(ord(ch) in cmap for ch in s):
            d.text(xy, s, font=main, fill=fill, anchor=anchor)
            return
        x, y = xy
        if anchor[0] == "m":
            x -= d.textlength(s, font=main) / 2
        for ch in s:
            f = main if ord(ch) in cmap else ext
            d.text((x, y), ch, font=f, fill=fill, anchor="l" + anchor[1])
            x += d.textlength(ch, font=f)


def front_face(t: Type, card: dict, design) -> Image.Image:
    style, paper, ink, accent, mark = design
    im = Image.new("RGB", CARD, paper)
    d = ImageDraw.Draw(im)
    w, h = CARD
    name_kind = "serif" if style in ("serif", "leaf") else "sans6"
    name_size = 76 if name_kind == "serif" else 58
    t.text(d, (80, 170), card["name"], name_kind, name_size, ink)
    t.text(d, (80, 222), card.get("role", ""), "sans", 30, ink if style != "dark" else "#bdb6aa")
    t.text(d, (80, 262), card.get("company", ""), "sans5", 30, accent)
    lines = [card.get(k) for k in ("phone", "email", "website", "address") if card.get(k)][:3]
    y = h - 80 - (len(lines) - 1) * 42
    for line in lines:
        t.text(d, (80, y), line, "sans", 27, ink if style != "dark" else "#d9d3c8")
        y += 42
    # one small mark per design, top right
    x0, y0 = w - 190, 70
    if style == "leaf":
        d.ellipse((x0 + 40, y0, x0 + 110, y0 + 110), outline=accent, width=6)
        d.line((x0 + 75, y0 + 10, x0 + 75, y0 + 100), fill=accent, width=6)
    elif style == "waves":
        for i in range(3):
            d.arc((x0, y0 + i * 26, x0 + 120, y0 + 60 + i * 26), 200, 340, fill=accent, width=6)
    elif style == "circles":
        for r in (20, 38, 56):
            d.ellipse((x0 + 60 - r, y0 + 56 - r, x0 + 60 + r, y0 + 56 + r), outline=accent, width=5)
    elif style == "square":
        d.rectangle((x0 + 30, y0, x0 + 120, y0 + 90), fill=accent)
    elif style == "lens":
        d.ellipse((x0 + 20, y0, x0 + 130, y0 + 110), outline=accent, width=5)
        d.ellipse((x0 + 50, y0 + 30, x0 + 100, y0 + 80), fill=accent)
    elif style == "dark":
        d.rectangle((0, h - 24, w, h), fill=accent)
    elif style == "stamp":
        d.ellipse((x0 + 10, y0, x0 + 130, y0 + 120), outline=ink, width=5)
        t.text(d, (x0 + 70, y0 + 72), mark, "serif", 40, ink, anchor="ms")
    elif style == "serif":
        d.line((80, 70, 200, 70), fill=accent, width=3)
    else:
        d.rectangle((w - 150, 0, w - 110, 140), fill=accent)
    return im


def back_face(t: Type, card: dict, design) -> Image.Image:
    style, paper, ink, accent, mark = design
    bg = accent if style not in ("stamp", "dark") else (paper if style == "stamp" else accent)
    fg = paper if bg != paper else ink
    im = Image.new("RGB", CARD, bg)
    d = ImageDraw.Draw(im)
    w, h = CARD
    kind = "serif" if style in ("serif", "leaf", "stamp") else "sans6"
    t.text(d, (w // 2, h // 2 + 30), mark, kind, 110 if kind == "serif" else 92, fg, anchor="ms")
    if style == "waves":
        for i in range(4):
            d.arc((-40, h - 170 + i * 30, w + 40, h + 40 + i * 30), 200, 340, fill=fg, width=4)
    elif style == "stamp":
        d.ellipse((w // 2 - 150, h // 2 - 150, w // 2 + 150, h // 2 + 150), outline=fg, width=6)
    t.text(d, (w // 2, h - 70), card.get("website") or card.get("company", ""), "sans", 26, fg, anchor="ms")
    return im


def as_photo(face: Image.Image, seed: int) -> Image.Image:
    """Put a card face on a desk in perspective, like a phone photo."""
    rng = np.random.default_rng(seed)
    size = (1600, 1200)
    desk = np.zeros((size[1], size[0], 3), np.float32)
    desk[:] = (74, 58, 44)
    grain = cv2.GaussianBlur(
        rng.normal(0, 1, (size[1], size[0])).astype(np.float32), (0, 0), sigmaX=24, sigmaY=2
    )
    desk += grain[..., None] * 60 + rng.normal(0, 4, desk.shape)
    fw, fh = face.size
    quad = np.float32([[300, 270], [1290, 330], [1250, 900], [270, 860]])
    m = cv2.getPerspectiveTransform(np.float32([[0, 0], [fw, 0], [fw, fh], [0, fh]]), quad)
    warped = cv2.warpPerspective(np.asarray(face, np.float32), m, size)
    mask = cv2.warpPerspective(np.ones((fh, fw), np.float32), m, size)[..., None]
    shadow = cv2.GaussianBlur(cv2.warpPerspective(np.ones((fh, fw), np.float32), m, size), (0, 0), 18)
    desk *= 1 - 0.45 * np.roll(shadow, (14, 10), (0, 1))[..., None]
    light = np.linspace(1.06, 0.9, size[0], dtype=np.float32)[None, :, None]
    out = (desk * (1 - mask) + warped * mask) * light
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def make_library(root: Path, t: Type) -> None:
    for n, person in enumerate(PEOPLE):
        folder = root / person["folder"]
        folder.mkdir(parents=True)
        front, back = (
            front_face(t, person["card"], person["design"]),
            back_face(t, person["card"], person["design"]),
        )
        if person.get("photo"):
            front, back = as_photo(front, n), as_photo(back, n + 100)
        front.save(folder / "front.jpg", quality=92)
        back.save(folder / "back.jpg", quality=92)
        (folder / "card.json").write_text(json.dumps(person["card"], indent=2, ensure_ascii=False), "utf-8")
        for key, card, design in person.get("extra", []):
            sub = folder / key
            sub.mkdir()
            time.sleep(0.05)
            full = {**person["card"], **card}
            front_face(t, full, design).save(sub / "front.jpg", quality=92)
            back_face(t, full, design).save(sub / "back.jpg", quality=92)
            (sub / "card.json").write_text(json.dumps(card, indent=2, ensure_ascii=False), "utf-8")
        # Newest first is the default sort, by folder creation time: keep the order above.
        time.sleep(0.05)


# ---------- capture ----------


def release_tag() -> str:
    """The newest release tag, so the screenshots don't look like a test build. Before the first release,
    the version the first release will get."""
    try:
        tags = subprocess.run(
            ["git", "tag", "-l", "v*"], check=False, cwd=ROOT, capture_output=True, text=True
        ).stdout
    except OSError:
        tags = ""
    plain = [x for x in tags.split() if x.count(".") == 2 and "-" not in x]
    plain.sort(key=lambda v: tuple(int(p) for p in v[1:].split(".")))
    return plain[-1] if plain else "v0.0.1"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('Playwright is missing. Run: pip install -e ".[brand]" and then: playwright install chromium')
        return 1

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        os.environ["DECKLET_DATA_DIR"] = str(tmp / "Decklet-data")  # before importing decklet
        sys.path.insert(0, str(ROOT))
        from decklet import paths, server, update_check

        tag = release_tag()
        update_check.display_version = lambda v=None: tag  # screenshots only; the source is unchanged

        cards = tmp / "Business cards"
        make_library(cards, Type(tmp))
        paths.ensure_data_dir()
        logging.getLogger("werkzeug").setLevel(logging.ERROR)  # no request log in the output
        backend = server.Backend(paths.data_dir())
        backend.set_root(cards)
        port, _ = server.start_server(server.create_app(backend))
        OUT.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--use-angle=metal", "--enable-gpu-rasterization"] if sys.platform == "darwin" else []
            )
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=SCALE, color_scheme="dark")
            page.route("**/*", lambda r: r.continue_() if "127.0.0.1" in r.request.url else r.abort())
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_selector(".tile")
            settle(page)
            shot(page, "gallery")

            page.locator(".tile").nth(0).click()  # Maya Okafor, the newest folder
            page.wait_for_selector("#viewer.open")
            settle(page, 1.6)
            page.locator("#panel").screenshot(path=str(OUT / "details-dark.png"))
            print("Wrote", (OUT / "details-dark.png").relative_to(ROOT))

            page.click("#cPrev")  # her older card
            settle(page, 1.6)
            shot(page, "cards")

            page.keyboard.press("Escape")
            tomas = PEOPLE.index(next(p for p in PEOPLE if p.get("photo")))
            page.locator(".tile").nth(len(PEOPLE) - 1 - tomas).click()
            page.wait_for_selector("#viewer.open")
            settle(page, 1.2)
            page.click("#cornBtn")
            page.wait_for_selector("#cornM.open")
            settle(page, 1.0)
            shot(page, "corners")
            page.click("#cornCancel")
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)

            # GIF: Maya's card turns over and back again.
            page.locator(".tile").nth(0).click()
            page.wait_for_selector("#viewer.open")
            settle(page, 1.6)
            for _ in range(2):  # two flips leave the card flat on its front, where the loop ends too
                page.click("#flipBtn")
                page.wait_for_timeout(1500)
            record_gif(page, OUT.parent / "gifs" / "turn-card.gif")
            browser.close()
    return 0


def record_gif(page, out: Path) -> None:
    """Hold, flip to the back, hold, flip to the front. Frames keep their real timing."""
    clip = {"x": 60, "y": 90, "width": 620, "height": 440}  # the card area of the stage, in page px
    frames: list[tuple[Image.Image, float]] = []

    def capture(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            t0 = time.monotonic()
            png = page.screenshot(clip=clip, animations="allow")
            frames.append((Image.open(io.BytesIO(png)).convert("RGB"), t0))

    # Run the viewer's animation at 20 steps a second instead of 60, so the turn is slow enough to follow.
    page.evaluate(
        "() => { window.requestAnimationFrame = cb => setTimeout(() => cb(performance.now()), 50); }"
    )
    capture(0.6)
    page.click("#flipBtn")
    capture(2.6)
    page.click("#flipBtn")
    capture(2.6)
    width = 840
    images, durations = [], []
    for n, (im, t0) in enumerate(frames):
        nxt = frames[n + 1][1] if n + 1 < len(frames) else t0 + 0.07
        images.append(im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS))
        durations.append(max(20, round((nxt - t0) * 1000)))
    # Pause on each resting side: the last frame before each flip and the final frame.
    durations[-1] += 900
    # One palette from frames of both sides, so neither face's colours drift.
    picks = images[:: max(1, len(images) // 8)]
    mosaic = Image.new("RGB", (width, sum(im.height for im in picks)))
    y = 0
    for im in picks:
        mosaic.paste(im, (0, y))
        y += im.height
    palette = mosaic.quantize(colors=192, method=Image.Quantize.MEDIANCUT)
    quantized = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
    out.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        out, save_all=True, append_images=quantized[1:], duration=durations, loop=0, optimize=True, disposal=1
    )
    print(f"Wrote {out.relative_to(ROOT)} ({len(images)} frames, {out.stat().st_size // 1024} KB)")


def settle(page, seconds: float = 0.6) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_function("[...document.images].every(i => i.complete)")
    page.wait_for_timeout(int(seconds * 1000))


def shot(page, view: str) -> None:
    out = OUT / f"{view}-dark.png"
    page.screenshot(path=str(out))
    print("Wrote", out.relative_to(ROOT))


if __name__ == "__main__":
    sys.exit(main())
