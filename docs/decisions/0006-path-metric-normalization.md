# 0006: Modulo path metrics, no normalization step

## Context

Viterbi path metrics grow without bound. Left alone they overflow after long runs: "works for 1,000 frames, fails at
100,000" (CLAUDE.md §12). The ACS must keep them bounded at 72 kbit/s indefinitely.

## Options considered

| Option | Hardware | Notes |
|---|---|---|
| **Modulo arithmetic** | Registers wrap; compare with the sign of the modulo difference | No extra logic in the ACS loop. Correct while the candidate spread stays under half the range |
| Subtract minimum | 64-way minimum tree + 64 subtractors every step | The minimum tree sits in the ACS feedback path and limits Fmax |
| Subtract on threshold | Detect all metrics above a threshold, subtract a constant | Cheaper than subtract-minimum, still needs a global AND across 64 states every step |

## Decision

Modulo arithmetic. Width from the spread bound: every state is reachable from the best state K−1 = 6 steps earlier,
so the path-metric spread is at most 6·BMmax. ACS compares candidates (metric + branch metric), whose spread is
at most 7·BMmax. Modulo comparison is correct while that is below 2^(bits−1): `path_metric_bits()` gives 8 bits for
3-bit soft (7·14 = 98 < 128) and 9 bits for 4-bit (7·30 = 210 < 256).

## Consequences

- No normalization logic and no global signal across the 64 states. Formal proof of the bound is still required in
  Phase D (CLAUDE.md §8.3).
- The best-state search at traceback uses the same modulo comparison.

## Measured evidence

- `model/tests/test_viterbi_fixed.py`: at σ = 1.0 (the largest spread tested), the modulo decoder matches the float
  decoder bit for bit over 32 × 4,096 bits at both widths. The largest spread seen is 48 (3-bit, bound 84) and 104
  (4-bit, bound 180). Registers narrower than the observed spread break decoding, so the check is not vacuous.
- `data/results/soft_width_ber.csv`: every BER point was decoded with modulo metrics at the derived width.

## Amendment (2026-11-06): formal status

The bound is now SVA in `fec_acs_array.sv`: every pair of metrics within ±(K − 1)·BMmax, checked as max − min of
the metrics relative to state 0, and (K − 1)·BMmax + BMmax < 2^(bits−1). It runs in every simulation. `make formal`
(`tb/formal/fec_acs_array.sby`) proves that a stall changes no metric, and finds no input sequence that breaks the
bound within 8 steps of reset at 4 bits. **The unbounded proof is open**: k-induction needs 7 unrolled steps of the
64-state array (first written as 2,016 pair assertions) and had not finished after 6.5 hours (`docs/viterbi.md`). Planted bugs:
no metric reset and a metric one bit too narrow are caught; a sign-extended branch metric needs 14 or more steps to
break the bound, beyond the bounded depth. The decision stands. In the model recurrence, the spread reaches
4·BMmax at most, a third below the bound the width is sized for.
