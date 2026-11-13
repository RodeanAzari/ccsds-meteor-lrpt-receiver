"""make reports TAG=<tag>: copy the committed timing and utilization reports into docs/reports/<tag>/ (buildplan §6).

Every build (`make synth-ooc`, `make board`) already commits its reports to docs/reports/{ooc,board}/<name>/ with
the RTL that produced it. A milestone keeps a frozen copy: summary, timing summary and utilization of each build.
Refuses an existing snapshot, and any build with negative slack (CLAUDE.md §5.4: no milestone with negative slack).

Usage: python scripts/snapshot_reports.py <tag>
"""

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "docs" / "reports"
KINDS = ("ooc", "board")
FILES = ("summary.txt", "timing_summary.rpt", "utilization.rpt")


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not re.fullmatch(r"v[0-9][\w.-]*", argv[0]):
        print("usage: make reports TAG=<milestone tag, e.g. v0.5-first-real-decode>", file=sys.stderr)
        return 1
    dest = REPORTS / argv[0]
    if dest.exists():
        print(f"{dest.relative_to(ROOT)} exists: a milestone snapshot is never overwritten", file=sys.stderr)
        return 1
    builds = sorted(d for k in KINDS for d in (REPORTS / k).iterdir() if d.is_dir())
    negative = []
    for b in builds:
        missing = [f for f in FILES if not (b / f).is_file()]
        if missing:
            print(f"{b.relative_to(ROOT)}: missing {', '.join(missing)}", file=sys.stderr)
            return 1
        fields = dict(line.split(None, 1) for line in (b / "summary.txt").read_text().splitlines() if line.strip())
        if float(fields["wns_ns"]) < 0:
            negative.append(f"{b.relative_to(REPORTS)} (WNS {fields['wns_ns'].strip()} ns)")
    if negative:
        print("negative slack, no milestone snapshot: " + ", ".join(negative), file=sys.stderr)
        return 1
    for b in builds:
        out = dest / b.relative_to(REPORTS)
        out.mkdir(parents=True)
        for f in FILES:
            shutil.copy2(b / f, out / f)
    print(f"{len(builds)} builds copied to {dest.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
