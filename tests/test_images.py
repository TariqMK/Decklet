"""Tests for thumbnails and display copies: made in the cache, originals untouched."""

import cv2
import numpy as np
from conftest import make_image
from PIL import Image

from decklet import images


def test_thumbnail_is_cached_and_original_untouched(tmp_path):
    src = make_image(tmp_path / "P" / "front.png", size=(3000, 1700), fmt="PNG")
    before = src.read_bytes()
    out = images.thumbnail(src, tmp_path / "cache")
    assert out.parent == tmp_path / "cache" / "thumbs"
    with Image.open(out) as im:
        assert max(im.size) == images.THUMB_PX and im.format == "JPEG"
    assert images.thumbnail(src, tmp_path / "cache") == out
    assert src.read_bytes() == before


def test_changed_file_gets_new_thumbnail(tmp_path):
    src = make_image(tmp_path / "front.jpg")
    first = images.thumbnail(src, tmp_path / "c")
    make_image(src, color=(0, 0, 0), size=(400, 220))
    assert images.thumbnail(src, tmp_path / "c") != first


def test_display_file_uses_original_for_jpeg(tmp_path):
    src = make_image(tmp_path / "front.jpg")
    assert images.display_file(src, tmp_path / "c") == src


def test_heic_gets_a_jpeg_display_copy(tmp_path):
    if not images.HEIF_OK:
        return
    src = tmp_path / "front.heic"
    Image.new("RGB", (320, 180), (10, 120, 200)).save(src, "HEIF")
    out = images.display_file(src, tmp_path / "c")
    assert out.suffix == ".jpg" and out.parent == tmp_path / "c" / "full"
    with Image.open(out) as im:
        assert im.size == (320, 180)


# ---------- alignment ----------


def card_photo(path, quad, size=(1200, 900), card=(525, 300), seed=1):
    """A fake photo: a light card with text, in perspective, on a noisy dark desk."""
    rng = np.random.default_rng(seed)
    bg = np.full((size[1], size[0], 3), (60, 50, 40), np.uint8)
    bg = cv2.add(bg, rng.integers(0, 25, bg.shape, dtype=np.uint8))
    face = np.full((card[1], card[0], 3), (230, 225, 210), np.uint8)
    cv2.putText(face, "MAYA", (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 3, (30, 30, 90), 6)
    src = np.float32([[0, 0], [card[0], 0], [card[0], card[1]], [0, card[1]]])
    m = cv2.getPerspectiveTransform(src, np.float32(quad))
    warped = cv2.warpPerspective(face, m, size)
    mask = cv2.warpPerspective(np.full((card[1], card[0]), 255, np.uint8), m, size)
    bg[mask > 0] = warped[mask > 0]
    Image.fromarray(bg).save(path)
    return path


def test_detects_a_tilted_card_in_perspective(tmp_path):
    quad = [[260, 180], [900, 250], [860, 640], [230, 560]]
    src = card_photo(tmp_path / "front.jpg", quad)
    found = images.detect_corners(images.open_upright(src))
    assert np.abs(np.array(found) - np.array(quad) / [1200, 900]).max() < 0.01


def test_card_filling_the_photo_gives_no_corners(tmp_path):
    src = make_image(tmp_path / "front.jpg", size=(700, 400))
    assert images.detect_corners(images.open_upright(src)) is None


def test_front_and_back_come_out_the_same_size(tmp_path):
    front = card_photo(tmp_path / "front.jpg", [[260, 180], [900, 250], [860, 640], [230, 560]])
    back = card_photo(
        tmp_path / "back.jpg", [[100, 100], [700, 120], [690, 470], [90, 440]], size=(900, 700), seed=2
    )
    out = images.aligned_pair(front, back, None, tmp_path / "cache")
    with Image.open(out["front"]) as f, Image.open(out["back"]) as b:
        assert f.size == b.size
        w, h = f.size
        assert 1.5 < w / h < 1.9  # close to the card's 1.75 shape, not the photo's 1.33


def test_back_photographed_upright_is_turned_to_match(tmp_path):
    front = card_photo(tmp_path / "front.jpg", [[200, 200], [900, 200], [900, 600], [200, 600]])
    back = card_photo(
        tmp_path / "back.jpg", [[300, 100], [700, 100], [700, 800], [300, 800]], size=(1000, 900), seed=3
    )
    out = images.aligned_pair(front, back, None, tmp_path / "cache")
    with Image.open(out["back"]) as b:
        assert b.size[0] > b.size[1]


def test_saved_corners_win_over_detection(tmp_path):
    src = card_photo(tmp_path / "front.jpg", [[260, 180], [900, 250], [860, 640], [230, 560]])
    pts = [[0, 0], [0.5, 0], [0.5, 0.25], [0, 0.25]]
    corners, manual = images.face_corners(src, pts, tmp_path / "c")
    assert manual and corners == pts
    out = images.aligned_pair(src, None, {"front": pts}, tmp_path / "c")
    with Image.open(out["front"]) as im:
        assert im.size == (600, 225)


def test_invalid_saved_corners_are_ignored():
    assert images.valid_corners([[0, 0], [1, 0], [1, 1]]) is None
    assert images.valid_corners([[0, 0], [1, 0], [1, 2], [0, 1]]) is None
    assert images.valid_corners("x") is None
