"""Reads the cards folder (one subfolder per person) and writes card.json, new card folders and _deleted moves.

It never moves, renames or changes an image file.
"""

import json
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# ===================== CONFIG =====================
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".heic")  # image types a card folder may hold
CARD_FILE = "card.json"  # optional details file in each person folder
DELETED_DIR = "_deleted"  # Delete moves person folders here, inside the root
# Fields in card.json, in the order they are written.
FIELDS = (
    "name",
    "company",
    "role",
    "email",
    "phone",
    "website",
    "address",
    "met_at",
    "met_date",
    "tags",
    "notes",
)
# ==================================================


class LibraryError(Exception):
    """A user-facing message about a folder action that failed."""


@dataclass
class Card:
    id: str  # the person folder's name
    folder: Path
    front: Path | None = None
    back: Path | None = None
    details: dict = field(default_factory=dict)
    details_error: str = ""  # set when card.json exists but can't be read
    added: float = 0.0

    @property
    def name(self) -> str:
        return str(self.details.get("name") or "").strip() or self.id

    def to_json(self) -> dict:
        d = {k: self.details.get(k, [] if k == "tags" else "") for k in FIELDS}
        if not isinstance(d["tags"], list):
            d["tags"] = [str(d["tags"])] if d["tags"] else []
        d["tags"] = [str(t) for t in d["tags"]]
        for k in FIELDS:
            if k != "tags" and not isinstance(d[k], str):
                d[k] = "" if d[k] is None else str(d[k])
        d["name"] = self.name
        return {
            "id": self.id,
            **d,
            "has_front": self.front is not None,
            "front_file": self.front.name if self.front else "",
            "back_file": self.back.name if self.back else "",
            "has_back": self.back is not None,
            "has_details": bool(self.details),
            "details_error": self.details_error,
            "added": self.added,
        }


# ---------- reading ----------


def is_image(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")


def find_images(folder: Path) -> tuple[Path | None, Path | None]:
    """Pick the front and back images in a person folder.

    1. Files named front.* / back.* (any letter case) win.
    2. Otherwise 2 images: alphabetical order, 1st = front, 2nd = back. 1 image: it is the front.
    """
    images = sorted((p for p in folder.iterdir() if is_image(p)), key=lambda p: p.name.lower())
    named = {p.stem.lower(): p for p in images if p.stem.lower() in ("front", "back")}
    front, back = named.get("front"), named.get("back")
    rest = [p for p in images if p not in (front, back)]
    if front is None and back is None:
        if len(rest) > 2:
            log.info("%s: %d images and none named front/back; using the first two", folder.name, len(rest))
        front = rest[0] if rest else None
        back = rest[1] if len(rest) > 1 else None
    elif front is None and len(rest) == 1:
        front = rest[0]
    elif back is None and len(rest) == 1:
        back = rest[0]
    return front, back


def folder_added_time(folder: Path) -> float:
    st = folder.stat()
    return getattr(st, "st_birthtime", None) or (st.st_ctime if os.name == "nt" else st.st_mtime)


def read_card(folder: Path) -> Card:
    front, back = find_images(folder)
    card = Card(id=folder.name, folder=folder, front=front, back=back, added=folder_added_time(folder))
    cf = folder / CARD_FILE
    if cf.is_file():
        try:
            data = json.loads(cf.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise TypeError("it is not a JSON object")
            card.details = data
        except (OSError, ValueError, TypeError) as e:
            card.details_error = f"{CARD_FILE} can't be read: {e}"
            log.warning("%s/%s can't be read: %s", folder.name, CARD_FILE, e)
    return card


def scan(root: Path) -> list[Card]:
    """Every person folder in the root. Folders starting with '_' or '.' are skipped."""
    cards = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        try:
            cards.append(read_card(entry))
        except OSError as e:
            log.warning("Skipped folder %s: %s", entry.name, e)
    return cards


# ---------- writing ----------


def clean_details(data: dict, existing: dict | None = None) -> dict:
    """card.json content: known fields in order, then any unknown keys the file already had, kept as they were."""
    out = {}
    for k in FIELDS:
        v = data.get(k, "")
        if k == "tags":
            if isinstance(v, str):
                v = [t.strip() for t in v.split(",")]
            v = [str(t).strip() for t in (v or []) if str(t).strip()]
        else:
            v = str(v or "").strip()
        out[k] = v
    for k, v in (existing or {}).items():
        if k not in out:
            out[k] = v
    return out


def write_details(folder: Path, details: dict) -> None:
    """Write card.json pretty-printed (indent 2, UTF-8) through a temp file, so a failed write can't corrupt it."""
    target = folder / CARD_FILE
    tmp = folder / f".{CARD_FILE}.tmp"
    tmp.write_text(json.dumps(details, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def safe_folder_name(name: str) -> str:
    """A folder name that works on Windows, macOS and Linux."""
    s = _UNSAFE.sub(" ", name).strip().strip(".").strip()
    s = re.sub(r"\s+", " ", s)[:80].rstrip(". ")
    if not s or s.startswith(("_", ".")) or s.lower() in _RESERVED:
        s = f"Card {s}".strip() if s else "Card"
    return s


def unique_path(parent: Path, name: str) -> Path:
    p, n = parent / name, 2
    while p.exists():
        p = parent / f"{name} ({n})"
        n += 1
    return p


def image_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in IMAGE_EXTS:
        raise LibraryError(f"{Path(filename).name} is not a supported image ({', '.join(IMAGE_EXTS)}).")
    return ext


class Library:
    """The scanned cards for one root folder. Thread-safe, because Flask serves requests on several threads."""

    def __init__(self, root: Path | None = None):
        self.root = root
        self._cards: dict[str, Card] = {}
        self._lock = threading.Lock()

    def root_ok(self) -> bool:
        return self.root is not None and self.root.is_dir()

    def rescan(self) -> list[Card]:
        if not self.root_ok():
            with self._lock:
                self._cards = {}
            return []
        cards = scan(self.root)
        with self._lock:
            self._cards = {c.id: c for c in cards}
        log.info("Scanned %s: %d cards", self.root.name, len(cards))
        return cards

    def get(self, card_id: str) -> Card:
        with self._lock:
            card = self._cards.get(card_id)
        if card is None:
            raise LibraryError("That card is no longer in the folder. Select Rescan.")
        return card

    def _refresh(self, folder: Path) -> Card:
        card = read_card(folder)
        with self._lock:
            self._cards[card.id] = card
        return card

    def _check_writable(self) -> None:
        if not self.root_ok():
            raise LibraryError("The cards folder is not available. Choose it again in Settings.")

    def add(self, details: dict, images: dict[str, tuple[str, bytes]]) -> Card:
        """Make a new person folder, copy the images in as front.<ext> / back.<ext>, and write card.json."""
        self._check_writable()
        name = str(details.get("name") or "").strip()
        if not name:
            raise LibraryError("Enter a name. It is used as the folder name.")
        exts = {side: image_ext(fn) for side, (fn, _) in images.items()}
        folder = unique_path(self.root, safe_folder_name(name))
        try:
            folder.mkdir()
            for side, (_, data) in images.items():
                (folder / f"{side}{exts[side]}").write_bytes(data)
            write_details(folder, clean_details(details))
        except OSError as e:
            log.exception("Could not create card folder %s", folder.name)
            raise LibraryError(f"Could not create the card folder: {e.strerror or e}") from e
        log.info("Added card folder %s (images: %s)", folder.name, ", ".join(images) or "none")
        return self._refresh(folder)

    def update(self, card_id: str, details: dict, images: dict[str, tuple[str, bytes]]) -> Card:
        """Write card.json. New images are only accepted for a side that has none; existing images are never replaced."""
        self._check_writable()
        card = self.get(card_id)
        if card.details_error:
            raise LibraryError(
                f"{card.details_error}. Fix or remove it in a text editor, then select Rescan."
            )
        for side in images:
            if getattr(card, side) is not None:
                raise LibraryError(
                    f"This card already has a {side} image. Decklet never replaces image files."
                )
        try:
            for side, (fn, data) in images.items():
                target = card.folder / f"{side}{image_ext(fn)}"
                if target.exists():
                    raise LibraryError(f"{target.name} already exists in the folder.")
                target.write_bytes(data)
                log.info("Added %s to %s", target.name, card.id)
            write_details(card.folder, clean_details(details, card.details))
        except OSError as e:
            log.exception("Could not save card %s", card.id)
            raise LibraryError(f"Could not save the card: {e.strerror or e}") from e
        log.info("Saved %s/%s", card.id, CARD_FILE)
        return self._refresh(card.folder)

    def delete(self, card_id: str) -> str:
        """Move the person folder into _deleted inside the root. Returns the folder name used there."""
        self._check_writable()
        card = self.get(card_id)
        trash = self.root / DELETED_DIR
        try:
            trash.mkdir(exist_ok=True)
            target = unique_path(trash, card.folder.name)
            shutil.move(str(card.folder), str(target))
        except OSError as e:
            log.exception("Could not move %s to %s", card.id, DELETED_DIR)
            raise LibraryError(f"Could not move the card to {DELETED_DIR}: {e.strerror or e}") from e
        with self._lock:
            self._cards.pop(card_id, None)
        log.info("Moved %s to %s/%s", card.id, DELETED_DIR, target.name)
        return target.name
