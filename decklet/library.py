"""Reads the cards folder and writes card.json, new card folders and _deleted moves. It never changes an image file.

Folder layout:
    <root>/<Person>/                 one person
    <root>/<Person>/front.jpg ...    their first card (optional)
    <root>/<Person>/card.json        person details (and the first card's details)
    <root>/<Person>/<Card>/          more cards for the same person, one subfolder each
    <root>/<Person>/<Card>/card.json that card's details (company, role, email, ...)
"""

import json
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

# ===================== CONFIG =====================
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".heic")  # image types a card folder may hold
CARD_FILE = "card.json"  # optional details file in a person or card folder
DELETED_DIR = "_deleted"  # Delete moves folders here, inside the root
# Details about the person, shared by all their cards.
PERSON_FIELDS = ("name", "tags", "notes", "met_at", "met_date")
# Details printed on one card. A card subfolder without card.json uses the person's values.
CARD_FIELDS = ("company", "role", "email", "phone", "website", "address")
# Order of the fields when card.json is written.
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

SIDES = ("front", "back")


class LibraryError(Exception):
    """A user-facing message about a folder action that failed."""


@dataclass
class CardFace:
    """One physical business card: a folder with up to two photos."""

    key: str  # "" = photos directly in the person folder, else the card subfolder's name
    folder: Path
    front: Path | None = None
    back: Path | None = None
    details: dict = field(default_factory=dict)  # this folder's card.json ("" key: the person's card.json)
    has_file: bool = False  # this folder has a card.json
    details_error: str = ""
    added: float = 0.0


@dataclass
class Person:
    id: str  # the person folder's name
    folder: Path
    details: dict = field(default_factory=dict)
    has_file: bool = False
    details_error: str = ""
    added: float = 0.0
    cards: list[CardFace] = field(default_factory=list)

    @property
    def name(self) -> str:
        return str(self.details.get("name") or "").strip() or self.id

    def card(self, key: str) -> CardFace:
        for c in self.cards:
            if c.key == key:
                return c
        raise LibraryError("That card is no longer in the folder. Select Rescan.")

    def card_values(self, c: CardFace) -> dict:
        """The card's own details, or the person's when a card subfolder has no card.json."""
        return c.details if c.key == "" or c.has_file else self.details

    def to_json(self) -> dict:
        cover = max(range(len(self.cards)), key=lambda i: self.cards[i].added) if self.cards else 0
        return {
            "id": self.id,
            "name": self.name,
            **{k: _text(self.details.get(k)) for k in PERSON_FIELDS if k not in ("name", "tags")},
            "tags": _tags(self.details.get("tags")),
            "has_details": self.has_file,
            "details_error": self.details_error,
            "added": max([self.added] + [c.added for c in self.cards]),
            "cover": cover,
            "cards": [
                {
                    "key": c.key,
                    "label": c.key,
                    **{k: _text(self.card_values(c).get(k)) for k in CARD_FIELDS},
                    "has_front": c.front is not None,
                    "has_back": c.back is not None,
                    "front_file": c.front.name if c.front else "",
                    "back_file": c.back.name if c.back else "",
                    "has_details": c.has_file,
                    "details_error": c.details_error,
                    "manual_corners": sorted(k for k in SIDES if (c.details.get("corners") or {}).get(k)),
                }
                for c in self.cards
            ],
        }


def _text(v) -> str:
    return "" if v is None else v if isinstance(v, str) else str(v)


def _tags(v) -> list[str]:
    if isinstance(v, list):
        return [str(t) for t in v]
    return [str(v)] if v else []


# ---------- reading ----------


def is_image(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")


def find_images(folder: Path) -> tuple[Path | None, Path | None]:
    """Pick the front and back images in one folder.

    1. Files named front.* / back.* (any letter case) win.
    2. Otherwise 2 images: alphabetical order, 1st = front, 2nd = back. 1 image: it is the front.
    """
    images = sorted((p for p in folder.iterdir() if is_image(p)), key=lambda p: p.name.lower())
    named = {p.stem.lower(): p for p in images if p.stem.lower() in SIDES}
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


def read_details(folder: Path) -> tuple[dict, bool, str]:
    """card.json in a folder: (data, file exists, error message)."""
    cf = folder / CARD_FILE
    if not cf.is_file():
        return {}, False, ""
    try:
        data = json.loads(cf.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise TypeError("it is not a JSON object")
        return data, True, ""
    except (OSError, ValueError, TypeError) as e:
        rel = f"{folder.parent.name}/{folder.name}" if folder.parent.name else folder.name
        log.warning("%s/%s can't be read: %s", rel, CARD_FILE, e)
        return {}, True, f"{CARD_FILE} can't be read: {e}"


def is_hidden(p: Path) -> bool:
    return p.name.startswith(("_", "."))


def read_person(folder: Path) -> Person:
    details, has_file, error = read_details(folder)
    person = Person(
        id=folder.name,
        folder=folder,
        details=details,
        has_file=has_file,
        details_error=error,
        added=folder_added_time(folder),
    )
    front, back = find_images(folder)
    subs = []
    for sub in sorted(
        (p for p in folder.iterdir() if p.is_dir() and not is_hidden(p)), key=lambda p: p.name.lower()
    ):
        s_front, s_back = find_images(sub)
        s_details, s_has, s_error = read_details(sub)
        if s_front or s_back or s_has:
            subs.append(
                CardFace(sub.name, sub, s_front, s_back, s_details, s_has, s_error, folder_added_time(sub))
            )
    if front or back or not subs:
        person.cards.append(CardFace("", folder, front, back, details, has_file, error, person.added))
    person.cards.extend(subs)
    return person


def scan(root: Path) -> list[Person]:
    """Every person folder in the root. Folders starting with '_' or '.' are skipped."""
    people = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir() or is_hidden(entry):
            continue
        try:
            people.append(read_person(entry))
        except OSError as e:
            log.warning("Skipped folder %s: %s", entry.name, e)
    return people


# ---------- writing ----------


def clean_value(key: str, v):
    if key == "tags":
        if isinstance(v, str):
            v = v.split(",")
        return [str(t).strip() for t in (v or []) if str(t).strip()]
    return str(v or "").strip()


def merge_details(existing: dict, data: dict, fields) -> dict:
    """existing card.json with `fields` replaced from data. Known fields in order, then any other keys as they were."""
    merged = dict(existing)
    for k in fields:
        merged[k] = clean_value(k, data.get(k, ""))
    out = {k: merged[k] for k in FIELDS if k in merged}
    out.update({k: v for k, v in merged.items() if k not in out})
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


def default_card_label(details: dict, person: Person) -> str:
    company = str(details.get("company") or "").strip()
    year = str(details.get("met_date") or "")[:4] or str(date.today().year)
    return f"{company} {year}".strip() if company else f"Card {len(person.cards) + 1}"


class Library:
    """The scanned people for one root folder. Thread-safe, because Flask serves requests on several threads."""

    def __init__(self, root: Path | None = None):
        self.root = root
        self._people: dict[str, Person] = {}
        self._lock = threading.Lock()

    def root_ok(self) -> bool:
        return self.root is not None and self.root.is_dir()

    def rescan(self) -> list[Person]:
        if not self.root_ok():
            with self._lock:
                self._people = {}
            return []
        people = scan(self.root)
        with self._lock:
            self._people = {p.id: p for p in people}
        log.info(
            "Scanned %s: %d people, %d cards", self.root.name, len(people), sum(len(p.cards) for p in people)
        )
        return people

    def get(self, person_id: str) -> Person:
        with self._lock:
            person = self._people.get(person_id)
        if person is None:
            raise LibraryError("That card is no longer in the folder. Select Rescan.")
        return person

    def _refresh(self, folder: Path) -> Person:
        person = read_person(folder)
        with self._lock:
            self._people[person.id] = person
        return person

    def _check_writable(self) -> None:
        if not self.root_ok():
            raise LibraryError("The cards folder is not available. Choose it again in Settings.")

    @staticmethod
    def _write_images(folder: Path, images: dict[str, tuple[str, bytes]]) -> None:
        for side, (fn, data) in images.items():
            target = folder / f"{side}{image_ext(fn)}"
            if target.exists():
                raise LibraryError(f"{target.name} already exists in the folder.")
            target.write_bytes(data)

    def add(self, details: dict, images: dict[str, tuple[str, bytes]]) -> Person:
        """New person: make a folder, copy the images in as front.<ext> / back.<ext>, and write card.json."""
        self._check_writable()
        name = str(details.get("name") or "").strip()
        if not name:
            raise LibraryError("Enter a name. It is used as the folder name.")
        for fn, _ in images.values():
            image_ext(fn)
        folder = unique_path(self.root, safe_folder_name(name))
        try:
            folder.mkdir()
            self._write_images(folder, images)
            write_details(folder, merge_details({}, details, FIELDS))
        except OSError as e:
            log.exception("Could not create card folder %s", folder.name)
            raise LibraryError(f"Could not create the card folder: {e.strerror or e}") from e
        log.info("Added person folder %s (images: %s)", folder.name, ", ".join(images) or "none")
        return self._refresh(folder)

    def add_card(
        self, person_id: str, label: str, details: dict, images: dict[str, tuple[str, bytes]]
    ) -> tuple[Person, str]:
        """Another card for a person: a new subfolder with its photos and its own card.json."""
        self._check_writable()
        person = self.get(person_id)
        if person.details_error:
            raise LibraryError(
                f"{person.details_error}. Fix or remove it in a text editor, then select Rescan."
            )
        for fn, _ in images.values():
            image_ext(fn)
        folder = unique_path(
            person.folder, safe_folder_name(label.strip() or default_card_label(details, person))
        )
        try:
            folder.mkdir()
            self._write_images(folder, images)
            write_details(folder, merge_details({}, details, CARD_FIELDS))
            write_details(person.folder, merge_details(person.details, details, PERSON_FIELDS))
        except OSError as e:
            log.exception("Could not create card folder %s/%s", person.id, folder.name)
            raise LibraryError(f"Could not create the card folder: {e.strerror or e}") from e
        log.info("Added card folder %s/%s (images: %s)", person.id, folder.name, ", ".join(images) or "none")
        return self._refresh(person.folder), folder.name

    def update(
        self, person_id: str, card_key: str, details: dict, images: dict[str, tuple[str, bytes]]
    ) -> Person:
        """Save details: person fields to the person's card.json, card fields to the card's card.json.

        New images are only accepted for a side that has none; existing images are never replaced.
        """
        self._check_writable()
        person = self.get(person_id)
        card = person.card(card_key)
        for err in (person.details_error, card.details_error):
            if err:
                raise LibraryError(f"{err}. Fix or remove it in a text editor, then select Rescan.")
        for side in images:
            if getattr(card, side) is not None:
                raise LibraryError(
                    f"This card already has a {side} image. Decklet never replaces image files."
                )
        try:
            self._write_images(card.folder, images)
            if card.key:
                write_details(card.folder, merge_details(card.details, details, CARD_FIELDS))
                write_details(person.folder, merge_details(person.details, details, PERSON_FIELDS))
            else:
                write_details(person.folder, merge_details(person.details, details, FIELDS))
        except OSError as e:
            log.exception("Could not save card %s/%s", person.id, card.key)
            raise LibraryError(f"Could not save the card: {e.strerror or e}") from e
        log.info("Saved %s%s/%s", person.id, f"/{card.key}" if card.key else "", CARD_FILE)
        return self._refresh(person.folder)

    def set_corners(self, person_id: str, card_key: str, corners: dict) -> Person:
        """Save hand-placed corners in the card's card.json. A side set to None goes back to automatic."""
        self._check_writable()
        person = self.get(person_id)
        card = person.card(card_key)
        if card.details_error:
            raise LibraryError(
                f"{card.details_error}. Fix or remove it in a text editor, then select Rescan."
            )
        data = dict(card.details)
        saved = dict(data.get("corners") or {})
        for side in SIDES:
            if side in corners:
                if corners[side] is None:
                    saved.pop(side, None)
                else:
                    saved[side] = [[round(float(x), 5), round(float(y), 5)] for x, y in corners[side]]
        if saved:
            data["corners"] = saved
        else:
            data.pop("corners", None)
        try:
            write_details(card.folder, data)
        except OSError as e:
            raise LibraryError(f"Could not save the corners: {e.strerror or e}") from e
        log.info(
            "Saved corners for %s%s (%s)",
            person.id,
            f"/{card.key}" if card.key else "",
            ", ".join(saved) or "automatic",
        )
        return self._refresh(person.folder)

    def delete(self, person_id: str, card_key: str = "") -> str:
        """Move a card subfolder, or the whole person folder ("" key), into _deleted. Returns the name used there."""
        self._check_writable()
        person = self.get(person_id)
        source = person.card(card_key).folder if card_key else person.folder
        name = f"{person.id} - {card_key}" if card_key else person.id
        trash = self.root / DELETED_DIR
        try:
            trash.mkdir(exist_ok=True)
            target = unique_path(trash, name)
            shutil.move(str(source), str(target))
        except OSError as e:
            log.exception("Could not move %s to %s", name, DELETED_DIR)
            raise LibraryError(f"Could not move the card to {DELETED_DIR}: {e.strerror or e}") from e
        if card_key:
            self._refresh(person.folder)
        else:
            with self._lock:
                self._people.pop(person_id, None)
        log.info("Moved %s to %s/%s", name, DELETED_DIR, target.name)
        return target.name
