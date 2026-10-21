#!/usr/bin/env python3
"""
bar_widget.py — one line of JSON for a status bar.

Omarchy's shell, Waybar, and anything else that speaks the same convention can
run this on an interval and render the result. It is the cheapest possible
frontend for Vitals: no QML, no websocket, no plugin manifest.

  {"text": "97%", "tooltip": "6.9 cores in leaked browsers...", "class": "hot"}

Usage:
  python3 tools/bar_widget.py                  # machine total
  python3 tools/bar_widget.py --workload brave # one workload
  python3 tools/bar_widget.py --url http://127.0.0.1:8791
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


def fetch(url):
    with urllib.request.urlopen(url + "/api/snapshot", timeout=3) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8791")
    ap.add_argument("--workload", default="", help="substring of a workload name")
    args = ap.parse_args()

    try:
        snap = fetch(args.url)
    except (urllib.error.URLError, OSError, ValueError):
        # a bar widget must never be the reason a session looks broken
        print(json.dumps({"text": "vitals ?", "tooltip": "Vitals is not responding", "class": "offline"}))
        return 0

    if args.workload:
        match = [w for w in snap["workloads"] if args.workload.lower() in w["name"].lower()]
        if not match:
            print(json.dumps({"text": "?", "tooltip": f"no workload matching {args.workload}",
                              "class": "offline"}))
            return 0
        w = max(match, key=lambda x: x["cpu"])
        text = f'{w["cpu"]:.1f}c'
        tip = [f'{w["name"]}: {w["cpu"]:.2f} cores ({w["pct"]:.0f}%), {w["procs"]} procs']
        if w.get("verdict"):
            tip.append(w["verdict"])
        for t in (w.get("tabs") or [])[:3]:
            tip.append(f'  {t["title"][:40]} — {t["task_pct"]:.1f}% page work')
        klass = "hot" if w["pct"] > 40 else "warn" if w["pct"] > 15 else "ok"
        if "leaked" in (w.get("flags") or []):
            klass = "leaked"
        print(json.dumps({"text": text, "tooltip": "\n".join(tip), "class": klass}))
        return 0

    pct = snap["total_pct"]
    klass = "hot" if pct > 80 else "warn" if pct > 50 else "ok"
    tip = [f'{snap["total_busy"]:.2f} of {snap["cores"]} cores ({pct}%)']
    for w in snap["workloads"][:5]:
        tip.append(f'  {w["name"][:28]} {w["cpu"]:.2f}c')
    flagged = [w for w in snap["workloads"] if w.get("flags")]
    for w in flagged:
        tip.append(f'  ! {w["name"]}: {", ".join(w["flags"])}')
    print(json.dumps({"text": f"{pct}%", "tooltip": "\n".join(tip), "class": klass}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
