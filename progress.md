# Progress

Current state, next steps and key decisions only. Details belong in `docs/log.md`, `docs/decisions/` and `data/results/`.

## Where things stand

**Phase 0: blocked on a real recording.**

- Done: `docs/signal-spec.md`, written from SatDump 1.2.2 source. Nothing in it is confirmed on a real signal yet.
- Kit: RTL-SDR Blog V3/V4 + Nooelec SAWbird+ NOAA ordered 2026-11-04, arriving about 2026-11-25.
- Not done: decode a real recording with SatDump, capture your own pass.

**Phase A: float model working on synthetic signals.**

- Done: transmit chain, parameterized RS codec, float receiver; 43 tests passing.
- Measured (`data/results/`):
  - BER matches theory, uncoded and Viterbi.
  - Full chain recovers every frame it can reach from 2.5 dB up.
- SatDump 1.2.2 decodes our synthetic recording: every CADU it writes matches truth (`data/results/satdump_crosscheck.csv`).
- Bit-true DDC (`model/ddc_fixed.py`): same frames and soft SNR as the float DDC (`data/results/ddc_fixed_chain.csv`);
  formats in `docs/fixed-point.md`; ADRs 0003 (NCO) and 0004 (CIC).
- Bit-true RRC (`model/rrc_fixed.py`): same frames and soft SNR as the float RRC, SQNR 63–68 dB
  (`data/results/rrc_fixed_chain.csv`). 47 tests passing.
- Bit-true sync (`model/sync_fixed.py`: AGC, Costas, Farrow + Gardner): everything from cu8 to soft symbols is now
  integer. Same frames as float at 2–8 dB, 1 and 3.4 kHz offsets with a 30 Hz/s ramp; tracking error 1.7–4.0 Hz rms
  (`data/results/sync_fixed_chain.csv`). 51 tests passing.
- Soft decisions: 4-bit, step ONE/4 (ADR 0005). Loss at BER 1e-5: 0.13 dB (3-bit: 0.24 dB)
  (`data/results/soft_width_ber.csv`). Bit-true Viterbi ACS with 9-bit modulo path metrics (ADR 0006) matches the
  float decoder bit for bit. 54 tests passing.
- Traceback: BRAM survivors, per-bit traceback 96 deep from state 0 (ADRs 0007, 0008); equals full-block BER
  (`data/results/traceback_depth.csv`). Depth 96 is outside CLAUDE.md's 35–50, which assumes a best-state start.
  `docs/design.md` summarizes ADRs 0001–0008. 56 tests passing.
- Not done: a real recording. Phase A's model work is otherwise complete through the Viterbi.

## Next steps

1. **You:** capture a pass with the V3 + SAWbird+ (bias tee on, gain raised from low while watching the waterfall),
   or get a public 72k recording from the libre.space forum. Check the satellite is in 72k mode first.
2. Decode it with SatDump and list it in `data/MANIFEST.md` with the gain.
3. On the recording: confirm the spec, resolve which rail leads and which carries G1, and compare the model's CADUs
   with SatDump's.
4. Phase B: DDC RTL from `model/ddc_fixed.py`, BRAM ROM only until `eth-core-v0.1`; `gs-replay`. Phase B DDC RTL can start from `model/ddc_fixed.py` (BRAM ROM
   only until `eth-core-v0.1`).

## Key decisions

| Decision | Why | Where |
|---|---|---|
| Add an NRZ-M decoder after Viterbi | SatDump's pipeline uses it; without it no ASM matches | ADR 0001 |
| Drop the dual-basis RS stage | The pipeline sets `rs_dualbasis: false` | `docs/signal-spec.md` |
| Search {0°, 90°} × swap on absolute correlation | NRZ-M makes 180° irrelevant | `docs/signal-spec.md` |
| `gs-diff` compares the 892 data bytes only | SatDump leaves channel errors in parity and ASM | `docs/signal-spec.md` |
| Carrier before timing; coarse fourth-power estimate first | Timing first fails on OQPSK; narrow loops pull in too slowly | ADR 0002 |
| Bit-true chain: host coarse estimate goes into the DDC NCO word | No FFT hardware; the RRC sees a centred signal | ADR 0002, `docs/fixed-point.md` |
| AGC on I²+Q² power, target rail rms 4096 | Steady state equals the float chain's unit-power normalization | `docs/fixed-point.md` |
| 4-bit soft, step ONE/4 | 0.11 dB better than 3-bit at 1e-5 for one bit per metric | ADR 0005 |
| Modulo path metrics, 9 bits | No normalization logic in the ACS loop | ADR 0006 |
| Traceback 96 deep from state 0, BRAM | Matches full-block BER; no 64-way minimum; ~14x real-time throughput | ADRs 0007, 0008 |
| Costas 0.001 rad/sample, timing kp 0.02 | Measured sweeps | `data/results/sync_*.csv` |
| Work in WSL at `~/CCSDS`; board USB through usbipd-win | Toolchain lives in WSL; /mnt/c is slow | This file |
| Sync threshold 0.75; frames under the flywheel held until the lock is confirmed | Fixes false locks and duplicate frames | `model/receiver.py` |

## Open questions

- Board Ethernet from WSL2: UDP multicast may need mirrored networking mode. Test before Phase B.
- Project 2 is `~/OrderBook` (github.com/RodeanAzari/OrderBook), at Phase A awaiting sign-off. `fpga-eth-core` is
  created in its Phase B, and it has no `tb/common/` and no `eth-core` tags yet. Until `eth-core v0.1`: hardware
  testing from a BRAM ROM only; until `v0.2`: results over UART/ILA (CLAUDE.md, Dependencies on Project 2).
- Coarse estimate in hardware vs. on the host (ADR 0002). Decide in Phase C.
- tb/common: follow coord.py (decided 2026-11-03). Import P2's `tb/common/` by path until `tb-common-v0.1`, then the
  pinned tag. P2 has no `tb/common/` yet, so cocotb benches start with plain cocotb.
