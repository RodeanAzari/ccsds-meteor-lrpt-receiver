# Viterbi decoder: tradeoffs (buildplan §3.6)

K = 7, r = ½, G1 = 171, G2 = 133 octal (`docs/signal-spec.md`). RTL: `rtl/fec/fec_viterbi.sv` = `fec_bm` →
64 × `fec_acs` (`fec_acs_array`) → `fec_traceback`. Bit-true model: `model/viterbi_fixed.py`. One decision per row
below, each with its ADR. Every number links to a result in `data/results/`; all inputs are synthetic.

| Component | Decision | Rejected | Evidence | ADR |
|---|---|---|---|---|
| Branch metrics | 4-bit soft, step ONE/4 | 3-bit | 0.11 dB at 1e-5 for 256 LUTs | 0005 |
| ACS | Fully parallel, 64 states, one step per clock | Folded ACS | 1,544 LUTs; throughput is set by traceback, not ACS | buildplan §3.6 |
| Path metrics | Modulo, 9 bits, no normalization | Subtract minimum, subtract on threshold | Bound holds 8 steps from reset (formal) and in every simulation; unbounded proof open | 0006 |
| Survivors | BRAM decision rows, per-bit sliding traceback | Register exchange, chunked traceback | 1 RAMB36, 77 LUTs | 0007 |
| Traceback | Depth 96 from state 0, a register | 35–50 from the best state | Matches full-block BER | 0008 |
| Throughput | 96 clocks per bit at 100 MHz: 14.5× real time | — | Measured in RTL simulation | 0007 |

## Branch metrics: soft-decision width

The decoder minimizes a distance on offset-binary symbols: top − u to an expected 1, u to an expected 0. Per symbol
this is a constant minus the float correlation, so for the same quantized input it decides exactly as the float
decoder does (`viterbi_fixed.py` docstring).

- **BER** (`soft_width_ber.csv`, plot `docs/media/2026-11-04_phase-a_soft-width-ber.png`): 4-bit is 0.11 dB better
  than 3-bit at 1e-5, about twice the uncertainty of each curve. At 4.0 dB, 3-bit makes 4.7e-5 errors and unquantized
  soft makes 1.7e-5.
- **Area** (`synth_fec_viterbi.csv`, `synth_fec_viterbi_3bit.csv`, out of context at 100 MHz): 1,621 LUTs and
  694 FFs at 4 bits (WNS +1.895 ns), 1,365 LUTs and 630 FFs at 3 bits (WNS +2.628 ns). The fourth bit costs 256 LUTs,
  0.4% of the device, almost all of it in the ACS array.
- **Kept 4-bit** (ADR 0005 amendment): 0.11 dB for 0.4% of the LUTs, with the whole receiver chain at 10.6%
  (`synth_rx_chain.csv`). The link is a dipole into an RTL-SDR, so margin at the edges of a pass is worth more.

## ACS: fully parallel

64 `fec_acs` units take one trellis step per clock. Folding would save LUTs the device doesn't need and multiply the
clocks per step; the traceback already sets the rate at ~96 clocks per bit, so the parallel array is idle most of
the time and its cost is area only: 1,544 LUTs and 641 FFs in the 4-bit build.

## Path metrics: modulo arithmetic

Metrics wrap modulo 2^9 and two candidates are compared by the sign of their modulo difference: no minimum tree and no
global signal across the 64 states in the ACS loop. The comparison is exact while any two candidates are within
2^8. Every state is reachable from the best state 6 steps back, so any two metrics differ by at most 6 × 30 = 180,
and any two candidates by at most 210 < 256.

- **Assertions** (`fec_acs_array.sv`): every pair of the 64 metrics within ±180, checked as one condition: each
  metric relative to state 0 as a 9-bit signed value, max − min ≤ 180 (pairs that close don't wrap, and the spread
  grows by at most 30 per step, so a violation shows before anything can wrap). And 180 + 30 < 256 for the configured
  widths. They run in every cocotb simulation and in SymbiYosys.
- **Formal** (`make formal`, `tb/formal/fec_acs_array.sby`, bitwuzla):
  - *Proven:* with free handshakes, a stall changes no metric, so a harness that steps every clock reaches every
    metric state the array can. k-induction can't see through stalls (k held cycles can be one state), hence the
    split.
  - *Bounded:* no input sequence breaks the bound within 8 steps of reset, at 4 bits.
  - *Open:* the unbounded proof (task `step`). The bound needs 7 unrolled steps of k-induction, since every state is
    reachable from the best state 6 steps back, and no one-step invariant of this form closes. Each step holds 64
    ACS units. On 2026-11-06, with the bound written as 2,016 pair assertions, the base case passed in 13 minutes
    and the induction had not finished after 6.5 hours; the same proof at 1 and 2 bits timed out after 2 hours. The
    max − min form replaced it (same condition, much cheaper in simulation); its induction is being rerun.
  - *Planted bugs:* path metrics not reset and an 8-bit metric for 4-bit soft are caught in under 30 s. A
    sign-extended branch metric breaks the bound only after 14 steps, even with the worst input at every step (1-bit,
    model recurrence): beyond the bounded depth, so only the open proof would catch it. An ACS that keeps the larger
    candidate stays bounded (the argument is symmetric); the bit-exact cocotb tests catch it.
- **Simulation**: the modulo decoder matches the float decoder bit for bit over 32 × 4,096 bits at σ = 1.0; the
  largest spread seen is 104 of the 180 bound (`model/tests/test_viterbi_fixed.py`). In the model recurrence, an
  input chosen to maximize the spread at every step reaches 4 × BM_MAX (8 at 1 bit, 24 at 2 bits), so the 6 × BM_MAX
  bound has a third in reserve.

## Survivors and traceback

Each step's 64 decision bits are one row of a 256-row ring in one RAMB36. Every output bit walks back `depth_i` rows
from state 0. The row address of each walk step is known in advance, so the BRAM read pipelines and only the 64:1
bit select depends on the state.

- **Register exchange** was rejected: 64 × depth flip-flops with a 64-wide mux per state per step, for a latency
  nobody needs on a recorded pass.
- **Depth** (`traceback_depth.csv`, plot `docs/media/2026-11-04_phase-a_traceback-depth.png`): at 2.5 dB,
  full-block decoding makes 1.740e-3 errors. A best-state start reaches that at depth 96 (1.740e-3) and is 5% worse
  at 48 (1.829e-3). A state-0 start, which needs no 64-way minimum, is 84% worse at 48 (3.202e-3) and equal at 96
  (1.743e-3). Depth 96 from state 0 is outside buildplan §3.6's 35–50, which assumes a best-state start (ADR 0008).
- The walk costs depth + 3 clocks per bit. Since the decoder has ~14× headroom, buying a minimum tree to shorten
  the walk would spend area to save time we already have.

## Throughput

`viterbi_rtl_sim.csv`: 95.9 clocks per bit with no stalls, against 1,389 at 100 MHz for 72 kbit/s: **14.5× real
time**. That covers flat-out replay over 100 Mb/s Ethernet (≈ 5.7×, ADR 0009). A BER campaign through the whole chain
is capped near 14× real time by the traceback. If Phase E needs more, chunked traceback (several bits per walk,
depth ≥ 96 for each) is the next step, under a new ADR (ADR 0007).

## In the receiver

The frame sync sends each frame as its own window, 128 symbols before it to 192 after (ADR 0010 amendment). The
decoder runs the windows back to back without a reset; the 64-step run-in absorbs the previous window's metrics, and
the 96-step run-out flushes the frame's last bit (`framesync_fixed.decode_windows()`). In RTL simulation from a cold
start, all 24,960 bits out of the chain match the model and every complete frame is a frame sent
(`rx_chain_rtl_decode.csv`).

Not yet: hardware BER (buildplan §9 Phase D) and the ILA capture of path metrics.
