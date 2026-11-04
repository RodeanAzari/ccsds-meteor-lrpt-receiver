# 0005: 4-bit soft decisions, quantizer step 1/4 of rail rms

## Context

The Viterbi decoder takes quantized soft symbols. Each extra bit costs area in every branch metric and path metric of
the fully parallel 64-state ACS (CLAUDE.md §3.6), and buys coding gain. CLAUDE.md asks for both widths to be measured.
Soft symbols leave the sync chain as s16 in units of `ONE` = 4096, the AGC's rail rms (`docs/fixed-point.md`).

## Options considered

Quantizer: midrise uniform, step 2^shift (the RTL selects bits, no multiplier), clamped, offset binary
(`model/viterbi_fixed.py`). The best step for each width was found by sweeping shift 7–12 at 3 dB.

| Width | Best step | Eb/N0 at BER 10⁻⁵ | Loss vs unquantized | Branch metric | Path metric (derived) |
|---|---|---|---|---|---|
| Unquantized | — | 4.15 dB | — | — | — |
| **4 bits** | ONE/4 (shift 10) | **4.28 dB** | **0.13 dB** | 0–30, 5 bits | 9 bits |
| 3 bits | ONE/4 (shift 10) | 4.39 dB | 0.24 dB | 0–14, 4 bits | 8 bits |

Path-metric widths follow from the spread bound in ADR 0006. LUT and register counts for each width are `[TBD]` until
Phase D synthesis. The RTL is parameterized on the width, so both can be built and compared.

Each crossing is interpolated between points with about 100 errors (±20% on BER, roughly ±0.05 dB on the crossing),
so the 0.11 dB difference between the widths is about twice the uncertainty of each.

## Decision

4-bit soft decisions with step ONE/4: levels at ±1/8 … ±15/8 of rail rms, clipping at ±2 rms.

Why: 0.11 dB is cheap to keep. The cost is one bit in 128 branch-metric adders and in 64 path-metric registers and
comparators on a device with area to spare (CLAUDE.md §1, §3.6). The link is a dipole into an RTL-SDR, so margin at the
edges of a pass is worth more than a few hundred LUTs.

## Consequences

- Viterbi input is 4-bit offset binary; path metrics are 9-bit modulo (ADR 0006).
- The step assumes the AGC holds rail rms at ONE. The chain measures 1.04–1.06 ONE at the strobes, well inside one
  step (a factor of 2). If a real recording shows a different level, rerun the sweep before changing the RTL.
- Phase D reports measured area for both widths and rechecks this decision against it.

## Measured evidence

- `data/results/soft_width_step.csv`: step sweep at 3 dB.
- `data/results/soft_width_ber.csv`: BER curves; plot `docs/media/2026-11-04_phase-a_soft-width-ber.png`.
- Both from `python -m analysis.soft_width_study`, AWGN symbol channel, synthetic only.
