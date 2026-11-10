"""The committed gs-rx demux vectors (gs/tests/data/demux) are what the golden model writes today.

Why it matters: the C++ test replays these files; if model/space_packets.py changes and they are not regenerated,
gs-rx would be tested against a model that no longer exists.
"""

from __future__ import annotations

from pathlib import Path

from scripts.gen_gs_vectors import OUT, generate


def test_committed_vectors_are_current(tmp_path: Path) -> None:
    names = generate(tmp_path)
    for name in names:
        for ext in ("cadu", "packets", "counts"):
            fresh, committed = tmp_path / f"{name}.{ext}", OUT / f"{name}.{ext}"
            assert committed.is_file(), f"{committed} missing: run scripts/gen_gs_vectors.py"
            assert fresh.read_bytes() == committed.read_bytes(), f"{committed} stale: run scripts/gen_gs_vectors.py"
    assert sorted(p.stem for p in OUT.glob("*.counts")) == sorted(names), "a vector file with no scenario"
