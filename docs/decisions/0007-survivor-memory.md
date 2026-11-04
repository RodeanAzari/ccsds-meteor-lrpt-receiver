# 0007: Survivor memory in BRAM, per-bit sliding traceback

## Context

The ACS produces one decision bit per state per step: 64 bits per decoded bit (CLAUDE.md §3.6). The decoder needs
72 kbit/s. With the core clock near 100 MHz, that is about 1,389 clocks per decoded bit.

## Options considered

| Option | Resources | Throughput | Notes |
|---|---|---|---|
| **BRAM decisions + per-bit traceback** (trace D steps for every output bit) | One BRAM36 (512 × 72; 64 bits per row, ≥ D rows); one state register and a 64:1 bit mux | ≈ f_clk / (D + overhead) bits/s | Simplest control: one read pointer, one bit out per traceback, in order |
| BRAM + chunked traceback (trace D + L, output L) | One BRAM, deeper (≥ 2D + L rows); L-bit reversal buffer | ≈ f_clk / 2 bits/s at L = D | Faster; bits come out reversed; each bit sees a depth between D and D + L |
| Register exchange | 64 × D flip-flops plus 64 × D 2:1 muxes (6,144 of each at D = 96) | One bit per clock | Fastest; large and routing-heavy. Throughput not needed here |

## Decision

BRAM decisions with per-bit sliding traceback. The row address of each traceback step is known in advance (t − d),
so BRAM reads pipeline. Only the 64:1 bit select depends on the current state, so one step per clock is realistic.
`model/viterbi_fixed.py` (`traceback_sliding()`) is bit-exact to this scheme.

## Consequences

- Throughput, derived at D = 96 and 100 MHz with ~4 clocks of overhead: ≈ 1.0 Mbit/s, about 14× the 72 kbit/s
  needed. Measured headroom is `[TBD]` until Phase D.
- That covers flat-out replay (≈ 5.5× real time, CLAUDE.md §8.4). It caps a BER campaign injected at the RRC input
  near 14× real time instead of the ~22× the link allows. If Phase E needs more, switch to chunked traceback under a
  new ADR. Its BER is at least as good, since every bit gets depth ≥ D.

## Measured evidence

`model/tests/test_viterbi_fixed.py`: sliding traceback returns the data exactly on a clean signal at depths 6 and
48. At depth 120 it matches full-block decisions on every bit at 3 dB, from either start state. Depth and start
state: ADR 0008.
