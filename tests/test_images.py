"""Tests for thumbnails and display copies: made in the cache, originals untouched."""

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
