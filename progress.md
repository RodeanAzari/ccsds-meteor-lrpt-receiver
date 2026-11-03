# Progress

Current state, next steps and key decisions only. Details belong in `docs/log.md`, `docs/decisions/` and `data/results/`.

## Where things stand

**Phase 0: blocked on a real recording.**

- Done: `docs/signal-spec.md`, written from SatDump 1.2.2 source. Nothing in it is confirmed on a real signal yet.
- Kit: RTL-SDR Blog V3 + Nooelec SAWbird+ NOAA (CLAUDE.md §1).
- Not done: decode a real recording with SatDump, capture your own pass.

**Phase A: float model working on synthetic signals.**

- Done: transmit chain, parameterized RS codec, float receiver; 43 tests passing.
- Measured (`data/results/`):
  - BER matches theory, uncoded and Viterbi.
  - Full chain recovers every frame it can reach from 2.5 dB up.
- SatDump 1.2.2 decodes our synthetic recording: every CADU it writes matches truth (`data/results/satdump_crosscheck.csv`).
- Bit-true DDC (`model/ddc_fixed.py`): same frames and soft SNR as the float DDC (`data/results/ddc_fixed_chain.csv`);
  formats in `docs/fixed-point.md`; ADRs 0003 (NCO) and 0004 (CIC).
- Not done: a real recording, bit-true model from the RRC on.

## Next steps

1. **You:** capture a pass with the V3 + SAWbird+ (bias tee on, gain raised from low while watching the waterfall),
   or get a public 72k recording from the libre.space forum. Check the satellite is in 72k mode first.
2. Decode it with SatDump and list it in `data/MANIFEST.md` with the gain.
3. On the recording: confirm the spec, resolve which rail leads and which carries G1, and compare the model's CADUs
   with SatDump's.
4. Bit-true RRC, then sync loops; soft-width ADR. Phase B DDC RTL can start from `model/ddc_fixed.py` (BRAM ROM
   only until `eth-core-v0.1`).

## Key decisions

| Decision | Why | Where |
|---|---|---|
| Add an NRZ-M decoder after Viterbi | SatDump's pipeline uses it; without it no ASM matches | ADR 0001 |
| Drop the dual-basis RS stage | The pipeline sets `rs_dualbasis: false` | `docs/signal-spec.md` |
| Search {0°, 90°} × swap on absolute correlation | NRZ-M makes 180° irrelevant | `docs/signal-spec.md` |
| `gs-diff` compares the 892 data bytes only | SatDump leaves channel errors in parity and ASM | `docs/signal-spec.md` |
| Carrier before timing; coarse fourth-power estimate first | Timing first fails on OQPSK; narrow loops pull in too slowly | ADR 0002 |
| Costas 0.001 rad/sample, timing kp 0.02 | Measured sweeps | `data/results/sync_*.csv` |
| Work in WSL at `~/CCSDS`; board USB through usbipd-win | Toolchain lives in WSL; /mnt/c is slow | This file |
| Sync threshold 0.75; frames under the flywheel held until the lock is confirmed | Fixes false locks and duplicate frames | `model/receiver.py` |

## Open questions

- Board Ethernet from WSL2: UDP multicast may need mirrored networking mode. Test before Phase B.
- Project 2 is `~/OrderBook` (github.com/RodeanAzari/OrderBook), at Phase A awaiting sign-off. `fpga-eth-core` is
  created in its Phase B, and it has no `tb/common/` and no `eth-core` tags yet. Until `eth-core v0.1`: hardware
  testing from a BRAM ROM only; until `v0.2`: results over UART/ILA (CLAUDE.md, Dependencies on Project 2).
- Coarse estimate in hardware vs. on the host (ADR 0002). Decide in Phase C.
