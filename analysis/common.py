"""Write results with the sidecar CLAUDE.md §11.2 requires, so every number can be traced to a run."""

from __future__ import annotations

import csv
import platform
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import scipy

ROOT = Path(__file__).parents[1]
RESULTS = ROOT / "data" / "results"
NOTES = Path(__file__).parent / "interpretations"


def _commit() -> str:
    run = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "model", "analysis", "rtl", "tb"], cwd=ROOT, capture_output=True, text=True
    )
    return run.stdout.strip() + (" (with uncommitted changes)" if dirty.stdout.strip() else "")


def write_result(
    name: str,
    header: Sequence[str],
    rows: Sequence[Sequence[object]],
    seed: str,
    command: str | None = None,
    tools: str = "",
    recording: str | None = None,
) -> Path:
    """`command` overrides the analysis-module command line (e.g. for a cocotb run); `tools` adds to the versions.

    `recording` names a real input (its data/MANIFEST.md row) instead of the synthetic `seed`.
    """
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{name}.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    note = NOTES / f"{name}.md"
    interpretation = note.read_text(encoding="utf-8").strip() if note.exists() else "[TBD]"
    versions = f"Python {platform.python_version()}, NumPy {np.__version__}, SciPy {scipy.__version__}"
    if tools:
        versions += f", {tools}"
    if command is None:
        command = " ".join(["python", "-m", Path(sys.argv[0]).stem, *sys.argv[1:]]) + "` (module in `analysis/`)"
    else:
        command += "`"
    input_line = (
        f"real recording `{recording}` (data/MANIFEST.md)." if recording else f"synthetic, {seed}. No real recording."
    )
    path.with_suffix(".md").write_text(
        f"# {name}\n\n"
        f"- **Commit:** `{_commit()}`\n"
        f"- **Command:** `{command}\n"
        f"- **Tools:** {versions}\n"
        f"- **Input:** {input_line}\n\n"
        f"{interpretation}\n"
    )
    print(f"wrote {path.relative_to(ROOT)}")
    return path
