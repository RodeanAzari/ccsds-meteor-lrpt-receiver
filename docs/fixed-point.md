# Fixed-point formats

Every signal's width, scaling, rounding and saturation point, as CLAUDE.md §3.2 requires. The bit-true model
(`model/ddc_fixed.py`) uses exactly these; the RTL must match it bit for bit.

**Conventions.** `sN` is an N-bit two's-complement integer. Rounding is round-half-up everywhere: add 2^(s−1), then
arithmetic shift right by s. Every narrowing saturates explicitly, even where the bound below says it can't trigger,
so a wrong bound shows up as a clipped sample rather than a wrapped one. The only wrapping registers are inside the
CIC, where wraparound is part of the algorithm.

## DDC (Phase B)

| Stage | Signal | Format | Rounding / saturation | Why this width |
|---|---|---|---|---|
| Ingest | I, Q | s9, value 2·raw − 255 | none (exact) | Odd integers in [−255, 255]; the cu8 midpoint 127.5 maps exactly to 0, so ingest adds no DC |
| DC block | accumulator | s24 with 12 fraction bits | `acc >> 10` rounded | Pole 1 − 2⁻¹⁰, corner 159 Hz at 1.024 MS/s. 12 fraction bits shrink the rounding dead band to 1/8 input LSB |
| DC block | output | s10 | rounded from the accumulator, saturated | A step in DC can briefly double the input swing: ±510 |
| NCO | phase accumulator | u32 | wraps (modulo 2³²) | 0.24 mHz resolution at 1.024 MS/s; 150 kHz is exactly 600·2²⁰. ADR 0003 |
| NCO | table phase | top 12 bits: 2 quadrant + 10 address | truncated | Phase-truncation spurs ≈ −6.02·12 = −72 dBc; measured 71.6–72.8 dB SFDR. ADR 0003 |
| NCO | cos, sin | s16, peak 32,767 | table entries rounded | Amplitude error far below the phase-truncation spurs |
| Mixer | products | s10 × s16 → s26 sum | none (exact; fits a DSP48E1 25×18) | — |
| Mixer | output | s16 | `>> 11` rounded, saturated | Bound: 511·√2·32,767 / 2¹¹ = 11,563. Chosen so the compensation FIR below cannot saturate |
| CIC | integrator/comb registers | s22 | wrap | Hogenauer: 16 + N·log₂(RM) = 16 + 3·2 = 22. ADR 0004 |
| CIC | output (256 kS/s) | s16 | `>> 6` rounded, saturated | Gain (RM)ᴺ = 64 = 2⁶ is removed exactly; output ≤ input |
| Comp FIR | taps (31) | s18, 17 fraction bits | taps rounded from `comp_fir_taps()` | Fits the DSP48E1 18-bit port; largest tap is 0.79 |
| Comp FIR | accumulator | ≤ 39 bits | none (exact; DSP48E1 has 48) | 16 + 18 + log₂(31) |
| Comp FIR | output → RRC | s16 | `>> 17` rounded, saturated | Σ\|taps\| = 1.98, so the worst case is 11,563 · 1.98 = 22,900 < 32,767 |

**Headroom.** The widths cover a full-scale DC step, so a typical signal uses little of the output range: the
synthetic recording (rms 38 LSB at the cu8 input) peaks at about 0.09 of full scale. That costs nothing measurable:
`data/results/ddc_fixed_chain.csv` shows the same frames and the same soft-symbol SNR (within 0.01 dB at every
noisy point) as the float DDC.

**Measured.** DDC quantization noise is 51.0–53.7 dB below the output on noisy inputs and 64.1 dB on a clean one
(`data/results/ddc_fixed_chain.csv`). Why SQNR is lower with noise than without is not yet established.

## RRC matched filter (Phase C)

Bit-true model: `model/rrc_fixed.py`. Input is the comp FIR output above.

| Stage | Signal | Format | Rounding / saturation | Why this width |
|---|---|---|---|---|
| RRC | taps (57: ±8 symbols at 3.56 sps, α = 0.5) | s18, 17 fraction bits | taps rounded from `rrc_taps()`; rounding keeps them symmetric | DSP48E1 18-bit B port; max tap 0.32, DC gain 1.000. Symmetry lets the RTL fold pairs through the 25-bit pre-adder (29 multipliers per rail) |
| RRC | accumulator | ≤ 40 bits | none (exact; DSP48E1 has 48) | 16 + 18 + log₂(57) |
| RRC | output → timing/carrier | s16 | `>> 17` rounded, saturated | Σ\|taps\| = 1.374, so the worst case is 22,900 · 1.374 = 31,465 < 32,767; checked by `test_rrc_fixed.py` |

**Measured.** RRC SQNR is 63.3–67.6 dB, about 12 dB below the DDC's, and the decoder sees no difference from a float
RRC: same frames, soft SNR within 0.01 dB (`data/results/rrc_fixed_chain.csv`).

**Normalization.** The float chain scales the RRC output to unit rail power (`normalize_rails()`); in hardware that is
the AGC's job, which is not yet bit-true.

## Synchronization (Phase C)

Bit-true model: `model/sync_fixed.py`, order per ADR 0002: AGC → Costas → Farrow + per-rail Gardner. **Sync unit:**
`ONE` = 4096, the AGC's target rail rms, so s16 leaves 8× rms headroom. Loop gains are integer registers computed from
the same `RxConfig` values as the float loops (`loop_gains()`); `test_sync_fixed.py` holds each within 1% of float.

| Stage | Signal | Format | Rounding / saturation | Why this width |
|---|---|---|---|---|
| Coarse frequency | — | host float, added to the DDC NCO word | — | ADR 0002: no FFT in hardware. Moves the signal to the centre of the RRC |
| AGC | gain | u20, 12 fraction bits (1/4096 to 256) | clamped to [1, 2²⁰−1] | The synthetic recording settles at 5.9 (8 dB) to 9.8 (2 dB), far inside the range (`data/results/sync_agc_settle.csv`). A real recording's level is `[TBD]` |
| AGC | output I, Q | s16, rms target `ONE` | `x·g >> 12` rounded, saturated | Saturates only beyond 8× rms |
| AGC | detector, update | I² + Q² (s33) vs. 2·ONE²; `g += (target − p) >> 24` rounded | — | Power detector: steady state is exactly unit rail power, what the float `normalize_rails()` gives. Linearized time constant ≈ 1,024·g samples (g = gain), so it slows for weaker signals. Measured from g = 1 to 90% of the settled gain: 60 ms at 8 dB to 104 ms at 2 dB (`data/results/sync_agc_settle.csv`) |
| Costas | phase | u32, wraps | top 12 bits index the DDC's NCO table | Phase truncation ≤ 2π/4096 = 0.09° |
| Costas | cos, sin | s16 (the DDC NCO table) | — | Shared table |
| Costas | rotator output | s16 | `>> 15` rounded, saturated | Rotation keeps magnitude; clips only beyond 8× rms |
| Costas | phase error | ONE-scaled | clamped to ±ONE | Same clamp as the float loop (±1) |
| Costas | frequency integrator | 32 + 16 fraction bits | clamped to ±15 kHz | ki is 0.67 phase LSB per ONE of error: without the 16 fraction bits it rounds to 1, a 50% gain error |
| Farrow | μ | u16 fraction | top 16 of 24 position fraction bits, truncated | Interpolation error from μ ≤ 2⁻¹⁶ of a sample |
| Farrow | output | s16 | three rounded Horner steps + rounded halving, saturated | Error ≤ 1.25 LSB against the float cubic, −72 dB under rms (`test_sync_fixed.py`) |
| Gardner | error | ONE-scaled | product `>> 12` rounded, clamped to ±ONE | Same clamp as float |
| Timing | position | 24 fraction bits | — | Nominal step 1.777… samples to 2⁻²⁴ |
| Timing | integrator | 24 + 16 fraction bits | clamped to ±1% of nominal | ki would round to 0 without the 16 fraction bits |

**Measured.** With everything up to the soft symbols bit-true, the receiver decodes the same frames as the float chain
at every Eb/N0 from 2 to 8 dB and at 1 kHz and 3.4 kHz offsets with a 30 Hz/s ramp. Frequency tracking error is
1.7–4.0 Hz rms (`data/results/sync_fixed_chain.csv`).

## Soft decisions and Viterbi (Phase D)

Bit-true model: `model/viterbi_fixed.py`. ADRs 0005 (width) and 0006 (path metrics).

| Stage | Signal | Format | Rounding / saturation | Why this width |
|---|---|---|---|---|
| Soft quantizer | input | s16 serial soft stream, ONE units | — | Chain soft rms is 1.04–1.06 ONE at the strobes |
| Soft quantizer | output | u4 offset binary; level u means (u − 8 + ½)·ONE/4 | `soft >> 10` (floor, midrise), + 8, clamped to [0, 15] | ADR 0005: 0.13 dB from unquantized at 10⁻⁵; levels symmetric about zero |
| Branch metric | per branch | u5, 0–30 | none (exact) | Distance: 15 − u for an expected 1, u for an expected 0, summed over G1 and G2 |
| Path metric | per state | u9, modulo 2⁹ | wraps by design; compare by the sign of the 9-bit difference | ADR 0006: candidate spread ≤ 7·30 = 210 < 256. Ties keep branch 0, as the float decoder does |

**Measured.** With modulo metrics the integer decoder matches the float decoder bit for bit on the same quantized input
(`model/tests/test_viterbi_fixed.py`). BER: `data/results/soft_width_ber.csv`.

## Later stages

Survivor memory and traceback depth (Phase D ADRs), derandomizer and RS: `[TBD]`. The bit-true model above still
traces back over the whole block.
