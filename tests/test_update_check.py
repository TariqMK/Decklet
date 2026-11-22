"""Tests for the manual update check, with the network stubbed out."""

import io
import json
import urllib.error

import pytest

from decklet import update_check as uc


def test_parse_and_compare_as_numbers():
    assert uc.parse_version("v1.2.3") == (1, 2, 3) and uc.parse_version(" 0.10.0 ") == (0, 10, 0)
    assert uc.parse_version("0.0.0.dev0") is None and uc.parse_version("v1.5.0-x.1") is None
    assert uc.is_newer("v0.10.0", "0.9.0") and not uc.is_newer("v0.9.0", "0.10.0")
    assert not uc.is_newer("v1.0.0", "0.0.0.dev0")


def test_display_version():
    assert uc.display_version("0.0.0.dev0") == "v0.0.0-dev"
    assert uc.display_version("1.2.0") == "v1.2.0"
    assert uc.display_version("1.5.0-new-sync.1") == "v1.5.0-new-sync.1"


def release(tag="v1.4.0", url="https://github.com/TariqMK/Decklet/releases/tag/v1.4.0", body=" notes "):
    return {"tag_name": tag, "html_url": url, "body": body}


@pytest.mark.parametrize(
    "current,headline,offers",
    [
        ("1.3.0", "Decklet v1.4.0 is available.", True),
        ("1.4.0", "Decklet is up to date.", False),
        ("1.10.0", "Decklet is up to date.", False),
        ("0.0.0.dev0", "This is a development build.", True),
        ("1.5.0-new-sync.1", "This is a test build.", True),
    ],
)
def test_cases(current, headline, offers):
    info = uc.parse_release(release(), current)
    assert uc.summary(info)[0] == headline and info.offers_page == offers
    assert info.notes == "notes"


def test_non_https_or_missing_url_falls_back_to_releases_page():
    assert uc.parse_release(release(url="http://evil"), "1.0.0").url == uc.RELEASES_PAGE
    assert uc.parse_release({"tag_name": "v1.0.0"}, "1.0.0").url == uc.RELEASES_PAGE


@pytest.mark.parametrize("data", [[], {"tag_name": 5}, {"tag_name": "latest"}])
def test_unreadable_release(data):
    with pytest.raises(uc.UpdateError, match="can't read"):
        uc.parse_release(data, "1.0.0")


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_check_sends_only_the_two_headers():
    seen = {}

    def opener(req, timeout):
        seen.update(headers=dict(req.header_items()), url=req.full_url, timeout=timeout)
        return FakeResp(json.dumps(release()).encode())

    info = uc.check("1.3.0", opener=opener)
    assert info.newer and seen["url"] == uc.LATEST_URL and seen["timeout"] == 10
    assert set(seen["headers"]) == {"User-agent", "Accept"}


def http_error(code):
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)

    return opener


@pytest.mark.parametrize(
    "opener,message",
    [
        (http_error(404), "No Decklet releases are published yet."),
        (http_error(403), "GitHub limits how often it can be checked. Try again in an hour."),
        (http_error(429), "GitHub limits how often it can be checked. Try again in an hour."),
        (http_error(500), "GitHub answered with error 500. Try again later."),
    ],
)
def test_http_errors(opener, message):
    with pytest.raises(uc.UpdateError) as e:
        uc.check("1.0.0", opener=opener)
    assert str(e.value) == message


def test_connection_error_and_bad_json():
    def offline(req, timeout):
        raise urllib.error.URLError("nodename nor servname provided")

    with pytest.raises(uc.UpdateError, match="Can't reach GitHub: nodename"):
        uc.check("1.0.0", opener=offline)
    with pytest.raises(uc.UpdateError, match="can't read"):
        uc.check("1.0.0", opener=lambda r, timeout: FakeResp(b"<html>"))
