"""ila_viterbi: the step-by-step check of the board's ACS path metrics against the bit-true model.

Why it matters: this is the pass/fail of the Phase D hardware capture. A capture of a correct ACS must pass, and the
faults an ACS or a capture can have must fail it: a wrong metric bit, the two soft symbols swapped (G1/G2 order),
decisions taken from the wrong step, and a lost or repeated step. A capture whose conditions did not apply (not
starting at the trigger, or storing a cycle that was not a step) must be refused, not checked.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from model.viterbi_fixed import acs_step
from scripts.ila_viterbi import N_STATES, PM_BITS, SOFT_BITS, check_steps, parse_acs_ila, relative_metrics

N = 300


def capture(swap: bool = False, dec_shift: int = 1) -> tuple[list[int], list[int], list[int]]:
    """A correct ACS run from zero metrics on random symbols, as the ILA would store it: per step the metrics
    before it, its symbols {b, a}, and the decisions of the step dec_shift steps before (1 for the RTL)."""
    rng = np.random.default_rng(7)
    sym = rng.integers(0, 1 << SOFT_BITS, size=(N, 2))
    pm = np.zeros((1, N_STATES), dtype=np.int64)
    pms, decs = [], [np.zeros(N_STATES, dtype=bool)]
    for a, b in sym:
        pms.append(pm[0].copy())
        d, pm = acs_step(pm, np.array([[a]]), np.array([[b]]), SOFT_BITS, PM_BITS)
        decs.append(d[0])
    words = [sum(int(v) << (PM_BITS * s) for s, v in enumerate(p)) for p in pms]
    syms = [int(a) << SOFT_BITS | int(b) if swap else int(b) << SOFT_BITS | int(a) for a, b in sym]
    dec_words = [sum(int(v) << s for s, v in enumerate(decs[k + 1 - dec_shift])) for k in range(N)]
    return words, syms, dec_words


# Vivado splits a probe into hw_probes by net name, one CSV column each (2026-11-23 capture: probe0 in 4 pieces per
# state). SPLIT cuts each probe into such pieces: (probe, lo, hi) in .ltx pin order.
WIDTHS = {"probe0": PM_BITS * N_STATES, "probe1": 2 * SOFT_BITS, "probe2": N_STATES, "probe3": 1}
SPLIT = [("probe0", lo, min(lo + 6, 575)) for lo in range(0, 576, 7)] + [("probe1", 0, 1), ("probe1", 2, 7),
                                                                      ("probe2", 0, 63), ("probe3", 0, 0)]


def ltx(pieces: list[tuple[str, int, int]]) -> str:
    pins = [{"name": n, "leftIndex": lo, "rightIndex": hi, "nets": [{"name": f"net{k}", "isBus": True}]}
            for k, (n, lo, hi) in enumerate(pieces)]
    return json.dumps({"ltx_root": {"ltx_data": [{"debug_cores": [{"name": "dbg_hub"}, {"name": "u_ila",
                                                                                       "pins": pins}]}]}})


def csv(words: list[int], syms: list[int], decs: list[int], enable: list[int] | None = None,
        trigger_row: int = 0, pieces: list[tuple[str, int, int]] = SPLIT) -> str:
    enable = enable or [1] * len(words)
    lines = ["Sample in Buffer,Sample in Window,TRIGGER," + ",".join(f"net{k}[{hi - lo}:0]"
                                                                      for k, (_, lo, hi) in enumerate(pieces)),
             "Radix - UNSIGNED,UNSIGNED,UNSIGNED" + ",HEX" * len(pieces)]
    for k, row in enumerate(zip(words, syms, decs, enable, strict=True)):
        value = dict(zip(WIDTHS, row, strict=True))
        cols = [f"{(value[n] >> lo) & ((1 << (hi - lo + 1)) - 1):x}" for n, lo, hi in pieces]
        lines.append(f"{k},{k - trigger_row},{int(k == trigger_row)}," + ",".join(cols))
    return "\n".join(lines)


def run(text: str, pieces: list[tuple[str, int, int]] = SPLIT) -> tuple[int, int, int]:
    return check_steps(*parse_acs_ila(text, ltx(pieces)))


def test_a_correct_acs_capture_passes() -> None:
    assert run(csv(*capture())) == (0, 0, -1)


def test_metric_bit_flip_fails_at_that_step() -> None:
    words, syms, decs = capture()
    words[150] ^= 1 << (PM_BITS * 17 + 3)
    bad_pm, _, first = run(csv(words, syms, decs))
    assert bad_pm >= 1 and first == 149  # step 149 should have produced row 150


@pytest.mark.parametrize("fault", ["swapped_symbols", "decisions_one_step_late", "lost_step", "repeated_step"])
def test_acs_and_capture_faults_fail(fault: str) -> None:
    words, syms, decs = capture(swap=fault == "swapped_symbols", dec_shift=2 if fault == "decisions_one_step_late"
                                else 1)
    if fault == "lost_step":
        del words[100], syms[100], decs[100]
    if fault == "repeated_step":
        words.insert(100, words[100]); syms.insert(100, syms[100]); decs.insert(100, decs[100])  # noqa: E702
    bad_pm, bad_dec, _ = run(csv(words, syms, decs))
    assert bad_pm + bad_dec > 0


def test_capture_conditions_are_enforced() -> None:
    words, syms, decs = capture()
    with pytest.raises(ValueError, match="not an ACS step"):
        parse_acs_ila(csv(words, syms, decs, enable=[1] * 10 + [0] + [1] * (N - 11)), ltx(SPLIT))
    with pytest.raises(ValueError, match="trigger"):
        parse_acs_ila(csv(words, syms, decs, trigger_row=5), ltx(SPLIT))


def test_split_probes_are_reassembled_and_a_wrong_map_is_refused() -> None:
    """The .ltx map puts the pieces back; a missing piece, an overlap or a column that is not the .ltx's net there
    must be refused, not read as some other bits."""
    words, syms, decs = capture()
    whole = [("probe0", 0, 575), ("probe1", 0, 7), ("probe2", 0, 63), ("probe3", 0, 0)]
    assert run(csv(words, syms, decs, pieces=whole), whole) == run(csv(words, syms, decs)) == (0, 0, -1)
    text = csv(words, syms, decs)
    with pytest.raises(ValueError, match="not every one"):
        parse_acs_ila(text, ltx([*SPLIT[:3], ("probe0", 21, 21), *SPLIT[4:]]))
    with pytest.raises(ValueError, match="twice"):
        parse_acs_ila(text, ltx([*SPLIT[:3], ("probe0", 20, 26), *SPLIT[4:]]))
    with pytest.raises(ValueError, match=r"the \.ltx has"):
        parse_acs_ila(text.replace(",net3[", ",netX[", 1), ltx(SPLIT))


def test_relative_metrics_unwrap_across_the_modulo_boundary() -> None:
    pm = np.array([[510, 3, 1] + [2] * (N_STATES - 3)], dtype=np.int64)  # 510 is -2 modulo 512: the best state
    assert relative_metrics(pm)[0, :3].tolist() == [0, 5, 3]
