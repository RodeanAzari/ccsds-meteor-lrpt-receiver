"""Side-by-side MSU-MR composite: this receiver's CADUs and SatDump's own decode of the same recording.

    satdump meteor_m2-x_lrpt cadu <ours/cadus.bin> <ours_dir>   # SatDump 1.2.2 makes the images from our CADUs
    PYTHONPATH=. python scripts/msu_mr_compare.py <ours_dir> <satdump_dir> <out.jpg>

Both are SatDump's `msu_mr_rgb_MSA_corrected_map.png`, rotated 180° so north is up (the evening passes run south to
north), scaled to 30% and top-aligned: after the rotation the top is the end of the pass, where both decodes stop
within a few frames of each other, so rows line up from the top. Labels give each image's line count.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COMPOSITE = "MSU-MR/msu_mr_rgb_MSA_corrected_map.png"
SCALE, GAP, HEADER = 0.3, 24, 40


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    full = [Image.open(Path(d) / COMPOSITE).convert("RGB").rotate(180) for d in argv[:2]]
    small = [im.resize((round(im.width * SCALE), round(im.height * SCALE)), Image.LANCZOS) for im in full]
    out = Image.new("RGB", (small[0].width + GAP + small[1].width, max(s.height for s in small) + HEADER), "white")
    draw, font = ImageDraw.Draw(out), ImageFont.load_default(size=24)
    labels = ["This receiver, RTL on the Arty", "SatDump 1.2.2, same recording"]
    x = 0
    for im, s, label in zip(full, small, labels, strict=True):
        out.paste(s, (x, HEADER))
        draw.text((x + 8, 6), f"{label}: {im.height:,} lines", fill="black", font=font)
        x += s.width + GAP
    out.save(argv[2], quality=85)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
