#!/usr/bin/env python3
"""
make_icons.py — turn one source mark into every icon size the surfaces need.

One file in, the full set out, because the alternative is discovering three
weeks later that the forge unfurl, the GitHub avatar, and the browser tab are
all still showing generated identicons.

  python3 tools/make_icons.py brand/mark.svg
  python3 tools/make_icons.py brand/mark.png --out-dir icons

Produces, in the output directory:
  icon-16.png  icon-32.png  icon-48.png  icon-180.png  icon-256.png
  icon-512.png icon-1024.png  favicon.ico  (16/32/48 multi-size)

Where each one goes:
  1024 + 512   store listings, social cards, press kit
  512          Forgejo org avatar, GitHub org avatar
  180          apple-touch-icon (iOS home screen)
  16/32/48     favicon.ico, browser tabs, bookmarks
"""

import argparse
import os
import shutil
import subprocess
import sys

from PIL import Image

RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS

SIZES = [16, 32, 48, 180, 256, 512, 1024]
ICO_SIZES = [16, 32, 48, 64]


def load_square(path, size=1024):
    """Return a square RGBA image, rendering SVG at high resolution first."""
    ext = os.path.splitext(path)[1].lower()
    tmp = None
    if ext == ".svg":
        tmp = f"/tmp/.icon-src-{os.getpid()}.png"
        if shutil.which("inkscape"):
            subprocess.run(["inkscape", path, "--export-type=png", f"--export-filename={tmp}",
                            f"--export-width={size}", f"--export-height={size}"],
                           check=True, capture_output=True)
        else:
            subprocess.run(["convert", "-background", "none", "-density", "600", path,
                            "-resize", f"{size}x{size}", tmp], check=True, capture_output=True)
        path = tmp
    img = Image.open(path).convert("RGBA")
    if tmp:
        os.unlink(tmp)
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    return canvas.resize((size, size), RESAMPLE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="square-ish .svg or .png/.jpg mark")
    ap.add_argument("--out-dir", default="icons")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        sys.exit(f"no such file: {args.source}")

    master = load_square(args.source)
    os.makedirs(args.out_dir, exist_ok=True)
    for size in SIZES:
        out = os.path.join(args.out_dir, f"icon-{size}.png")
        master.resize((size, size), RESAMPLE).save(out)
        print(f"  {out}")

    ico_path = os.path.join(args.out_dir, "favicon.ico")
    master.resize((256, 256), RESAMPLE).save(ico_path, sizes=[(s, s) for s in ICO_SIZES])
    print(f"  {ico_path}  ({', '.join(str(s) for s in ICO_SIZES)})")

    print(f"\n{len(SIZES) + 1} files in {args.out_dir}/")
    print("upload icon-512.png as the org avatar on both forges; the rest ship with the app")


if __name__ == "__main__":
    main()
