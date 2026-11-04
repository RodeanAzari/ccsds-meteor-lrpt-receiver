# Design summary

Architecture: CLAUDE.md §3. Fixed-point formats: `docs/fixed-point.md`. This file summarizes each decision record
and lists clock-domain crossings.

## Decisions

| ADR | Decision | Evidence |
|---|---|---|
| [0001](decisions/0001-nrzm-decoder.md) | NRZ-M decoder after Viterbi | SatDump pipeline; no ASM matches without it |
| [0002](decisions/0002-oqpsk-timing.md) | Carrier before OQPSK timing; host coarse estimate into the DDC NCO | `sync_loop_order.csv`, `sync_pull_in.csv` |
| [0003](decisions/0003-nco.md) | NCO: 32-bit phase, quarter-wave table, 12-bit table phase | `ddc_nco_sfdr.csv` |
| [0004](decisions/0004-cic.md) | CIC ÷4 order 3, 31-tap compensation FIR | `ddc_fixed_chain.csv` |
| [0005](decisions/0005-soft-decision-width.md) | 4-bit soft decisions, step 1/4 of rail rms | `soft_width_ber.csv` |
| [0006](decisions/0006-path-metric-normalization.md) | Modulo path metrics, 9 bits | `test_viterbi_fixed.py` |
| [0007](decisions/0007-survivor-memory.md) | Survivors in BRAM, per-bit sliding traceback | `test_viterbi_fixed.py` |
| [0008](decisions/0008-traceback-depth.md) | Traceback depth 96 from state 0 | `traceback_depth.csv` |

Still required (CLAUDE.md §5.5): interpolator type, Berlekamp–Massey variant, RS instance count, phase-ambiguity
strategy, IQ transport format. The interpolator (Catmull-Rom cubic) and phase-ambiguity strategy (4 hypotheses on the
encoded ASM, `signal-spec.md`) are implemented in the model but have no ADR yet.

## Clock-domain crossings

None yet: no RTL. Every crossing gets a row here and an XDC constraint when it is written.
