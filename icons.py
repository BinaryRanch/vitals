"""Site icons for Vitals, fetched from the site itself and cached on disk.

No third-party icon service, no tracking pixel, no CDN in the middle: the icon
comes from the origin you are already talking to, over the same network path the
browser used. First request for a host hits the network once, then it is served
from ~/.cache/vitals/icons for a month.

If a site has no icon, we return None and the UI draws a letter tile in the
site's own hash colour. A missing icon is never an error worth showing.
"""
import hashlib
import os
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

CACHE_DIR = os.path.expanduser("~/.cache/vitals/icons")
MAX_BYTES = 96 * 1024
MAX_AGE_S = 30 * 24 * 3600
TIMEOUT = 2.5

# what a browser would accept, most common first
CANDIDATES = ("/favicon.ico", "/favicon.png", "/apple-touch-icon.png")


def _host_of(url):
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return None
        return p.scheme, p.hostname, p.port
    except ValueError:
        return None


def _path_for(host):
    return os.path.join(CACHE_DIR, hashlib.sha1(host.encode()).hexdigest() + ".img")


def _content_type(data):
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"<svg" or b"<svg" in data[:200]:
        return "image/svg+xml"
    return "image/x-icon"


def icon_for(url):
    """Return (bytes, content_type) for the site's icon, or None.

    Cached for 30 days. A stale cache entry is refreshed in place; a failure
    leaves the old one alone rather than blanking a working icon.
    """
    host_bits = _host_of(url)
    if not host_bits:
        return None
    scheme, host, port = host_bits
    cache_key = f"{host}:{port or ''}"
    path = _path_for(cache_key)

    fresh = False
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < MAX_AGE_S:
            fresh = True
        else:
            try:
                with open(path, "rb") as f:
                    cached = f.read()
                _refresh_in_background(scheme, host, port, path)
                return cached, _content_type(cached)
            except OSError:
                pass

    if fresh:
        try:
            with open(path, "rb") as f:
                data = f.read()
            if data:
                return data, _content_type(data)
        except OSError:
            pass

    data = _fetch(scheme, host, port)
    if not data:
        return None
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        pass
    return data, _content_type(data)


def _fetch(scheme, host, port):
    netloc = host if not port else f"{host}:{port}"
    for suffix in CANDIDATES:
        url = f"{scheme}://{netloc}{suffix}"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; Vitals/0.2; local monitor)",
                "Accept": "image/*,*/*;q=0.8"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = r.read(MAX_BYTES)
            if data and len(data) > 40:
                return data
        except (urllib.error.URLError, socket.timeout, OSError, ValueError):
            continue
    return None


def _refresh_in_background(scheme, host, port, path):
    import threading

    def work():
        data = _fetch(scheme, host, port)
        if not data:
            return
        try:
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except OSError:
            pass

    threading.Thread(target=work, daemon=True, name="vitals-icon").start()
