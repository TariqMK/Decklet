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
    person = {p.id: p for p in scan(root)}["Elias Brandt"]
    data = person.to_json()
    assert person.name == "Elias Brandt" and data["has_details"] is False
    assert (data["cards"][0]["front_file"], data["cards"][0]["back_file"]) == ("FRONT.JPG", "Back.png")


def test_broken_card_json_still_shows_card_and_blocks_edit(root):
    (root / "Elias Brandt" / "card.json").write_text("{ not json", encoding="utf-8")
    lib = Library(root)
    lib.rescan()
    card = lib.get("Elias Brandt")
    assert card.details_error and card.name == "Elias Brandt"
    with pytest.raises(LibraryError):
        lib.update("Elias Brandt", "", {"name": "X"}, {})
    assert (root / "Elias Brandt" / "card.json").read_text(encoding="utf-8") == "{ not json"


def test_update_writes_pretty_json_and_keeps_unknown_keys(root):
    cf = root / "Maya Okafor" / "card.json"
    cf.write_text(json.dumps({"name": "Maya Okafor", "linkedin": "maya-o"}), encoding="utf-8")
    images_before = {p.name: p.read_bytes() for p in (root / "Maya Okafor").glob("*.jpg")}
    lib = Library(root)
    lib.rescan()
    lib.update("Maya Okafor", "", {"name": "Maya O.", "role": "Architect", "tags": "a, b ,,c"}, {})
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
        lib.update("Maya Okafor", "", {"name": "Maya"}, {"back": ("new.jpg", b"data")})


def test_update_can_add_a_missing_side(tmp_path):
    make_image(tmp_path / "R" / "Solo" / "front.jpg")
    lib = Library(tmp_path / "R")
    lib.rescan()
    card = lib.update("Solo", "", {"name": "Solo"}, {"back": ("IMG.PNG", b"png-bytes")}).cards[0]
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


# ---------- several cards for one person ----------


@pytest.fixture
def multi(root):
    """Maya has her first card at the top, plus two card subfolders (one without card.json)."""
    maya = root / "Maya Okafor"
    make_image(maya / "Halcyon 2026" / "front.jpg")
    make_image(maya / "Halcyon 2026" / "back.jpg")
    (maya / "Halcyon 2026" / "card.json").write_text(
        json.dumps({"company": "Halcyon Studio", "role": "Director", "email": "maya@halcyon.example.com"}),
        encoding="utf-8",
    )
    make_image(maya / "Old card" / "scan.png", fmt="PNG")
    (maya / "_scraps").mkdir()
    make_image(maya / "_scraps" / "front.jpg")
    (maya / "empty").mkdir()
    return root


def test_card_subfolders_are_cards_of_one_person(multi):
    person = {p.id: p for p in scan(multi)}["Maya Okafor"]
    assert [c.key for c in person.cards] == ["", "Halcyon 2026", "Old card"]
    data = person.to_json()
    halcyon, old = data["cards"][1], data["cards"][2]
    assert halcyon["company"] == "Halcyon Studio" and halcyon["role"] == "Director"
    assert old["company"] == "Northwind Networks"  # no card.json: uses the person's details
    assert old["front_file"] == "scan.png" and old["has_back"] is False
    assert data["tags"] == ["networking"]


def test_person_with_only_card_subfolders_has_no_main_card(tmp_path):
    make_image(tmp_path / "R" / "Ana Ruiz" / "2025" / "front.jpg")
    person = scan(tmp_path / "R")[0]
    assert [c.key for c in person.cards] == ["2025"]


def test_editing_a_subfolder_card_splits_person_and_card_details(multi):
    lib = Library(multi)
    lib.rescan()
    lib.update(
        "Maya Okafor",
        "Halcyon 2026",
        {
            "name": "Maya Okafor",
            "tags": "design",
            "notes": "Moved to Halcyon",
            "company": "Halcyon",
            "role": "CD",
        },
        {},
    )
    card = json.loads((multi / "Maya Okafor" / "Halcyon 2026" / "card.json").read_text(encoding="utf-8"))
    person = json.loads((multi / "Maya Okafor" / "card.json").read_text(encoding="utf-8"))
    assert card["company"] == "Halcyon" and card["role"] == "CD" and "notes" not in card
    assert person["notes"] == "Moved to Halcyon" and person["tags"] == ["design"]
    assert person["company"] == "Northwind Networks"  # the main card's company is untouched


def test_add_card_makes_a_subfolder(multi):
    lib = Library(multi)
    lib.rescan()
    person, key = lib.add_card(
        "Maya Okafor", "", {"company": "Kestrel Labs", "met_date": "2027-03-01"}, {"front": ("a.HEIC", b"H")}
    )
    assert key == "Kestrel Labs 2027"
    assert (multi / "Maya Okafor" / key / "front.heic").read_bytes() == b"H"
    assert (
        json.loads((multi / "Maya Okafor" / key / "card.json").read_text(encoding="utf-8"))["company"]
        == "Kestrel Labs"
    )
    assert key in [c.key for c in person.cards]
    _, again = lib.add_card("Maya Okafor", "Kestrel Labs 2027", {}, {})
    assert again == "Kestrel Labs 2027 (2)"


def test_delete_one_card_moves_only_its_subfolder(multi):
    lib = Library(multi)
    lib.rescan()
    assert lib.delete("Maya Okafor", "Halcyon 2026") == "Maya Okafor - Halcyon 2026"
    assert (multi / "_deleted" / "Maya Okafor - Halcyon 2026" / "front.jpg").exists()
    assert (multi / "Maya Okafor" / "front.jpg").exists()
    assert [c.key for c in lib.get("Maya Okafor").cards] == ["", "Old card"]


def test_corners_are_saved_in_the_cards_own_card_json(multi):
    lib = Library(multi)
    lib.rescan()
    pts = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
    lib.set_corners("Maya Okafor", "Old card", {"front": pts})
    data = json.loads((multi / "Maya Okafor" / "Old card" / "card.json").read_text(encoding="utf-8"))
    assert data == {"corners": {"front": pts}}
    lib.set_corners("Maya Okafor", "", {"back": pts})
    person = json.loads((multi / "Maya Okafor" / "card.json").read_text(encoding="utf-8"))
    assert person["corners"] == {"back": pts} and person["company"] == "Northwind Networks"
    lib.set_corners("Maya Okafor", "", {"back": None})
    assert "corners" not in json.loads((multi / "Maya Okafor" / "card.json").read_text(encoding="utf-8"))
