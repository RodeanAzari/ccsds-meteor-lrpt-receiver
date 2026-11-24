"""The committed gs-image vectors (gs/tests/data/msumr) are what the golden model writes today.

Why it matters: gs/tests/msumr_test.cpp replays these files; if model/msumr.py changes and they are not regenerated,
gs-image would be tested against a model that no longer exists.
"""

from __future__ import annotations

from pathlib import Path

from scripts.gen_msumr_vectors import OUT, generate


def test_committed_vectors_are_current(tmp_path: Path) -> None:
    names = generate(tmp_path)
    for name in names:
        for ext in ("packets", "summary", "image"):
            fresh, committed = tmp_path / f"{name}.{ext}", OUT / f"{name}.{ext}"
            if ext == "packets" and name == "real":
                continue  # the input, extracted once from the pass (gen_msumr_vectors.py --extract)
            assert fresh.exists() == committed.exists(), f"{committed}: run scripts/gen_msumr_vectors.py"
            if fresh.exists():
                assert fresh.read_bytes() == committed.read_bytes(), f"{committed} stale: run gen_msumr_vectors.py"
    assert sorted(p.stem for p in OUT.glob("*.summary")) == sorted(names), "a vector file with no scenario"
