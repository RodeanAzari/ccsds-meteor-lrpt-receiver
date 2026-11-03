# 0002: Carrier before OQPSK timing, with a coarse frequency estimate first

## Context

CLAUDE.md §3 puts timing recovery before carrier recovery. With OQPSK the Q rail is half a symbol off from I, and
the carrier is still rotating at the timing stage. SatDump 1.2.2 runs Costas first, then delays Q by one sample, then
runs Mueller & Müller timing (`docs/signal-spec.md`).

## Options considered

| Order | Frames decoded of 48, 8 dB, at offsets of 0 / 300 / 1000 / 3000 Hz |
|---|---|
| Costas, then per-rail Gardner at 2 sps | 48 / 48 / 48 / 48 |
| Per-rail Gardner, then Costas | 9 / 48 / 16 / 42 |
| Plain QPSK Gardner, then Costas | 0 / 0 / 0 / 0 |

On acquisition: a Costas loop narrow enough to track well at low Eb/N0 pulls in too slowly. At 0.002 rad/sample it
mostly doesn't lock from 2 kHz or 3.4 kHz within 3.4 s. Wider loops pull in faster but decode far fewer frames.

## Decision

1. **Coarse frequency estimate:** a ~1 s FFT of the matched-filtered signal raised to the fourth power. The line sits
   at 4× the offset and stands about 13× above the median at 2 dB, against about 9× for noise alone.
2. **Costas loop:** fourth order, 0.001 rad/sample at 256 kS/s, run on every sample.
3. **Timing:** Farrow cubic interpolator to 2 sps. Per-rail Gardner detector: the real rail on even outputs, the
   imaginary rail on odd outputs. kp 0.02, ki = kp²/4.
4. **Rail alignment:** even real strobes paired with the following odd imaginary strobes into one serial soft stream.
   Which rail leads is resolved by the frame-sync hypotheses, not by a fixed delay.

**For the RTL:** the coarse estimate doesn't need FFT hardware. `gs-replay` or the host computes it from the first
seconds of IQ and writes the NCO frequency register, which CLAUDE.md §3.3 already plans for Doppler pre-correction.
This choice is open until Phase C.

## Consequences

- CLAUDE.md §3 and §12 ("plain QPSK Gardner on unaligned OQPSK") are consistent with this. Only the timing-before-
  carrier order in the §3 diagram changes.
- The Costas loop runs at 256 kS/s, before the Farrow interpolator, so it needs a full-rate rotator.

## Measured evidence

- `data/results/sync_loop_order.csv`
- `data/results/sync_costas_bw.csv`
- `data/results/sync_timing_gain.csv`
- `data/results/sync_pull_in.csv`
- `data/results/fer_full_chain.csv`

All from synthetic signals at commit `950a988`. Not confirmed on a real recording: `[TBD]`.
