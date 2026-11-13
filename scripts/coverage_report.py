"""Functional coverage closure (buildplan §8.2): merge the cocotb runs' Verilator coverage into the bins.

The bins are the `cov_*` cover properties in rtl/ (not rtl/eth/), counted by Verilator --coverage-user in every
simulation `make cov` builds (tb/cocotb/run.py with COV=1). A bin is named by its file and cover name
(`fec_cadu.sv:cov_rs_corrected_16`), so hits in block tests and in chain tests add up. Verilator merges a generate
loop's covers into one point, so a cover inside a loop is refused (docs/coverage.md). Closure is every bin
hit or excluded with a justification in docs/coverage.md's exclusion table; an exclusion whose bin was hit is stale
and fails too. Writes data/results/coverage.csv.

Usage: python scripts/coverage_report.py [build/sim]
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.common import write_result  # noqa: E402

GROUPS = {  # cover-name prefix -> buildplan §8.2 bin group
    "cov_fsm_": "sync FSM states and transitions",
    "cov_hyp_": "each phase hypothesis winning",
    "cov_rs_": "RS errors 0-16 plus uncorrectable",
    "cov_vit_": "Viterbi normalization events",
    "cov_bp_": "backpressure per interface",
}
EXCLUSIONS = ROOT / "docs" / "coverage.md"


def parse_dat(path: Path) -> dict[str, int]:
    """Bin name -> count for the cov_* user points of one coverage.dat."""
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="latin-1").splitlines():
        m = re.fullmatch(r"C '(.*)' (\d+)", line)
        if not m:
            continue
        fields = dict(f.split("\x02", 1) for f in m.group(1).split("\x01") if "\x02" in f)
        name, file = fields.get("o", ""), fields.get("f", "")
        if fields.get("t") != "user" or not name.startswith("cov_") or "/rtl/" not in file or "/rtl/eth/" in file:
            continue
        if "__BRA__" in fields["h"]:
            raise ValueError(f"{file}:{fields.get('l')}: {name} is in a generate loop; Verilator merges its iterations")
        key = f"{Path(file).name}:{name}"
        counts[key] = counts.get(key, 0) + int(m.group(2))
    return counts


def read_exclusions() -> dict[str, str]:
    """docs/coverage.md table rows `| bin | justification |` under '## Exclusions'."""
    text = EXCLUSIONS.read_text(encoding="utf-8")
    section = text.split("## Exclusions", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0].startswith("`") and cells[0] != "---":
            rows[cells[0].strip("`")] = cells[1]
    return rows


def group_of(key: str) -> str:
    name = key.rsplit(".", 1)[-1].split(":")[-1]
    for prefix, group in GROUPS.items():
        if name.startswith(prefix):
            return group
    raise ValueError(f"cover {key} has no bin group prefix ({', '.join(GROUPS)})")


def main(argv: list[str]) -> int:
    sim = Path(argv[0]) if argv else ROOT / "build" / "sim"
    dats = sorted(sim.glob("*/coverage.dat"))
    if not dats:
        print(f"no coverage.dat under {sim}: run make cov", file=sys.stderr)
        return 1
    total: dict[str, int] = defaultdict(int)
    for d in dats:
        for k, v in parse_dat(d).items():
            total[k] += v
    excl = read_exclusions()
    rows, missed, stale = [], [], []
    for key in sorted(total, key=lambda k: (group_of(k), k)):
        hits = total[key]
        status = "hit" if hits else ("excluded" if key in excl else "MISSED")
        if hits and key in excl:
            stale.append(key)
        if status == "MISSED":
            missed.append(key)
        rows.append([group_of(key), key, hits, status, excl.get(key, "")])
    unknown = [k for k in excl if k not in total and not k.startswith("group:")]
    for k in excl:  # whole groups with no RTL bin (e.g. no lock detector)
        if k.startswith("group:"):
            rows.append([k.removeprefix("group:"), k, 0, "excluded", excl[k]])
    defined = set(GROUPS.values()) | {"loop lock states"}
    covered_groups = {r[0] for r in rows}
    for g in sorted(defined - covered_groups):
        missed.append(f"group:{g}")
        rows.append([g, f"group:{g}", 0, "MISSED", ""])
    write_result("coverage", ["group", "bin", "hits", "status", "exclusion"], rows,
                 seed="the cocotb suites' own seeds (make cov: make sim, sim-slow and sim-full with COV=1)",
                 command="make cov", tools="Verilator 5.050 --coverage-user, cocotb 2.1.0")
    n_hit = sum(r[3] == "hit" for r in rows)
    n_excl = sum(r[3] == "excluded" for r in rows)
    print(f"{len(rows)} bins from {len(dats)} runs: {n_hit} hit, {n_excl} excluded, {len(missed)} missed")
    for k in missed:
        print(f"  MISSED {k}")
    for k in stale:
        print(f"  STALE exclusion (bin was hit): {k}")
    for k in unknown:
        print(f"  UNKNOWN exclusion (no such bin): {k}")
    return 1 if missed or stale or unknown else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
