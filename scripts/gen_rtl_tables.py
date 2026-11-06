"""Write the RTL's ROM/coefficient files from the bit-true model, so the model is the only source of the values.

    python scripts/gen_rtl_tables.py          # rewrite the files
    python scripts/gen_rtl_tables.py --check  # exit 1 if any committed file differs (run by make model-test)
"""

from __future__ import annotations

import sys
from pathlib import Path

from model import ddc_fixed as m
from model import framesync_fixed, rrc_fixed
from model.receiver import RxConfig

ROOT = Path(__file__).resolve().parent.parent


def hex_lines(values: list[int], bits: int) -> str:
    digits = (bits + 3) // 4
    return "".join(f"{v & ((1 << bits) - 1):0{digits}x}\n" for v in values)


def pattern_words() -> list[int]:
    """Encoded-ASM patterns, one word per phase hypothesis (framesync_fixed.patterns() order): bit k set = +1."""
    return [sum(1 << k for k, s in enumerate(p) if s > 0) for p in framesync_fixed.patterns().tolist()]


def tables() -> dict[Path, str]:
    return {
        ROOT / "rtl/ddc/nco_lut.mem": hex_lines(m.nco_lut().tolist(), m.NCO_BITS),
        # s18 taps at the default RxConfig (1.024 MS/s, /4); the RTL's NTAPS must equal RxConfig.comp_taps
        ROOT / "rtl/ddc/comp_fir_taps.mem": hex_lines(m.comp_taps(RxConfig()).tolist(), m.COMP_FRAC + 1),
        # s18 RRC taps (57 at the default RxConfig); the RTL's NTAPS must equal their count
        ROOT / "rtl/sync/rrc_taps.mem": hex_lines(rrc_fixed.taps(RxConfig()).tolist(), rrc_fixed.RRC_FRAC + 1),
        # 52-symbol encoded ASM under the 4 hypotheses; the RTL's PATTERN_LEN must equal the length
        ROOT / "rtl/fec/asm_patterns.mem": hex_lines(pattern_words(), framesync_fixed.patterns().shape[1]),
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
