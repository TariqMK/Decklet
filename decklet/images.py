"""Makes thumbnails, HEIC copies and straightened ("aligned") card faces in the cache folder. Originals are only read.

Alignment finds the card's four corners in each photo (OpenCV), corrects the perspective and gives the front and
back exactly the same size, so the two faces of the 3D card always line up.
"""

import hashlib
import json
import logging
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

log = logging.getLogger(__name__)

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # a missing native library must not stop the app
    HEIF_OK = False
    log.warning("HEIC support is not available; .heic images will not show", exc_info=True)

# ===================== CONFIG =====================
THUMB_PX = 720  # longest side of gallery thumbnails
THUMB_QUALITY = 85  # JPEG quality of thumbnails
FULL_QUALITY = 92  # JPEG quality of HEIC copies for the 3D viewer
NEEDS_CONVERT = (".heic",)  # types the web view can't show on every platform
ALIGNED_MAX_PX = 2000  # longest side of straightened faces for the 3D viewer
DETECT_PX = 900  # photos are scaled to this size to look for the card's corners
MIN_CARD_AREA = 0.15  # a found card must cover at least this share of the photo
EDGE_INSET = 0.01  # found outlines are pulled in by this share, so no desk shows at the card edge
FULL_FRAME = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]  # no crop: the whole photo
# ==================================================

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def cache_key(src: Path) -> str:
    """Changes when the file changes, so a replaced photo gets a new thumbnail."""
    st = src.stat()
    raw = f"{src.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _render(src: Path, out: Path, max_px: int | None, quality: int) -> Path:
    lock = _lock_for(str(out))
    with lock:
        if out.exists():
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                bg = Image.new("RGB", im.size, (34, 34, 34))
                im = im.convert("RGBA")
                bg.paste(im, mask=im.getchannel("A"))
                im = bg
            if max_px:
                im.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
            tmp = out.with_suffix(".tmp")
            im.save(tmp, "JPEG", quality=quality, optimize=True, progressive=True)
            tmp.replace(out)
        log.info("Made %s %s from %s", "thumbnail" if max_px else "display copy", out.name, src.name)
    return out


def thumbnail(src: Path, cache_dir: Path) -> Path:
    return _render(src, cache_dir / "thumbs" / f"{cache_key(src)}.jpg", THUMB_PX, THUMB_QUALITY)


def display_file(src: Path, cache_dir: Path) -> Path:
    """The full-size image for the 3D viewer: the original, or a JPEG copy for HEIC."""
    if src.suffix.lower() not in NEEDS_CONVERT:
        return src
    return _render(src, cache_dir / "full" / f"{cache_key(src)}.jpg", None, FULL_QUALITY)


# ---------- corners and alignment ----------

Corners = list[
    list[float]
]  # four [x, y] points, 0..1 of the photo, in order top-left, top-right, bottom-right, bottom-left


def open_upright(src: Path) -> Image.Image:
    """The photo as RGB, turned the way its EXIF orientation says (as the browser shows it)."""
    with Image.open(src) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def order_corners(pts) -> np.ndarray:
    """Sort four points into top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(pts, dtype=np.float64).reshape(4, 2)
    s, d = pts.sum(axis=1), pts[:, 1] - pts[:, 0]
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]])


def _quad_ok(quad: np.ndarray, area_total: float) -> bool:
    if len({tuple(np.round(p, 1)) for p in quad}) < 4:
        return False
    area = cv2.contourArea(quad.astype(np.float32))
    return area >= MIN_CARD_AREA * area_total and cv2.isContourConvex(
        quad.astype(np.float32).reshape(-1, 1, 2)
    )


def detect_corners(img: Image.Image) -> Corners | None:
    """Find the card in a photo. Returns its corners (0..1), or None when the card already fills the photo or none is found."""
    w, h = img.size
    scale = DETECT_PX / max(w, h)
    small = np.asarray(
        img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.BILINEAR)
    )
    sh, sw = small.shape[:2]
    total = float(sw * sh)
    found = None

    # 1. Edges: the card outline is usually the largest four-sided shape.
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 30, 110), np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) == 4:
            quad = order_corners(approx)
            if _quad_ok(quad, total):
                found = quad
                break

    # 2. Colour: the card differs from the background around the photo's border.
    if found is None:
        lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
        border = np.concatenate(
            [
                lab[:4].reshape(-1, 3),
                lab[-4:].reshape(-1, 3),
                lab[:, :4].reshape(-1, 3),
                lab[:, -4:].reshape(-1, 3),
            ]
        )
        diff = np.linalg.norm(lab - np.median(border, axis=0), axis=2)
        diff = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            c = max(contours, key=cv2.contourArea)
            quad = order_corners(cv2.boxPoints(cv2.minAreaRect(c)))
            if _quad_ok(quad, total):
                found = quad

    if found is None:
        return None
    centre = found.mean(axis=0)
    found = centre + (found - centre) * (1 - EDGE_INSET)
    found = np.clip(found / [sw, sh], 0.0, 1.0)
    if cv2.contourArea(found.astype(np.float32)) > 0.97:  # the card already fills the photo
        return None
    return [[round(float(x), 5), round(float(y), 5)] for x, y in found]


def auto_corners(src: Path, cache_dir: Path) -> Corners | None:
    """Detected corners for a photo, remembered in the cache so each photo is only searched once."""
    out = cache_dir / "corners" / f"{cache_key(src)}.json"
    if out.exists():
        try:
            return json.loads(out.read_text(encoding="utf-8"))["corners"]
        except (OSError, ValueError, KeyError):
            pass
    corners = detect_corners(open_upright(src))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"corners": corners}), encoding="utf-8")
    log.info("Corners for %s: %s", src.name, "found" if corners else "whole photo")
    return corners


def valid_corners(value) -> Corners | None:
    """Corners from card.json if they are four [x, y] pairs between 0 and 1, else None."""
    try:
        pts = [[float(x), float(y)] for x, y in value]
    except (TypeError, ValueError):
        return None
    if len(pts) != 4 or not all(0 <= v <= 1 for p in pts for v in p):
        return None
    return pts


def quad_size(corners: Corners, size: tuple[int, int]) -> tuple[float, float]:
    """Width and height in pixels of the card the corners outline."""
    tl, tr, br, bl = (np.array(p) * size for p in corners)
    width = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    height = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    return float(width), float(height)


def rotate_corners(corners: Corners) -> Corners:
    """The same outline with the starting corner moved on by one: the card turns 90 degrees."""
    return corners[1:] + corners[:1]


def warp(img: Image.Image, corners: Corners, out_size: tuple[int, int]) -> Image.Image:
    w, h = img.size
    src = np.array([[x * w, y * h] for x, y in corners], dtype=np.float32)
    dst = np.array([[0, 0], [out_size[0], 0], [out_size[0], out_size[1]], [0, out_size[1]]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(
        np.asarray(img), m, out_size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return Image.fromarray(out)


def face_corners(src: Path, saved, cache_dir: Path) -> tuple[Corners, bool]:
    """Corners to use for one photo and whether they came from card.json (True) or detection (False)."""
    manual = valid_corners(saved)
    if manual:
        return manual, True
    return auto_corners(src, cache_dir) or FULL_FRAME, False


def aligned_pair(
    front: Path | None, back: Path | None, saved: dict | None, cache_dir: Path
) -> dict[str, Path]:
    """Straighten both faces and give them the same size. Returns {"front": path, "back": path} in the cache."""
    saved = saved if isinstance(saved, dict) else {}
    sides = {k: v for k, v in (("front", front), ("back", back)) if v is not None}
    imgs, corners, manual = {}, {}, {}
    for side, src in sides.items():
        imgs[side] = open_upright(src)
        corners[side], manual[side] = face_corners(src, saved.get(side), cache_dir)

    lead = "front" if "front" in sides else "back"
    w, h = quad_size(corners[lead], imgs[lead].size)
    if "front" in sides and "back" in sides and not manual["back"]:
        bw, bh = quad_size(corners["back"], imgs["back"].size)
        if (w >= h) != (bw >= bh):  # the back was photographed the other way round
            corners["back"] = rotate_corners(corners["back"])
    scale = min(1.0, ALIGNED_MAX_PX / max(w, h))
    size = (max(1, round(w * scale)), max(1, round(h * scale)))

    out = {}
    for side, src in sides.items():
        raw = f"{cache_key(src)}|{corners[side]}|{size}"
        target = cache_dir / "aligned" / f"{hashlib.sha1(raw.encode()).hexdigest()[:20]}.jpg"
        lock = _lock_for(str(target))
        with lock:
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(".tmp")
                warp(imgs[side], corners[side], size).save(tmp, "JPEG", quality=FULL_QUALITY, optimize=True)
                tmp.replace(target)
                log.info("Aligned %s of %s to %dx%d", side, src.parent.name, *size)
        out[side] = target
    return out
