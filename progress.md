# Progress

Current state, next steps and key decisions only (≤ 150 lines). Measurements live in the README Results table and
`data/results/`; history in `docs/log.md`; rationale in `docs/decisions/`.

## Where things stand

- **Phase 0:** `docs/signal-spec.md` written from SatDump 1.2.2 source; **nothing confirmed on a real signal yet**.
  Kit (RTL-SDR Blog V3 + SAWbird+ NOAA) arrives about 2026-11-25.
- **Phase A:** float and bit-true models complete through the Viterbi on synthetic signals (BER matches theory;
  SatDump decodes our synthetic recording with every frame matching). Needs a real recording.
- **Phase B: DONE 2026-11-07** (tag `v0.1-ddc`). DDC bit-exact on the board from BRAM and over Ethernet (37/40
  replays; host-side losses/reordering open, see Open questions). Fuzzing moves with `gs-rx` to Phase F.
- **Phase C:** sync chain in RTL (`rtl/sync/sync_top.sv`: RRC → AGC → Costas → Farrow/Gardner), every block and the
  chain bit-exact in simulation, OOC 100 MHz met. `make sim-full` decodes the chain's output from reset: first CADU
  out of RTL. Lock range ±15 kHz (set by the coarse estimator's window), lock in 16–35 ms, Doppler tracking 0.84 Hz
  rms; plots and GIF done (`make sync-lock-study`, `make plots`). **Not done:** locking on a real recording.
- **Phase D:** Viterbi decoder RTL (`rtl/fec/fec_viterbi.sv`) bit-exact with the model, errors included; 96
  clocks/bit (14.5× real time); OOC 100 MHz met. Soft quantizer (`fec_soft_quant`) and frame sync
  (`rtl/fec/fec_framesync.sv`: correlators → FSM → 32k-symbol ring sending per-frame Viterbi windows, ADR 0010
  amendment) match the model window for window in 13 cocotb scenarios; OOC 100 MHz met (+0.653 ns, 3,112 LUT,
  4 RAMB36). Chain `rtl/top/rx_chain.sv` (sync_top → quant → framesync → viterbi): `make sim-full` decodes 5 frames
  from a cold start, every bit equal to the model (`decode_windows()`), 3/3 frames as sent; OOC +0.827 ns, 6,750 LUT.
  `docs/viterbi.md` written; 3-bit area measured (4-bit stands). Path-metric formal: stall hold proven, bound holds
  8 steps from reset; **unbounded proof open** (k-induction > 6.5 h). **Not done:** hardware BER.
- **Phases E–F:** not started in RTL (RS, `gs-rx`/`gs-diff`/`gs-view`). eth-core TX (`v0.2`) is in the submodule
  for the return path.

Traps to remember (beyond CLAUDE.md §12):
- Traceback depth is 96 from state 0 (ADRs 0007, 0008), outside buildplan §3.6's 35–50, which assumes a best-state
  start. Deliberate.
- Costas pull-in is slow at bw 0.001: within one frame up to ~100 Hz, 0.9 s or never at 300 Hz
  (`sync_lock_costas.csv`). The host coarse estimate must leave ≲ 100 Hz; it leaves ~15 Hz (ADR 0002).
- The AGC gain step has a ±25% power dead zone (`docs/fixed-point.md`).
- A cold start (AGC from gain 1.0, loops from zero) costs 40,000–60,000 DDC-rate samples before the first frame
  decodes (scratch model run, not a committed result).

## Next steps

1. **You:** capture a pass with the V3 + SAWbird+ (bias tee on, gain raised from low while watching the waterfall),
   or get a public 72k recording from the libre.space forum. Check the satellite is in 72k mode first.
2. Decode it with SatDump; list it in `data/MANIFEST.md` with the gain.
3. On the recording: confirm the spec, resolve which rail leads and which carries G1, compare the model's CADUs with
   SatDump's.
4. Phase D: hardware BER (Ethernet replay works now). Phase E's first job:
   carry the window `tuser`/`tlast` past the Viterbi (they end at `fec_framesync` today); frame = bits PRE/2 ..
   PRE/2 + 8,191 of each 8,352-bit window.
5. Phase E: the stats packet (ingest gap/bad/lost counters, eth-core error counters) back over eth-core TX; that
   also says where the intermittent replay losses happen.
## Key decisions

| Decision | Why | Where |
|---|---|---|
| Add an NRZ-M decoder after Viterbi | SatDump's pipeline uses it; without it no ASM matches | ADR 0001 |
| Drop the dual-basis RS stage | The pipeline sets `rs_dualbasis: false` | `docs/signal-spec.md` |
| Search {0°, 90°} × swap on absolute correlation | NRZ-M makes 180° irrelevant | `docs/signal-spec.md` |
| `gs-diff` compares the 892 data bytes only | SatDump leaves channel errors in parity and ASM | `docs/signal-spec.md` |
| Carrier before timing; coarse fourth-power estimate first | Timing first fails on OQPSK; narrow loops pull in too slowly | ADR 0002 |
| Host coarse estimate goes into the DDC NCO word | No FFT hardware; the RRC sees a centred signal | ADR 0002, `docs/fixed-point.md` |
| AGC on I²+Q² power, target rail rms 4096 | Steady state equals the float chain's unit-power normalization | `docs/fixed-point.md` |
| 4-bit soft, step ONE/4 | 0.11 dB better than 3-bit at 1e-5 for one bit per metric | ADR 0005 |
| Modulo path metrics, 9 bits | No normalization logic in the ACS loop | ADR 0006 |
| Traceback 96 deep from state 0, BRAM | Matches full-block BER; no 64-way minimum | ADRs 0007, 0008 |
| Costas 0.001 rad/sample, timing kp 0.02 | Measured sweeps | `data/results/sync_*.csv` |
| RTL streams carry `{Q, I}` in one beat; pipelines stall as a whole | One handshake per sample; no rail skew | `docs/design.md` |
| Loop blocks (AGC, Costas, timing) keep one sample/output in flight | Each update depends on the previous output | `docs/design.md` |
| Board readout: UART dump with CRC-32, host skips bad dumps | Opening the serial port sometimes resets the design | `docs/design.md` |
| RTL tables generated from the model, checked for staleness | One source of truth for NCO and FIR coefficients | `scripts/gen_rtl_tables.py` |
| IQ replay: 8-byte BE seq + 512 raw cu8 per datagram | Matches eth-core `rx_stats`; ≤ 5.69× on 100 Mb/s | ADR 0009 |
| ILA inserted in Tcl after synthesis, storage-qualified | RTL unchanged; 16,384 deep holds the whole snippet | `syn/impl_board.tcl` |
| Sync threshold 0.75; flywheel frames held until lock confirmed (float model) | Fixes false locks and duplicate frames | `model/receiver.py` |
| RTL frame sync is causal: local-normalized correlation, verify queue, delay line, slips followed ±2 | Finds ≥ the float model's frames | ADR 0010 |
| RTL frame sync sends each frame as its own window [s − 128, s + F + 192) from a 32k-symbol ring | Matches the model's frames through slips; last bit flushes inside the window | ADR 0010 amendment |
| `make sim` < 5 min; long runs in `make sim-full`, recorded by `*-rtl-results` | Fast regression; no skipped tests in `make sim` | `tb/cocotb/run.py` |
| Ethernet core on the 100 MHz core clock; ingest releases whole datagrams only | One crossing (eth-core's); DDC indices stay seq × 512 | ADR 0011 |
| RTL Viterbi never resets between windows; the run-in absorbs the jump | No per-window control; model matches it | `framesync_fixed.decode_windows()` |

## Open questions

- Board Ethernet from WSL2: UDP multicast may need mirrored networking mode. Test when `eth-core-v0.1` lands.
- Coarse estimate in hardware vs. on the host (ADR 0002). Decide in Phase C.
- Why opening the serial port reset the design on 2026-11-04 but not on 2026-11-07. Not established; `eth-check`
  reprograms instead.
- `make sim` without `test_fec_framesync` (now `make sim-slow`, in `make ci`): re-time on a quiet machine (expected
  ~260 s: 356 − 98).
- Intermittent replay faults (3 of 40): datagrams reordered on the host (proven by the model) or lost (cause open).
  Real-pass replays need the board's gap counter in the stats packet. Reordering buffer in the ingest: only if
  real replays need it.
- `make formal` in CI (buildplan §6 lists it): ~25 min and oss-cad-suite in the container. Local only for now; your call.
