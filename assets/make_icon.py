"""Draws the Decklet app icon (two stacked cards, gold on dark) and saves it as .png, .ico and .icns.

Run from the project root: python assets/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
S = 1024  # master size in px


def card(size, fill, outline=None, angle=0.0):
    w, h = int(size * 0.62), int(size * 0.62 / 1.75)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    box = ((size - w) // 2, (size - h) // 2, (size + w) // 2, (size + h) // 2)
    d.rounded_rectangle(
        box, radius=int(h * 0.09), fill=fill, outline=outline, width=int(size * 0.008) if outline else 0
    )
    return layer.rotate(angle, resample=Image.Resampling.BICUBIC), box


def make() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(bg).rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=(22, 22, 22, 255))
    img.alpha_composite(bg)

    back, _ = card(S, (58, 52, 44, 255), angle=14)
    shadow, _ = card(S, (0, 0, 0, 150), angle=-4)
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    front, box = card(S, (201, 169, 110, 255), angle=-4)
    img.alpha_composite(back, (0, -40))
    img.alpha_composite(shadow, (0, 34))
    img.alpha_composite(front, (0, 30))

    # Simple text lines on the front card.
    lines = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(lines)
    x0, y0, _, y1 = box
    h = y1 - y0
    d.rounded_rectangle(
        (x0 + 60, y0 + h * 0.30 + 30, x0 + 330, y0 + h * 0.30 + 66), radius=18, fill=(22, 22, 22, 235)
    )
    d.rounded_rectangle(
        (x0 + 60, y0 + h * 0.30 + 100, x0 + 240, y0 + h * 0.30 + 124), radius=12, fill=(22, 22, 22, 150)
    )
    d.rounded_rectangle(
        (x0 + 60, y0 + h * 0.30 + 150, x0 + 280, y0 + h * 0.30 + 174), radius=12, fill=(22, 22, 22, 150)
    )
    img.alpha_composite(lines.rotate(-4, resample=Image.Resampling.BICUBIC))
    return img


def main() -> None:
    img = make()
    img.save(ROOT / "decklet" / "icon.png")
    img.save(ROOT / "assets" / "icon.png")
    img.save(
        ROOT / "assets" / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    img.save(ROOT / "assets" / "icon.icns")
    print("Saved decklet/icon.png, assets/icon.png, assets/icon.ico, assets/icon.icns")


if __name__ == "__main__":
    main()
