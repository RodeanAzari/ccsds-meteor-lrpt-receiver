"""Turn an out-of-context Vivado run (syn/synth_ooc.tcl) into data/results/synth_<top>.csv.

    python -m analysis.synth_report <top>      (run by make synth-ooc TOP=<top>)

One row per hierarchy instance from utilization_hier.rpt (LUTs, FFs, RAMB36/18, DSPs), plus the post-route
timing (WNS, WHS, failing endpoints) from timing_summary.rpt, so every utilization and timing number in the docs
links to a CSV. The raw reports stay in docs/reports/ooc/<top>/.
"""

from __future__ import annotations

import re
import sys

from analysis.common import ROOT, write_result


def parse(top: str) -> tuple[list[list[object]], dict[str, str]]:
    rpt = ROOT / "docs" / "reports" / "ooc" / top
    summary = dict(line.split(maxsplit=1) for line in (rpt / "summary.txt").read_text().splitlines() if line)
    timing = (rpt / "timing_summary.rpt").read_text()
    m = re.search(r"WNS\(ns\).*?\n[-\s]+\n\s*(\S+)\s+\S+\s+(\d+)\s+\d+\s+(\S+)\s+\S+\s+(\d+)", timing)
    if m is None:
        raise SystemExit(f"no design timing summary in {rpt / 'timing_summary.rpt'}")
    wns, fail_setup, whs, fail_hold = m.groups()
    rows: list[list[object]] = []
    for line in (rpt / "utilization_hier.rpt").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 10 or not cells[7].replace(".", "").isdigit():
            continue
        inst, module, luts, _logic, _lutram, _srl, ffs, ramb36, ramb18, dsp = cells
        rows.append([inst, module if module != "(top)" else top, luts, ffs, ramb36, ramb18, dsp,
                     summary["clk_mhz"], wns, whs, int(fail_setup) + int(fail_hold)])
    return rows, summary


def main(argv: list[str]) -> int:
    top = argv[0]
    rows, s = parse(top)
    write_result(
        f"synth_{top}",
        ["instance", "module", "luts", "ffs", "ramb36", "ramb18", "dsp48e1", "clk_mhz", "wns_ns", "whs_ns",
         "failing_endpoints"],
        rows,
        f"no input data: out-of-context place and route of {top} on {s['part']}",
        command=f"make synth-ooc TOP={top}",
        tools=f"Vivado {s['vivado']}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
