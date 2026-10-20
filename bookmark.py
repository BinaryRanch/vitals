#!/usr/bin/env python3
"""Put Vitals in the browser's bookmark bar.

Chromium-family browsers (Brave, Chrome, Chromium) store bookmarks as a JSON
file with an MD5 checksum over a canonical serialisation of every node. If the
checksum does not match, the browser silently falls back to Bookmarks.bak and
the edit disappears, so this tool recomputes it and refuses to write a file it
cannot verify.

Checksum algorithm (components/bookmarks/browser/bookmark_codec.cc):
    for each root folder, in order bookmark_bar, other, synced:
        feed the root itself as a folder node
        then every descendant, depth first, in order
    folder node : id + name (UTF-16LE bytes) + b"folder"
    url node    : id + name (UTF-16LE bytes) + b"url" + url (UTF-8)

Verified by reproducing the stored checksum of a real 13.8 MB profile file.

Safe by construction: refuses while the browser owns the profile, writes through
a temp file with an atomic rename, keeps a timestamped backup, and re-reads the
file it just wrote to confirm the checksum lands.

Usage:
    python3 bookmark.py --install              # add Vitals + Vitals popup
    python3 bookmark.py --install --wait 600   # wait up to 10 min for browser exit
    python3 bookmark.py --status               # what is in the bar right now
    python3 bookmark.py --remove               # take them back out
    python3 bookmark.py --install --profile-dir /path/to/Profile
    python3 bookmark.py --install --dry-run
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import time
import uuid

VITALS_URL = "http://127.0.0.1:8791/"
BOOKMARKLET = (
    "javascript:(function(){window.open('http://127.0.0.1:8791/',"
    "'vitals','width=1500,height=950,menubar=no,toolbar=no,location=no,"
    "status=no');})();void(0);"
)
ROOTS = ("bookmark_bar", "other", "synced")
WINDOWS_EPOCH_OFFSET = 11644473600  # seconds between 1601-01-01 and 1970-01-01


# ---------------------------------------------------------------- checksum
def _u16(s: str) -> bytes:
    return s.encode("utf-16-le")


def _feed_url(h, node) -> None:
    h.update(str(node["id"]).encode())
    h.update(_u16(node.get("name") or ""))
    h.update(b"url")
    h.update((node.get("url") or "").encode("utf-8"))


def _feed_folder(h, node) -> None:
    h.update(str(node["id"]).encode())
    h.update(_u16(node.get("name") or ""))
    h.update(b"folder")


def _walk(h, node) -> None:
    if node.get("type") == "url":
        _feed_url(h, node)
    else:
        _feed_folder(h, node)
        for child in node.get("children", []):
            _walk(h, child)


def checksum(doc) -> str:
    h = hashlib.md5()
    for key in ROOTS:
        root = doc["roots"].get(key)
        if not root:
            continue
        _feed_folder(h, root)
        for child in root.get("children", []):
            _walk(h, child)
    return h.hexdigest()


# ---------------------------------------------------------------- discovery
def candidate_profiles():
    home = os.path.expanduser("~")
    pats = [
        # Flatpak builds keep their profile inside the sandbox.
        f"{home}/.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser/Default",
        f"{home}/.var/app/com.google.Chrome/config/google-chrome/Default",
        f"{home}/.var/app/org.chromium.Chromium/config/chromium/Default",
        # Native builds.
        f"{home}/.config/BraveSoftware/Brave-Browser/Default",
        f"{home}/.config/google-chrome/Default",
        f"{home}/.config/chromium/Default",
        # Chromium-family shells.
        f"{home}/.config/microsoft-edge/Default",
        f"{home}/.config/vivaldi/Default",
    ]
    out = []
    for p in pats:
        if os.path.isfile(os.path.join(p, "Bookmarks")):
            out.append(p)
    return out


def profile_in_use(profile_dir: str) -> bool:
    """True when a browser currently owns this profile.

    Chromium takes a SingletonLock in the user data dir (the parent of the
    profile dir). Reading the bookmarks file under a live browser is pointless:
    the in-memory model overwrites it on the next save.
    """
    user_data_dir = os.path.dirname(profile_dir.rstrip("/"))
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        if os.path.exists(os.path.join(user_data_dir, name)):
            return True
    # Also catch a browser pointed at this profile with an explicit flag.
    needle = os.path.abspath(profile_dir)
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\x00", b" ").decode("utf8", "replace")
        except OSError:
            continue
        if "--type=" in cmd:
            continue
        if needle in cmd and any(b in cmd for b in ("brave", "chrome", "chromium", "edge", "vivaldi")):
            return True
    return False


def max_id(doc) -> int:
    top = 0

    def walk(node):
        nonlocal top
        try:
            top = max(top, int(node.get("id", 0)))
        except (TypeError, ValueError):
            pass
        for child in node.get("children", []):
            walk(child)

    for key in ROOTS:
        if doc["roots"].get(key):
            walk(doc["roots"][key])
    return top


def now_micros() -> str:
    return str(int((time.time() + WINDOWS_EPOCH_OFFSET) * 1_000_000))


def find_ours(doc):
    """Return (vitals_node, bookmarklet_node) currently in the bar, if any."""
    plain = bm = None

    def walk(node):
        nonlocal plain, bm
        if node.get("type") == "url":
            url = node.get("url") or ""
            if url == VITALS_URL:
                plain = node
            elif url.startswith("javascript:") and "8791" in url:
                bm = node
        for child in node.get("children", []):
            walk(child)

    for key in ROOTS:
        if doc["roots"].get(key):
            walk(doc["roots"][key])
    return plain, bm


def make_node(node_id: int, name: str, url: str) -> dict:
    stamp = now_micros()
    return {
        "date_added": stamp,
        "date_last_used": "0",
        "guid": str(uuid.uuid4()),
        "id": str(node_id),
        "name": name,
        "type": "url",
        "url": url,
    }


# ---------------------------------------------------------------- operations
def load(profile_dir):
    path = os.path.join(profile_dir, "Bookmarks")
    with open(path, encoding="utf8") as f:
        raw = f.read()
    return path, raw, json.loads(raw)


def save(path, doc, raw_before) -> None:
    doc["checksum"] = checksum(doc)
    doc.pop("checksum_sha256", None)  # browser rewrites it; absent is valid
    text = json.dumps(doc, indent=3, sort_keys=True, ensure_ascii=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.pre-vitals-{stamp}.bak"
    shutil.copy2(path, backup)
    tmp = f"{path}.vitals.tmp"
    with open(tmp, "w", encoding="utf8") as f:
        f.write(text)
    shutil.copystat(path, tmp)
    os.replace(tmp, path)
    print(f"  backup: {backup}")

    # Verify what actually landed on disk.
    with open(path, encoding="utf8") as f:
        check = json.load(f)
    if checksum(check) != check.get("checksum"):
        raise SystemExit("REFUSING: checksum did not verify after write")
    if len(raw_before) and not check["roots"].get("bookmark_bar"):
        raise SystemExit("REFUSING: bookmark bar missing after write")


def install(profile_dir, dry_run=False, name="Vitals", popup_name="Vitals popup") -> int:
    path, raw, doc = load(profile_dir)
    plain, bm = find_ours(doc)
    next_id = max_id(doc) + 1
    added = []

    if plain is None:
        doc["roots"]["bookmark_bar"].setdefault("children", []).append(
            make_node(next_id, name, VITALS_URL)
        )
        next_id += 1
        added.append(name)
    elif plain.get("name") != name:
        plain["name"] = name
        added.append(f"{name} (renamed)")

    if bm is None:
        doc["roots"]["bookmark_bar"].setdefault("children", []).append(
            make_node(next_id, popup_name, BOOKMARKLET)
        )
        added.append(popup_name)

    if not added:
        print("  already installed, nothing to do")
        return 0

    if dry_run:
        probe = json.loads(raw)
        probe["checksum"] = checksum(doc)
        print(f"  dry run: would add {added} | new checksum {probe['checksum']}")
        return 0

    print(f"  profile: {profile_dir}")
    print(f"  adding: {', '.join(added)}")
    save(path, doc, raw)
    print(f"  checksum: {doc['checksum']} verified on disk")
    return 0


def remove(profile_dir, dry_run=False) -> int:
    path, raw, doc = load(profile_dir)
    plain, bm = find_ours(doc)
    if plain is None and bm is None:
        print("  nothing to remove")
        return 0
    removed = []
    for key in ROOTS:
        root = doc["roots"].get(key)
        if not root:
            continue
        keep = []
        for child in root.get("children", []):
            if child is plain or child is bm:
                removed.append(child.get("name"))
            else:
                keep.append(child)
        root["children"] = keep
    if dry_run:
        print(f"  dry run: would remove {removed}")
        return 0
    save(path, doc, raw)
    print(f"  removed: {removed}")
    return 0


def status(profile_dir) -> int:
    _, _, doc = load(profile_dir)
    plain, bm = find_ours(doc)
    bar = doc["roots"]["bookmark_bar"]
    print(f"  profile : {profile_dir}")
    print(f"  bar     : {len(bar.get('children', []))} items")
    print(f"  Vitals  : {plain.get('name') + ' -> ' + plain['url'] if plain else 'not present'}")
    print(f"  popup   : {bm.get('name') if bm else 'not present'}")
    stored = doc.get("checksum", "")
    good = stored == checksum(doc)
    print(f"  checksum: {'valid' if good else 'MISMATCH'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Install Vitals into the bookmark bar")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--profile-dir", default=None)
    ap.add_argument("--name", default="Vitals")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait", type=int, default=0,
                    help="seconds to wait for the browser to exit before giving up")
    args = ap.parse_args(argv)

    if not (args.install or args.remove or args.status):
        ap.print_help()
        return 2

    profiles = [args.profile_dir] if args.profile_dir else candidate_profiles()
    if not profiles:
        print("no Chromium-family profile found; pass --profile-dir")
        return 1

    targets = []
    for p in profiles:
        if not os.path.isfile(os.path.join(p, "Bookmarks")):
            print(f"  skip {p}: no Bookmarks file")
            continue
        waited = 0
        while profile_in_use(p) and waited < args.wait:
            if waited == 0:
                print(f"  browser is running on {p}; waiting up to {args.wait}s")
            time.sleep(2)
            waited += 2
        if profile_in_use(p):
            print(f"  skip {p}: browser holds the profile lock. Close the browser "
                  f"and re-run, or pass --wait N.")
            continue
        targets.append(p)

    if not targets:
        return 1

    for p in targets:
        if args.status:
            status(p)
        elif args.remove:
            remove(p, args.dry_run)
        else:
            install(p, args.dry_run, name=args.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
