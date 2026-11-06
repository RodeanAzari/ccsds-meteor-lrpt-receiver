"""Turn an out-of-context Vivado run (syn/synth_ooc.tcl) into data/results/synth_<top>.csv.

    python -m analysis.synth_report <top>          (run by make synth-ooc TOP=<top>)
    python -m analysis.synth_report <top> board    (run by make board; reports in docs/reports/board/<top>/)

One row per hierarchy instance from utilization_hier.rpt (LUTs, FFs, RAMB36/18, DSPs), plus the post-route
timing (WNS, WHS, failing endpoints) from timing_summary.rpt, so every utilization and timing number in the docs
links to a CSV. The raw reports stay in docs/reports/ooc/<top>/.
"""

from __future__ import annotations

import re
import sys

from analysis.common import ROOT, write_result


def parse(top: str, kind: str = "ooc") -> tuple[list[list[object]], dict[str, str]]:
    rpt = ROOT / "docs" / "reports" / kind / top
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
        rows.append(
            [
                inst,
                module if module != "(top)" else top,
                luts,
                ffs,
                ramb36,
                ramb18,
                dsp,
                summary["clk_mhz"],
                wns,
                whs,
                int(fail_setup) + int(fail_hold),
            ]
        )
    return rows, summary


def main(argv: list[str]) -> int:
    top = argv[0]
    kind = argv[1] if len(argv) > 1 else "ooc"
    rows, s = parse(top, kind)
    name, command, what = {
        "ooc": (
            f"synth_{top}",
            f"make synth-ooc TOP={s['top']}"
            + (f' GENERICS="{s["generics"]}" NAME={top}' if "generics" in s else ""),
            "out-of-context place and route",
        ),
        "board": (f"board_{top}", "make board", "board-level place and route (constr/arty_a7_100t.xdc)"),
    }[kind]
    write_result(
        name,
        [
            "instance",
            "module",
            "luts",
            "ffs",
            "ramb36",
            "ramb18",
            "dsp48e1",
            "clk_mhz",
            "wns_ns",
            "whs_ns",
            "failing_endpoints",
        ],
        rows,
        f"no input data: {what} of {s['top']}{' with ' + s['generics'] if 'generics' in s else ''} on {s['part']}",
        command=command,
        tools=f"Vivado {s['vivado']}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
