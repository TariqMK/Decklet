"""Tests for reading person folders and the non-destructive writes (card.json, Add card, Delete)."""

import json

import pytest
from conftest import make_image

from decklet.library import Library, LibraryError, find_images, safe_folder_name, scan


def test_named_front_back_any_case(root):
    front, back = find_images(root / "Elias Brandt")
    assert front.name == "FRONT.JPG" and back.name == "Back.png"


def test_two_unnamed_images_use_alphabetical_order(tmp_path):
    f = tmp_path / "P"
    make_image(f / "IMG_0002.jpg")
    make_image(f / "IMG_0001.jpg")
    front, back = find_images(f)
    assert (front.name, back.name) == ("IMG_0001.jpg", "IMG_0002.jpg")


def test_one_image_is_the_front(tmp_path):
    make_image(tmp_path / "P" / "scan.webp", fmt="WEBP")
    assert find_images(tmp_path / "P") == (tmp_path / "P" / "scan.webp", None)


def test_named_front_plus_one_other_image_uses_it_as_back(tmp_path):
    make_image(tmp_path / "P" / "front.jpg")
    make_image(tmp_path / "P" / "reverse.jpg")
    front, back = find_images(tmp_path / "P")
    assert (front.name, back.name) == ("front.jpg", "reverse.jpg")


def test_other_files_are_ignored(tmp_path):
    make_image(tmp_path / "P" / "front.jpg")
    (tmp_path / "P" / "notes.txt").write_text("x")
    (tmp_path / "P" / "back.gif").write_bytes(b"GIF89a")
    assert find_images(tmp_path / "P") == (tmp_path / "P" / "front.jpg", None)


def test_scan_skips_deleted_and_hidden_folders(root):
    (root / "_deleted" / "Old").mkdir(parents=True)
    (root / ".cache").mkdir()
    (root / "loose.jpg").write_bytes(b"x")
    assert [c.id for c in scan(root)] == ["Elias Brandt", "Maya Okafor"]


def test_name_comes_from_folder_without_card_json(root):
    card = {c.id: c for c in scan(root)}["Elias Brandt"]
    data = card.to_json()
    assert card.name == "Elias Brandt" and data["has_details"] is False
    assert (data["front_file"], data["back_file"]) == ("FRONT.JPG", "Back.png")


def test_broken_card_json_still_shows_card_and_blocks_edit(root):
    (root / "Elias Brandt" / "card.json").write_text("{ not json", encoding="utf-8")
    lib = Library(root)
    lib.rescan()
    card = lib.get("Elias Brandt")
    assert card.details_error and card.name == "Elias Brandt"
    with pytest.raises(LibraryError):
        lib.update("Elias Brandt", {"name": "X"}, {})
    assert (root / "Elias Brandt" / "card.json").read_text(encoding="utf-8") == "{ not json"


def test_update_writes_pretty_json_and_keeps_unknown_keys(root):
    cf = root / "Maya Okafor" / "card.json"
    cf.write_text(json.dumps({"name": "Maya Okafor", "linkedin": "maya-o"}), encoding="utf-8")
    images_before = {p.name: p.read_bytes() for p in (root / "Maya Okafor").glob("*.jpg")}
    lib = Library(root)
    lib.rescan()
    lib.update("Maya Okafor", {"name": "Maya O.", "role": "Architect", "tags": "a, b ,,c"}, {})
    text = cf.read_text(encoding="utf-8")
    data = json.loads(text)
    assert text.startswith('{\n  "name": "Maya O."')
    assert data["tags"] == ["a", "b", "c"] and data["linkedin"] == "maya-o" and data["role"] == "Architect"
    assert list(data)[:11] == [
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
    ]
    assert {p.name: p.read_bytes() for p in (root / "Maya Okafor").glob("*.jpg")} == images_before
    assert (root / "Maya Okafor").exists()  # never renamed


def test_update_never_replaces_an_existing_image(root):
    lib = Library(root)
    lib.rescan()
    with pytest.raises(LibraryError, match="never replaces"):
        lib.update("Maya Okafor", {"name": "Maya"}, {"back": ("new.jpg", b"data")})


def test_update_can_add_a_missing_side(tmp_path):
    make_image(tmp_path / "R" / "Solo" / "front.jpg")
    lib = Library(tmp_path / "R")
    lib.rescan()
    card = lib.update("Solo", {"name": "Solo"}, {"back": ("IMG.PNG", b"png-bytes")})
    assert card.back.name == "back.png" and card.back.read_bytes() == b"png-bytes"


def test_add_creates_folder_copies_images_and_writes_json(root):
    lib = Library(root)
    lib.rescan()
    card = lib.add(
        {"name": "Tom Hale", "company": "Copperleaf"},
        {"front": ("IMG_1.JPEG", b"F"), "back": ("IMG_2.heic", b"B")},
    )
    folder = root / "Tom Hale"
    assert card.id == "Tom Hale"
    assert (folder / "front.jpeg").read_bytes() == b"F" and (folder / "back.heic").read_bytes() == b"B"
    assert json.loads((folder / "card.json").read_text(encoding="utf-8"))["company"] == "Copperleaf"


def test_add_never_overwrites_an_existing_folder(root):
    lib = Library(root)
    lib.rescan()
    card = lib.add({"name": "Maya Okafor"}, {})
    assert card.id == "Maya Okafor (2)"
    assert (
        json.loads((root / "Maya Okafor" / "card.json").read_text(encoding="utf-8"))["company"]
        == "Northwind Networks"
    )


def test_add_rejects_unsupported_images_and_needs_a_name(root):
    lib = Library(root)
    with pytest.raises(LibraryError):
        lib.add({"name": "X"}, {"front": ("doc.pdf", b"x")})
    with pytest.raises(LibraryError):
        lib.add({"name": "  "}, {})
    assert not (root / "X").exists()


def test_delete_moves_folder_into_deleted(root):
    lib = Library(root)
    lib.rescan()
    lib.delete("Maya Okafor")
    (root / "Elias Brandt").rename(root / "Maya Okafor")  # same name again
    lib.rescan()
    assert lib.delete("Maya Okafor") == "Maya Okafor (2)"
    assert (root / "_deleted" / "Maya Okafor" / "front.jpg").exists()
    assert (root / "_deleted" / "Maya Okafor (2)" / "FRONT.JPG").exists()
    assert [c.id for c in lib.rescan()] == []


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Maya Okafor", "Maya Okafor"),
        ('A/B:C*D?"', "A B C D"),
        ("CON", "Card CON"),
        ("_hidden", "Card _hidden"),
        ("...", "Card"),
        ("  José  Núñez ", "José Núñez"),
    ],
)
def test_safe_folder_name(name, expected):
    assert safe_folder_name(name) == expected
