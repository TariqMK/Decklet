"""Shared test fixtures: a temporary data folder and a cards folder with sample person folders."""

import json

import pytest
from PIL import Image


def make_image(path, color=(200, 160, 100), size=(350, 200), fmt=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, fmt)
    return path


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "Decklet-data"
    monkeypatch.setenv("DECKLET_DATA_DIR", str(d))
    return d


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "Business Cards"
    make_image(r / "Maya Okafor" / "front.jpg")
    make_image(r / "Maya Okafor" / "back.jpg")
    (r / "Maya Okafor" / "card.json").write_text(
        json.dumps({"name": "Maya Okafor", "company": "Northwind Networks", "tags": ["networking"]}),
        encoding="utf-8",
    )
    make_image(r / "Elias Brandt" / "FRONT.JPG")
    make_image(r / "Elias Brandt" / "Back.png", fmt="PNG")
    return r
