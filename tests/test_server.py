"""Tests for the local API: access guard, card listing and editing over HTTP, and the bug report URL."""

import io
import json
from urllib.parse import parse_qs, urlparse

import pytest

from decklet import paths
from decklet.server import Backend, create_app, report_url


@pytest.fixture
def client(root, data_dir):
    backend = Backend(data_dir)
    backend.set_root(root)
    app = create_app(backend)
    c = app.test_client()
    c.backend = backend
    c.h = {"X-Decklet-Token": backend.token}
    return c


def test_api_needs_token_and_local_host(client):
    assert client.get("/api/cards").status_code == 403
    assert client.get("/api/cards", headers=client.h).status_code == 200
    assert client.get("/api/cards", headers=client.h, base_url="http://evil.example").status_code == 403


def test_page_has_token(client):
    html = client.get("/").get_data(as_text=True)
    assert client.backend.token in html and "__DECKLET_TOKEN__" not in html


def test_list_and_images(client):
    data = client.get("/api/cards", headers=client.h).get_json()
    assert [c["name"] for c in data["cards"]] == ["Elias Brandt", "Maya Okafor"]
    r = client.get("/media/thumb/front/Maya%20Okafor")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"
    assert client.get("/media/full/back/Elias%20Brandt").mimetype == "image/png"
    assert client.get("/media/full/back/..%2F..%2Fetc").status_code == 404
    assert client.get("/media/full/side/Maya%20Okafor").status_code == 404


def test_add_edit_delete_round_trip(client, root):
    client.get("/api/cards", headers=client.h)
    r = client.post(
        "/api/cards",
        headers=client.h,
        content_type="multipart/form-data",
        data={
            "details": json.dumps({"name": "Tom Hale", "tags": ["coffee"]}),
            "front": (io.BytesIO(b"JPEGDATA"), "photo.JPG"),
        },
    )
    assert r.status_code == 200, r.get_json()
    assert (root / "Tom Hale" / "front.jpg").read_bytes() == b"JPEGDATA"
    r = client.put(
        "/api/cards/Tom%20Hale",
        headers=client.h,
        content_type="multipart/form-data",
        data={"details": json.dumps({"name": "Tom Hale", "role": "Head Roaster"})},
    )
    assert r.get_json()["card"]["role"] == "Head Roaster"
    r = client.put(
        "/api/cards/Tom%20Hale",
        headers=client.h,
        content_type="multipart/form-data",
        data={"details": "{}", "front": (io.BytesIO(b"NEW"), "x.jpg")},
    )
    assert r.status_code == 400 and "never replaces" in r.get_json()["error"]
    assert (root / "Tom Hale" / "front.jpg").read_bytes() == b"JPEGDATA"
    assert client.delete("/api/cards/Tom%20Hale", headers=client.h).status_code == 200
    assert (root / "_deleted" / "Tom Hale" / "card.json").exists()


def test_missing_root_reports_not_ok(client, root):
    root.rename(root.parent / "gone")
    assert client.get("/api/cards", headers=client.h).get_json()["root_ok"] is False


def test_settings_keep_relative_and_absolute_root(client, root, data_dir):
    s = json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))
    assert s["root"] == "../Business Cards" and s["root_abs"] == str(root.resolve())
    assert paths.resolve_root(s) == root.resolve()


def test_report_url_has_only_version_and_os():
    url = report_url("v0.0.0-dev", "macOS 26.1")
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://github.com/TariqMK/Decklet/issues/new?")
    assert q == {"template": ["bug.yml"], "version": ["v0.0.0-dev"], "os": ["macOS 26.1"]}
    assert "macOS+26.1" in url or "macOS%2026.1" in url


def test_open_only_allows_known_pages(client, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))
    assert client.post("/api/open", headers=client.h, json={"what": "file:///etc/passwd"}).status_code == 400
    client.post("/api/open", headers=client.h, json={"what": "report"})
    assert opened and opened[0].startswith("https://github.com/TariqMK/Decklet/issues/new")


def test_local_server_binds_without_reverse_dns(client, monkeypatch):
    import socket

    from decklet.server import make_local_server

    def no_dns(*a, **k):
        raise AssertionError("reverse DNS lookup")

    monkeypatch.setattr(socket, "getfqdn", no_dns)
    srv = make_local_server(create_app(client.backend))
    try:
        assert srv.server_address[0] == "127.0.0.1" and srv.server_port > 0
    finally:
        srv.server_close()
