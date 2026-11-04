# 0008: Traceback depth 96 from state 0

## Context

The traceback (ADR 0007) starts from some state at the newest step and walks back D steps. Starting from the best
state needs a 64-way modulo minimum every step. Starting from a fixed state needs a longer D for the survivors to
merge. CLAUDE.md §3.6 suggests D = 5–7 × K (35–50) and asks for a sweep.

## Options considered

BER of the 4-bit decoder (ADR 0005), 12.0 M bits per point, the same noise and ACS decisions for every row, relative
to full-block traceback:

| Configuration | 2.5 dB | 3.0 dB | 4.0 dB | Extra logic |
|---|---|---|---|---|
| Best state, D = 36 | +25% | +19% | +1% | 64-way min tree (63 nine-bit modulo comparators) |
| Best state, D = 48 | +5.1% | +2.0% | 0% | same |
| Best state, D = 60 | +1.0% | 0.0% | 0% | same |
| State 0, D = 48 | +84% | +92% | +86% | none |
| State 0, D = 72 | +3.6% | +1.2% | 0% | none |
| **State 0, D = 96** | **+0.1%** | **0%** | **0%** | **none** |

## Decision

Start from state 0, D = 96, as a register (the BRAM holds up to ~500 rows). Clocks per bit are nearly free (ADR 0007),
so a longer walk costs time we have and saves the minimum tree. In these measurements it matches full-block
decoding.

This is outside the 35–50 range in CLAUDE.md §3.6. That range assumes a best-state start, and even then it measures
2–5% worse than full-block at 2.5–3 dB.

## Consequences

- Throughput ≈ f_clk / ~100 per bit (ADR 0007).
- Decoding latency is 96 bits (1.3 ms at 72 kbit/s), irrelevant for a recorded pass.
- If chunked traceback is adopted later, it keeps D ≥ 96 per bit.

## Measured evidence

`data/results/traceback_depth.csv` (`python -m analysis.traceback_study`); plot
`docs/media/2026-11-04_phase-a_traceback-depth.png`. AWGN symbol channel, synthetic only. Every point has ≥ 100
errors.
