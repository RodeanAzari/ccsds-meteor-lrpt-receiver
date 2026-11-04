"""Write the RTL's ROM/coefficient files from the bit-true model, so the model is the only source of the values.

    python scripts/gen_rtl_tables.py          # rewrite the files
    python scripts/gen_rtl_tables.py --check  # exit 1 if any committed file differs (run by make model-test)
"""

from __future__ import annotations

import sys
from pathlib import Path

from model import ddc_fixed as m

ROOT = Path(__file__).resolve().parent.parent


def hex_lines(values: list[int], bits: int) -> str:
    digits = (bits + 3) // 4
    return "".join(f"{v & ((1 << bits) - 1):0{digits}x}\n" for v in values)


def tables() -> dict[Path, str]:
    return {
        ROOT / "rtl/ddc/nco_lut.mem": hex_lines(m.nco_lut().tolist(), m.NCO_BITS),
    }


def main(argv: list[str]) -> int:
    stale = []
    for path, text in tables().items():
        if "--check" in argv:
            if not path.exists() or path.read_text() != text:
                stale.append(path)
        else:
            path.write_text(text)
    for path in stale:
        print(f"stale: {path.relative_to(ROOT)} (run python scripts/gen_rtl_tables.py)", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
