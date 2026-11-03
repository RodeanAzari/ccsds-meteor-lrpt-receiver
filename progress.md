# Progress

Current state, next steps and key decisions only. Details belong in `docs/log.md`, `docs/decisions/` and `data/results/`.

## Where things stand

**Phase 0: blocked on a real recording.**

- Done: `docs/signal-spec.md`, written from SatDump 1.2.2 source. Nothing in it is confirmed on a real signal yet.
- Not done: decode a recording with SatDump, buy the kit, capture your own pass.

**Phase A: started early on synthetic signals, with your approval.**

- Done: transmit chain, parameterized RS codec, float receiver, test suite. Synthetic signals decode end to end.
- In progress: sync and BER measurements. Results pending.
- Not done: validation against SatDump, bit-true model, `docs/fixed-point.md`.

## Next steps

1. Finish the sync and BER measurements, set the loop defaults, write the OQPSK timing ADR.
2. Generate the synthetic IQ file for a SatDump cross-check.
3. **You:** run SatDump 1.2.2 on that file. My attempt to download and run it was blocked by the permission check.
4. **You:** get a real recording. Ask on the libre.space forum or buy the kit; no public archive was found.
5. Use that recording to resolve which rail leads and which carries G1.

## Key decisions

| Decision | Why | Where |
|---|---|---|
| Add an NRZ-M decoder after Viterbi | SatDump's pipeline uses it; without it no ASM matches | ADR 0001 |
| Drop the dual-basis RS stage | The pipeline sets `rs_dualbasis: false` | `docs/signal-spec.md` |
| Search {0°, 90°} × swap on absolute correlation | NRZ-M makes 180° irrelevant | `docs/signal-spec.md` |
| `gs-diff` compares the 892 data bytes only | SatDump leaves channel errors in parity and ASM | `docs/signal-spec.md` |
| Sync threshold 0.75 | 0.55 caused false locks on random data | `model/receiver.py` |

## Open questions

- Host setup: CLAUDE.md assumes a Linux host, but this machine is Windows with WSL2. Resolve before Phase B.
- `fpga-eth-core` isn't on this machine or among the repos listed on your GitHub account. Needed for Phase B.
