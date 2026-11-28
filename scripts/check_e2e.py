"""End-to-end check of a running Decklet: page and fonts, token and host guard, scan rules, images, Add card,
Edit, adding a missing side, Add card for a person, Adjust corners, Delete to _deleted and the update check,
on made-up sample cards.

It drives the app through the same local API the window uses and checks each step's effect on disk, not
only the reply. It only touches the sample cards it makes in the work folder. Standard library only, so it
runs on any test machine.

Usage:
  1. Make a new, empty folder for the sample cards.
  2. Point Decklet at it before starting: write settings.json in Decklet-data beside the app:
       {"root": "", "root_abs": "<that folder>"}
  3. Start Decklet (source or a build).
  4. Find the port it listens on:
       macOS:   lsof -nP -a -p <pid> -iTCP -sTCP:LISTEN
       Linux:   ss -ltnpH | grep '"Decklet"'
       Windows: (Get-NetTCPConnection -State Listen -OwningProcess (Get-Process Decklet).Id).LocalPort
  5. python scripts/check_e2e.py --url http://127.0.0.1:<port> --work <that folder>
     Add --offline to skip the update check, which contacts GitHub.
"""

import argparse
import hashlib
import json
import re
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from pathlib import Path

# --- Fill in for this app ----------------------------------------------------------------------------
APP_NAME = "Decklet"
FONT = "inter-latin-400-normal.woff2"  # one bundled font file
# -----------------------------------------------------------------------------------------------------

failures = []
TOKEN = ""


def check(name, ok, detail=""):
    """Print PASS or FAIL for one step and remember failures."""
    print(("PASS " if ok else "FAIL ") + name + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def request(path, method="GET", body=None, headers=None, token=True, timeout=120):
    """Call the app. Returns (status, content type, raw bytes)."""
    h = dict(headers or {})
    if token:
        h["X-Decklet-Token"] = TOKEN
    req = urllib.request.Request(args.url.rstrip("/") + path, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def call(path, method="GET", body=None, **kw):
    """Call the JSON API. body: dict (sent as JSON). Returns (status, parsed JSON or text)."""
    data, headers = None, {}
    if body is not None:
        data, headers = json.dumps(body).encode(), {"Content-Type": "application/json"}
    status, _, raw = request(path, method, data, headers, **kw)
    text = raw.decode("utf-8", "replace")
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def form(path, method, details, images=None, label=None):
    """Send the Add card / Edit form the way the page does: multipart with details JSON and image files."""
    boundary = uuid.uuid4().hex
    parts = [("details", None, json.dumps(details).encode())]
    if label is not None:
        parts.append(("label", None, label.encode()))
    for side, (fn, data) in (images or {}).items():
        parts.append((side, fn, data))
    body = b""
    for name, fn, data in parts:
        disp = f'form-data; name="{name}"' + (f'; filename="{fn}"' if fn else "")
        ctype = "Content-Type: image/png\r\n" if fn else ""
        body += f"--{boundary}\r\nContent-Disposition: {disp}\r\n{ctype}\r\n".encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    status, _, raw = request(path, method, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        return status, json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def q(person, card=""):
    return "?" + urllib.parse.urlencode({"p": person, "c": card})


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def card_png(seed):
    """A made-up card photo: a light card with dark 'text' lines on a dark table, so corners can be found."""
    w, h, x0, y0, x1, y1 = 640, 420, 80 + seed * 3, 70, 560 - seed * 2, 350
    shade = 200 + seed * 7 % 50
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            if x0 <= x < x1 and y0 <= y < y1:
                line = (y - y0) % 40 < 6 and x0 + 40 <= x < x1 - 120 + seed * 5
                row += bytes((40, 40, 50) if line else (shade, shade - 5, shade - 15))
            else:
                row += bytes((25, 30 + seed, 35))
        rows.append(bytes(row))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))


def details(**kw):
    """A full form, as the page sends it: every field, blank unless given."""
    keys = ("name", "tags", "notes", "met_at", "met_date", "company", "role", "email", "phone", "website",
            "address")
    out = {k: "" for k in keys}
    out["tags"] = []
    out.update(kw)
    return out


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--url", required=True, help="Base URL of the running app")
parser.add_argument("--work", required=True, help="The new, empty cards folder Decklet was started with")
parser.add_argument("--offline", action="store_true", help="Skip the update check (it contacts GitHub)")
args = parser.parse_args()

work = Path(args.work)
if not work.is_dir() or any(work.iterdir()):
    sys.exit(f"Work folder must exist and be empty: {work}")
print(f"Work folder: {work}")

# --- App checks ---------------------------------------------------------------------------------------

# Page, token and guard
status, ctype, raw = request("/", token=False)
page = raw.decode("utf-8", "replace")
m = re.search(r'name="decklet-token" content="([^"]+)"', page)
check("UI page loads", status == 200 and f"<title>{APP_NAME}" in page and "text/html" in ctype, status)
check("Page carries a per-launch token", bool(m) and m.group(1) != "__DECKLET_TOKEN__")
TOKEN = m.group(1) if m else ""
status, _, _ = request(f"/fonts/{FONT}", token=False)
check("Bundled font loads", status == 200, status)
status, _ = call("/api/state", token=False)
check("API refuses a call without the token", status == 403, status)
status, _, _ = request("/", headers={"Host": "attacker.example"}, token=False)
check("Server refuses another host name", status == 403, status)
status, st = call("/api/state")
ok = status == 200 and isinstance(st, dict)
check("State: app name", ok and st.get("app") == APP_NAME, st)
check("State: cards folder is the work folder", ok and st.get("root_ok")
      and Path(st.get("root", "")).resolve() == work.resolve(), st)
print(f"INFO version {st.get('version') if ok else '?'}")

# Sample cards on disk, the way a user makes them by hand
ada, ben, cara = work / "Ada Example", work / "Ben Sample", work / "Cara Test"
second = cara / "Second Job"
for folder in (ada, ben, cara, second, work / "_archive", work / ".hidden"):
    folder.mkdir()
(ada / "Front.PNG").write_bytes(card_png(1))
(ada / "BACK.png").write_bytes(card_png(2))
(ben / "photo.png").write_bytes(card_png(3))
(cara / "a.png").write_bytes(card_png(4))
(cara / "b.png").write_bytes(card_png(5))
(second / "front.png").write_bytes(card_png(6))
(work / "_archive" / "front.png").write_bytes(card_png(7))
(cara / "card.json").write_text(json.dumps({"name": "Cara Test", "company": "Example Ltd",
                                            "x_custom": {"kept": True}}, indent=2), encoding="utf-8")
originals = {p: sha(p) for p in work.rglob("*.png") if p.is_file()}
originals.update({p: sha(p) for p in work.rglob("*.PNG") if p.is_file()})

# Scan
status, res = call("/api/cards")
people = {p["id"]: p for p in res.get("cards", [])} if status == 200 and isinstance(res, dict) else {}
check("Scan finds the three person folders only", sorted(people) == ["Ada Example", "Ben Sample", "Cara Test"],
      sorted(people))
a = people.get("Ada Example", {}).get("cards", [{}])[0]
check("Front/back names in any case", a.get("front_file") == "Front.PNG" and a.get("back_file") == "BACK.png", a)
b = people.get("Ben Sample", {}).get("cards", [{}])[0]
check("One image is the front", b.get("has_front") and not b.get("has_back"), b)
c = people.get("Cara Test", {})
c_main = next((x for x in c.get("cards", []) if x["key"] == ""), {})
check("Two unnamed images: alphabetical front, back", c_main.get("front_file") == "a.png"
      and c_main.get("back_file") == "b.png", c_main)
check("Card subfolder is a second card", sorted(x["key"] for x in c.get("cards", [])) == ["", "Second Job"], c)
check("card.json details are read", c.get("name") == "Cara Test" and c_main.get("company") == "Example Ltd", c)

# Images
for kind in ("thumb", "full", "original"):
    for side in ("front", "back"):
        status, ctype, raw = request(f"/media/{kind}/{side}/{urllib.parse.quote('Ada Example')}?c=", token=False)
        check(f"Image {kind} {side}", status == 200 and ctype.startswith("image/") and len(raw) > 1000,
              f"{status} {ctype} {len(raw)}")
status, ctype, _ = request(f"/media/full/front/{urllib.parse.quote('Cara Test')}?c=Second%20Job", token=False)
check("Image of a card subfolder", status == 200 and ctype.startswith("image/"), status)
status, _, _ = request(f"/media/full/back/{urllib.parse.quote('Ben Sample')}?c=", token=False)
check("Missing side gives 404", status == 404, status)

# Add card (new person)
front_new, back_new = card_png(8), card_png(9)
status, res = form("/api/cards", "POST",
                   details(name="Dee Demo", company="Sample Co", email="dee@example.com", tags=["demo"]),
                   {"front": ("IMG_0001.png", front_new), "back": ("IMG_0002.png", back_new)})
dee = work / "Dee Demo"
check("Add card replies", status == 200, res)
check("Add card makes the folder", dee.is_dir())
check("Add card copies photos as front/back", (dee / "front.png").is_file() and (dee / "back.png").is_file()
      and sha(dee / "front.png") == hashlib.sha256(front_new).hexdigest()
      and sha(dee / "back.png") == hashlib.sha256(back_new).hexdigest())
dj = read_json(dee / "card.json") if (dee / "card.json").is_file() else {}
check("Add card writes card.json", dj.get("name") == "Dee Demo" and dj.get("email") == "dee@example.com"
      and dj.get("tags") == ["demo"], dj)
status, res = form("/api/cards", "POST", details(name="Dee Demo"))
check("Same name gets ' (2)'", status == 200 and (work / "Dee Demo (2)").is_dir(), res)
status, res = form("/api/cards", "POST", details(name=""))
check("Add card without a name is refused", status == 400, res)

# Edit
status, res = form("/api/card" + q("Cara Test"), "PUT",
                   details(name="Cara Test", company="Example Ltd", notes="Met at the sample fair"))
cj = read_json(cara / "card.json")
check("Edit replies", status == 200, res)
check("Edit writes card.json", cj.get("notes") == "Met at the sample fair", cj)
check("Edit keeps unknown keys", cj.get("x_custom") == {"kept": True}, cj)
check("Edit never renames the folder", cara.is_dir())
status, res = form("/api/card" + q("Ada Example"), "PUT", details(name="Ada Example"),
                   {"front": ("new.png", card_png(10))})
check("Edit refuses to replace an image", status == 400, res)
status, res = form("/api/card" + q("Ben Sample"), "PUT", details(name="Ben Sample"),
                   {"back": ("back.png", card_png(11))})
check("Edit adds a missing side", status == 200 and (ben / "back.png").is_file(), res)

# Broken card.json is never overwritten
broken = work / "Eve Broken"
broken.mkdir()
(broken / "front.png").write_bytes(card_png(12))
(broken / "card.json").write_text("{ not json", encoding="utf-8")
call("/api/cards")
status, res = form("/api/card" + q("Eve Broken"), "PUT", details(name="Eve Broken"))
check("Broken card.json: Edit refused, file kept", status == 400
      and (broken / "card.json").read_text(encoding="utf-8") == "{ not json", res)

# Add card for a person
status, res = form("/api/card" + q("Dee Demo"), "POST", details(name="Dee Demo", company="Next Co"),
                   {"front": ("x.png", card_png(13))}, label="New Role")
sub = dee / "New Role"
check("Add card for a person makes a subfolder", status == 200 and (sub / "front.png").is_file()
      and read_json(sub / "card.json").get("company") == "Next Co", res)

# Adjust corners
status, res = call("/api/corners" + q("Ada Example"))
check("Corners found for both sides", status == 200 and isinstance(res, dict)
      and all(len(res.get(s, {}).get("corners", [])) == 4 for s in ("front", "back")), res)
if status == 200 and isinstance(res, dict) and res.get("front"):
    auto = res["front"]["auto"]
    check("Automatic corners are inside the card, not the whole photo",
          auto != [[0, 0], [1, 0], [1, 1], [0, 1]] and 0.05 < auto[0][0] < 0.3, auto)
manual = [[0.1, 0.1], [0.9, 0.12], [0.88, 0.9], [0.12, 0.88]]
status, res = call("/api/corners" + q("Ada Example"), "PUT", {"front": manual})
aj = read_json(ada / "card.json") if (ada / "card.json").is_file() else {}
check("Hand-placed corners saved in card.json", status == 200
      and aj.get("corners", {}).get("front") == manual, aj)
status, ctype, _ = request(f"/media/full/front/{urllib.parse.quote('Ada Example')}?c=", token=False)
check("Straightened image with hand-placed corners", status == 200 and ctype.startswith("image/"), status)
status, res = call("/api/corners" + q("Ada Example"), "PUT", {"front": None})
aj = read_json(ada / "card.json")
check("Automatic again removes the corners", status == 200 and "corners" not in aj, aj)

# Delete
status, res = call("/api/card" + q("Cara Test", "Second Job"), "DELETE")
moved = work / "_deleted" / "Cara Test - Second Job"
check("Delete a card subfolder moves only it", status == 200 and moved.is_dir() and not second.exists()
      and cara.is_dir(), res)
status, res = call("/api/card" + q("Dee Demo"), "DELETE")
check("Delete a person moves the whole folder", status == 200 and not dee.exists()
      and (work / "_deleted" / "Dee Demo" / "New Role" / "front.png").is_file(), res)
status, res = call("/api/cards")
ids = sorted(p["id"] for p in res.get("cards", [])) if isinstance(res, dict) else []
check("Deleted cards leave the gallery", "Dee Demo" not in ids and "_deleted" not in ids, ids)

# No image file changed
for p, h in originals.items():
    now = p if p.exists() else moved / p.name if p.parent == second else None
    if now is None or not now.exists() or sha(now) != h:
        check(f"Image unchanged: {p.relative_to(work)}", False, "changed or missing")
check("All sample images unchanged", not any(f.startswith("Image unchanged") for f in failures))

# Update check
if not args.offline:
    status, res = call("/api/update-check", "POST")
    check("Update check reaches GitHub", status == 200 and isinstance(res, dict) and res.get("headline"), res)
    if status == 200 and isinstance(res, dict):
        print(f"INFO update check: {res.get('headline')}")
# -----------------------------------------------------------------------------------------------------

print(f'RESULT: {"FAIL" if failures else "PASS"} ({len(failures)} failed)')
sys.exit(1 if failures else 0)
