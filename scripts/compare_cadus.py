#!/usr/bin/env python3
"""Compare a SatDump .cadu file against truth on the 892 data bytes per frame (signal-spec.md, gs-diff).

Usage: python scripts/compare_cadus.py <satdump.cadu> <truth.cadu>
"""

from __future__ import annotations

import sys
from pathlib import Path

FRAME = 1024
DATA = slice(4, 4 + 892)


def frames(path: Path) -> list[bytes]:
    raw = path.read_bytes()
    if len(raw) % FRAME:
        raise SystemExit(f"{path}: size {len(raw)} is not a whole number of 1024-byte frames")
    return [raw[i : i + FRAME] for i in range(0, len(raw), FRAME)]


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    got = frames(Path(sys.argv[1]))
    truth = {f[DATA] for f in frames(Path(sys.argv[2]))}
    matched = sum(f[DATA] in truth for f in got)
    print(f"{len(got)} frames decoded, {matched} match truth on the data bytes, {len(got) - matched} differ")
    print(f"{len(truth)} frames in truth")
    return 0 if matched == len(got) and got else 1


if __name__ == "__main__":
    raise SystemExit(main())
