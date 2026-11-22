"""Asks GitHub for the latest Decklet release, only when the user selects the version. Nothing is downloaded or installed."""

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import APP_NAME, REPOSITORY
from ._version import __version__

log = logging.getLogger(__name__)

LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
TIMEOUT = 10  # seconds
USER_AGENT = f"{APP_NAME}/{__version__}"

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_BRANCH = re.compile(r"^v?\d+\.\d+\.\d+-[a-z0-9-]+\.\d+$")


class UpdateError(Exception):
    """Its message is the finished text shown to the user."""


def parse_version(text: str):
    m = _VERSION.match(str(text).strip())
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a > b)


def display_version(v: str = __version__) -> str:
    """'v1.2.0' for releases and branch builds; a dev version like 0.0.0.dev0 shows as v0.0.0-dev."""
    if re.fullmatch(r"\d+\.\d+\.\d+\.dev\d*", v):
        return "v" + v.split(".dev")[0] + "-dev"
    return v if v.startswith("v") else f"v{v}"


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str
    url: str
    notes: str

    @property
    def branch_build(self) -> bool:
        return bool(_BRANCH.match(self.current))

    @property
    def dev_build(self) -> bool:
        return parse_version(self.current) is None and not self.branch_build

    @property
    def newer(self) -> bool:
        return not self.branch_build and not self.dev_build and is_newer(self.latest, self.current)

    @property
    def offers_page(self) -> bool:
        return self.newer or self.dev_build or self.branch_build


def _unreadable() -> UpdateError:
    return UpdateError(f"GitHub sent an answer {APP_NAME} can't read. Try again later.")


def parse_release(data, current: str) -> UpdateInfo:
    if not isinstance(data, dict):
        raise _unreadable()
    tag = data.get("tag_name")
    if not isinstance(tag, str) or parse_version(tag) is None:
        raise _unreadable()
    url = data.get("html_url")
    if not (isinstance(url, str) and url.startswith("https://")):
        url = RELEASES_PAGE
    body = data.get("body")
    notes = body.strip() if isinstance(body, str) else ""
    return UpdateInfo(current=current, latest=display_version(tag.strip()), url=url, notes=notes)


def check(current: str = __version__, opener=urllib.request.urlopen) -> UpdateInfo:
    """One GET to GitHub. Blocks, so callers run it off the UI thread."""
    req = urllib.request.Request(
        LATEST_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    started = time.monotonic()
    try:
        with opener(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        log.info("Update check: api.github.com answered %s", e.code)
        if e.code == 404:
            raise UpdateError(f"No {APP_NAME} releases are published yet.") from e
        if e.code in (403, 429):
            raise UpdateError("GitHub limits how often it can be checked. Try again in an hour.") from e
        raise UpdateError(f"GitHub answered with error {e.code}. Try again later.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", None) or e
        log.info("Update check: can't reach api.github.com: %s", reason)
        raise UpdateError(f"Can't reach GitHub: {reason}. Check the internet connection.") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise _unreadable() from e
    info = parse_release(data, current)
    log.info(
        "Update check: api.github.com answered 200 in %.1f s, latest %s",
        time.monotonic() - started,
        info.latest,
    )
    return info


def summary(info: UpdateInfo) -> tuple[str, str]:
    cur = display_version(info.current)
    if info.branch_build:
        return "This is a test build.", f"You are running {cur}. The latest release is {info.latest}."
    if info.dev_build:
        return "This is a development build.", f"You are running {cur}. The latest release is {info.latest}."
    if info.newer:
        return (
            f"{APP_NAME} {info.latest} is available.",
            f"You have {cur}. Open the release page to download the new version.",
        )
    return f"{APP_NAME} is up to date.", f"{cur} is the latest release."
