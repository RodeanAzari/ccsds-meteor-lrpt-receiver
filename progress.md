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

**Phase B: DDC bit-exact in simulation and on the board.**

- `rtl/ddc/`: ingest + DC block, NCO + mixer, CIC ÷4, 31-tap comp FIR, `ddc_top`. Each block and the whole chain
  match `model/ddc_fixed.py` bit for bit under backpressure. 9.0 cycles per input sample, 10.8× real time at
  100 MHz (`data/results/ddc_rtl_sim.csv`). 13 cocotb tests; `make ci` runs lint and sim.
- tb-common pinned at `tb-common-v0.1` (pip from git) with cocotb 2.1.0.
- Out-of-context at 100 MHz: WNS +0.661 ns, 1,036 LUTs, 6 DSP48E1, 1 RAMB18 (`data/results/synth_ddc_top.csv`).
  Vivado via `scripts/vivado.sh`; `make synth-ooc TOP=<top>`.
- **On the board:** BRAM-ROM snippet → DDC → UART; 16,384 outputs, 0 mismatches vs. the model
  (`data/results/ddc_board.csv`); board build WNS +1.521 ns. `make board prog board-check` (claim the board first).
- Opening the serial port resets the board design; dumps carry a CRC-32 and the host skips cut-off ones.
- `gs-replay` (C++, `gs/`): 8-byte BE sequence + 512 cu8 samples per datagram (ADR 0009, `docs/protocol.md`).
  Loopback on the synthetic recording: 1× and 5× lossless and byte-exact (`data/results/gs_replay_loopback.csv`).
  `make gs gs-test`, in `make ci`. Not yet sent to the board (eth-core-v0.1).
- ILA: `make board ILA=1` + `make ila-capture`. All 16,384 DDC outputs captured over JTAG, 0 mismatches vs. the model
  (`data/results/ddc_board_ila.csv`); plot in `docs/media/`.
- README written to the §11.4 standard (2026-11-05); every number links to its CSV, unmeasured rows `[TBD]`.
- C++ static analysis: `make gs-lint` (clang-format, clang-tidy with warnings as errors, cppcheck), in `make ci`;
  `gs/` clean.
- Hosted CI: GitHub Actions runs `make ci` on every push in an `ubuntu:26.04` container, Verilator v5.050 cached.
  First run green 2026-11-05 (17 min, including the Verilator build).
- Not done: board photo (deferred by you); fuzzing (needs `gs-rx`'s parser, Phase F).

**Phase C: RTL started.**

- `rtl/sync/sync_rrc.sv`: the comp FIR reused with the 57 RRC taps (`rtl/sync/rrc_taps.mem`, generated from the
  model). 4,000 / 4,000 outputs bit-exact under backpressure; 62 clocks/sample, 6.3× real time
  (`data/results/rrc_rtl_sim.csv`). OOC 100 MHz WNS +2.453 ns, 616 LUT, 2 DSP (`data/results/synth_sync_rrc.csv`).
- Next: AGC RTL against `model/sync_fixed.py`, then Costas, then Farrow + Gardner.

## Next steps

1. **You:** capture a pass with the V3 + SAWbird+ (bias tee on, gain raised from low while watching the waterfall),
   or get a public 72k recording from the libre.space forum. Check the satellite is in 72k mode first.
2. Decode it with SatDump and list it in `data/MANIFEST.md` with the gain.
3. On the recording: confirm the spec, resolve which rail leads and which carries G1, and compare the model's CADUs
   with SatDump's.
4. **You:** install clang-format, clang-tidy, cppcheck and clang (libFuzzer), which need sudo, so C++ static analysis can run.
5. Phase B can't close until `gs-replay` runs over Ethernet to the board (eth-core-v0.1).
6. Phase C RTL: AGC → Costas → Farrow + Gardner, each bit-exact against `model/sync_fixed.py`.

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
| RTL streams carry `{Q, I}` in one beat; pipelines stall as a whole | One handshake per sample; no rail skew | `docs/design.md` |
| Board readout: UART dump with CRC-32, host skips bad dumps | A cut-off dump must not read as a DDC error | `docs/design.md` |
| RTL tables generated from the model, checked for staleness | One source of truth for NCO and FIR coefficients | `scripts/gen_rtl_tables.py` |
| IQ replay: 8-byte BE seq + 512 raw cu8 per datagram | Matches eth-core `rx_stats`; no host conversion; ≤ 5.69× on 100 Mb/s | ADR 0009 |
| ILA inserted in Tcl after synthesis, storage-qualified on the DDC handshake | RTL unchanged; 16,384 deep holds the whole snippet | `syn/impl_board.tcl` |
| Sync threshold 0.75; frames under the flywheel held until the lock is confirmed | Fixes false locks and duplicate frames | `model/receiver.py` |

## Open questions

- Board Ethernet from WSL2: UDP multicast may need mirrored networking mode. Test before Phase B.
- P2 gates (2026-11-04): `tb-common-v0.1` tagged and in use. `eth-core-v0.1` and `v0.2` not tagged: hardware
  testing from a BRAM ROM only, results over UART/ILA (CLAUDE.md, Dependencies on Project 2).
- Coarse estimate in hardware vs. on the host (ADR 0002). Decide in Phase C.
- What in the board resets the design when the serial port opens. Not established; harmless with the CRC.
