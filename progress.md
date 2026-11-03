# Progress

Current state, next steps and key decisions only. Details belong in `docs/log.md`, `docs/decisions/` and `data/results/`.

## Where things stand

**Phase 0: blocked on a real recording.**

- Done: `docs/signal-spec.md`, written from SatDump 1.2.2 source. Nothing in it is confirmed on a real signal yet.
- Not done: decode a recording with SatDump, buy the kit, capture your own pass.

**Phase A: float model working on synthetic signals.**

- Done: transmit chain, parameterized RS codec, float receiver; 37 tests passing.
- Measured (`data/results/`):
  - BER matches theory, uncoded and Viterbi.
  - Full chain recovers every frame it can reach from 2.5 dB up.
- Not done: SatDump cross-check, a real recording, bit-true model, `docs/fixed-point.md`.

## Next steps

1. **You:** run the SatDump cross-check on the synthetic file. Generate it with `make synthetic-iq`, then:

   ```
   satdump meteor_m2-x_lrpt baseband data/synthetic/synthetic_seed2026_1024000SPS.cu8 out \
       --samplerate 1024000 --baseband_format cu8 --freq_shift -150000 --dc_block
   python scripts/compare_cadus.py out/meteor_m2-x_lrpt.cadu data/synthetic/synthetic_seed2026_truth.cadu
   ```

   The command is untested; check SatDump's actual output filename. My attempt to run SatDump was blocked by the
   permission check.
2. **You:** get a real recording. Ask on the libre.space forum or buy the kit.
3. On the recording: confirm the spec, resolve which rail leads and which carries G1, and compare the model's CADUs
   with SatDump's.
4. Bit-true model and `docs/fixed-point.md`. Start the NCO, CIC and soft-width ADRs.

## Key decisions

| Decision | Why | Where |
|---|---|---|
| Add an NRZ-M decoder after Viterbi | SatDump's pipeline uses it; without it no ASM matches | ADR 0001 |
| Drop the dual-basis RS stage | The pipeline sets `rs_dualbasis: false` | `docs/signal-spec.md` |
| Search {0°, 90°} × swap on absolute correlation | NRZ-M makes 180° irrelevant | `docs/signal-spec.md` |
| `gs-diff` compares the 892 data bytes only | SatDump leaves channel errors in parity and ASM | `docs/signal-spec.md` |
| Carrier before timing; coarse fourth-power estimate first | Timing first fails on OQPSK; narrow loops pull in too slowly | ADR 0002 |
| Costas 0.001 rad/sample, timing kp 0.02 | Measured sweeps | `data/results/sync_*.csv` |
| Sync threshold 0.75; frames under the flywheel held until the lock is confirmed | Fixes false locks and duplicate frames | `model/receiver.py` |

## Open questions

- Host setup: CLAUDE.md assumes a Linux host, but this machine is Windows with WSL2. Resolve before Phase B.
- `fpga-eth-core` isn't on this machine or among the repos listed on your GitHub account. Needed for Phase B.
- Coarse estimate in hardware vs. on the host (ADR 0002). Decide in Phase C.
