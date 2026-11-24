"""MSU-MR false-colour image from this receiver's own chain, no SatDump: gs-image's per-channel PNGs.

    build/gs-Release/gs-image <rx>/packets.bin <dir>        # board -> gs-rx -> gs-image
    PYTHONPATH=. python scripts/msu_mr_own.py <dir> <out.jpg>

The usual LRPT "221" composite: red and green from channel 2 (near infrared, 0.7-1.1 um), blue from channel 1
(visible, 0.5-0.7 um), pixel values as decoded, no stretch, no map. Rotated 180° so north is up (the evening passes
run south to north) and scaled to 30%, as scripts/msu_mr_compare.py does.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

SCALE = 0.3


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    ch1, ch2 = (Image.open(Path(argv[0]) / f"MSU-MR-{c}.png").convert("L") for c in (1, 2))
    if ch1.size != ch2.size:
        print(f"channel sizes differ: {ch1.size} {ch2.size}", file=sys.stderr)
        return 1
    rgb = Image.merge("RGB", (ch2, ch2, ch1)).rotate(180)
    rgb.resize((round(rgb.width * SCALE), round(rgb.height * SCALE)), Image.LANCZOS).save(argv[1], quality=85)
    print(f"{argv[1]}: {rgb.width} x {rgb.height} source pixels")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
