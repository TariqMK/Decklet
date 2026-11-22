"""Makes gallery thumbnails and browser-friendly copies of HEIC photos in the cache folder. Originals are only read."""

import hashlib
import logging
import threading
from pathlib import Path

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
