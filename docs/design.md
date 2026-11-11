# Design summary

Architecture: CLAUDE.md §3. Fixed-point formats: `docs/fixed-point.md`. This file summarizes each decision record
and lists clock-domain crossings.

## Decisions

| ADR | Decision | Evidence |
|---|---|---|
| [0001](decisions/0001-nrzm-decoder.md) | NRZ-M decoder after Viterbi | SatDump pipeline; no ASM matches without it |
| [0002](decisions/0002-oqpsk-timing.md) | Carrier before OQPSK timing; host coarse estimate into the DDC NCO | `sync_loop_order.csv`, `sync_pull_in.csv` |
| [0003](decisions/0003-nco.md) | NCO: 32-bit phase, quarter-wave table, 12-bit table phase | `ddc_nco_sfdr.csv` |
| [0004](decisions/0004-cic.md) | CIC ÷4 order 3, 31-tap compensation FIR | `ddc_fixed_chain.csv` |
| [0005](decisions/0005-soft-decision-width.md) | 4-bit soft decisions, step 1/4 of rail rms | `soft_width_ber.csv` |
| [0006](decisions/0006-path-metric-normalization.md) | Modulo path metrics, 9 bits | `test_viterbi_fixed.py` |
| [0007](decisions/0007-survivor-memory.md) | Survivors in BRAM, per-bit sliding traceback | `test_viterbi_fixed.py` |
| [0008](decisions/0008-traceback-depth.md) | Traceback depth 96 from state 0 | `traceback_depth.csv` |
| [0009](decisions/0009-iq-transport-format.md) | IQ replay: 8-byte BE sequence + 512 raw cu8 samples per datagram | `gs_replay_loopback.csv` |
| [0010](decisions/0010-streaming-frame-sync.md) | Streaming frame sync: 4-bit correlation normalized over its own 52 symbols, 4-deep verify queue, slips followed within ±2 symbols; per-frame Viterbi windows from a 32k-symbol ring (amendment) | `framesync_fixed.csv` |
| [0011](decisions/0011-ethernet-ingest.md) | Ethernet ingest: one 100 MHz core domain; each datagram held in a BRAM ring and released only if whole | `test_iq_udp_ingest.py`, `ddc_board_eth.csv` |
| [0012](decisions/0012-rs-instance-count.md) | One fpga-rs-core RS decoder; deinterleave ×4 and re-interleave in one buffer around it | fpga-rs-core `docs/reports/ooc/` |
| [0013](decisions/0013-ingest-reorder-buffer.md) | Ingest reorder buffer: 4 datagram slots by `seq`, released in order; losses skipped, late datagrams dropped | `test_iq_udp_ingest.py` |
| [0014](decisions/0014-control-commands.md) | Control commands in-band on the replay port (byte 0 bit 7); SET_NCO accepted only before the DDC's first sample | `test_ctrl_rx.py`, `test_arty_rx_eth_top_full.py` |
| [0015](decisions/0015-space-packet-demux.md) | Space packets: SatDump's packets on unbroken streams; a packet crossing a counter gap or disagreeing with the first header pointer dropped and counted | `model/tests/test_space_packets.py` |
| [0016](decisions/0016-gs-view-status-snapshot.md) | gs-view draws a key=value snapshot gs-rx writes every 0.5 s (atomic rename); gs-rx stays the only receiver. No constellation (needs an RTL tap) or Viterbi corrections (not reported) in v1 | `gs/tests/view_test.cpp`, `gs/tests/test_rx_loopback.py` |

Still required (CLAUDE.md §5.5): interpolator type, Berlekamp–Massey variant, RS instance count, phase-ambiguity
strategy. The interpolator (Catmull-Rom cubic) and phase-ambiguity strategy (4 hypotheses on the
encoded ASM, `signal-spec.md`) are implemented in the model but have no ADR yet.

## Stream conventions (RTL)

- Every block is AXI4-Stream with `s_tdata_i/s_tvalid_i/s_tready_o` in and `m_tdata_o/m_tvalid_o/m_tready_i` out.
- I/Q travel together in one beat: `tdata = {Q, I}`, each rail at its `docs/fixed-point.md` width. The cu8 input is
  `{Q_u8, I_u8}`, the replay byte order (I, then Q) read as a little-endian 16-bit word.
- Blocks with internal pipelines advance all stages together on `ce = !m_tvalid || m_tready`; nothing is dropped.
- DDC chain (`rtl/ddc/ddc_top.sv`): `ddc_ingest` → `ddc_nco_mixer` → `ddc_cic` → `ddc_comp_fir`.
- Sync chain (`rtl/sync/sync_top.sv`, ADR 0002): `sync_rrc`, which is `ddc_comp_fir` with the 57 RRC taps (same arithmetic;
  one FIR to verify, not two) → `sync_agc` (one sample in flight, so the per-sample gain update lands before the
  next sample) → `sync_costas` (same structure; its own copy of the DDC's sine table, one RAMB18) → `sync_timing` (Farrow + per-rail Gardner;
  one output at a time, since each output's error sets the next position). The loop gains are `sync_top` ports
  (control registers later, CLAUDE.md §3.1). Three blocks accept input only with their output empty, so a stall
  anywhere propagates to `s_tready`; `test_sync_top.py` keeps the output slower than the chain to exercise that.
- Soft quantizer (`rtl/fec/fec_soft_quant.sv`): `{Q, I}` from `sync_top` → one u4 symbol per beat (I on even beats,
  Q on odd, counted from reset), pass-through handshake.
- Frame sync (`rtl/fec/fec_framesync.sv`, ADR 0010 and its amendment): `fec_fs_correlator` (4 encoded-ASM
  correlators + Σ|v|, transposed form, one add per register) → `fec_fs_fsm` (SEARCH/VERIFY/LOCK, 4-deep verify queue,
  5-position hit history for slips) → frame descriptors → `fec_fs_window` (32,768-symbol ring in 4 RAMB36; each frame
  read out as a derotated window [start − 128, start + F + 192), `tuser = {flywheel, swap, alternate}`, `tlast` at
  window end). Everything on the input side advances on the input handshake. The input stalls rather than overwrite
  a symbol the reader or the next window still needs; windows overlap, so the next window can be the older of the
  two.
- Viterbi decoder (`rtl/fec/fec_viterbi.sv`, ADRs 0005–0008): `fec_acs_array` (64 `fec_acs` on one `fec_bm`, one
  step per clock, trellis from the G1/G2 taps) → `fec_traceback` (256-row decision ring in one RAMB36, walks back
  `depth_i` rows from state 0 per output bit, depth + 3 clocks per bit). The traceback takes a row only between
  walks, so it stalls the array; the stall enable to the 576 path-metric flip-flops is the decoder's worst path.
- Chain after the DDC (`rtl/top/rx_chain.sv`): `sync_top` → `fec_soft_quant` → `fec_framesync` → `fec_viterbi`.
  The Viterbi has no reset between windows; the run-in absorbs the previous window's metrics
  (`framesync_fixed.decode_windows()`). The Viterbi takes no `tuser`/`tlast`, so the window flags and boundary end at
  the frame sync for now: Phase E carries them past it (frame = bits PRE/2 .. PRE/2 + 8,191 of each 8,352-bit window).

## Clock-domain crossings

The ROM top is single-clock (100 MHz, `clk100_i`); the Ethernet top's core domain is 100 MHz from the MMCM
(`rtl/lib/xilinx/clk_gen_eth.sv`, ADR 0011), plus the PHY's 25 MHz `eth_rx_clk_i` inside fpga-eth-core's `eth_rx`.

| Signal | From | Synchronizer | XDC |
|---|---|---|---|
| `ck_rst_n_i` (RESET button) | asynchronous | `rtl/lib/reset_sync.sv`: async assert, 3-flop sync deassert | `set_false_path -from` in `constr/arty_a7_100t.xdc` |
| `btn0_i` (BTN0) | asynchronous | `rtl/lib/cdc_sync_bit.sv`: 2-flop, `ASYNC_REG` | `set_false_path -from` in `constr/arty_a7_100t.xdc` |
| MMCM `locked` (Ethernet top) | asynchronous | `reset_sync` `u_rst_core`, with the button | not a timed path |
| MII bytes, rx_clk → core | `eth_rx_clk_i` | fpga-eth-core `async_fifo` (Gray pointers, formally proven) | eth-core's `constr/async_fifo.xdc`, read scoped to `async_fifo` |
| MAC reset request, core → rx_clk | `mac_rst_q` | `reset_sync` `u_rst_mii` (async assert, sync deassert) | `set_false_path -to` its `PRE` pins, `constr/arty_eth.xdc` |

## Board bring-up (Phase B, no Ethernet)

`rtl/top/arty_ddc_rom_top.sv`: `iq_rom_source` (64 K-sample cu8 snippet in BRAM) → `ddc_top` → `capture_dump`
(16 K-word BRAM) → `uart_tx` (115,200 baud). Dump format: `"DDC1"` | u32 n | n × u32 `{Q, I}` | u32 CRC-32, all
little-endian. **Opening the board's serial port reset the design** and started a dump on 2026-11-04 (mechanism not
established), so the host discards any dump whose CRC fails. On 2026-11-07 it did *not* reset `arty_ddc_eth_top`
(see below). `make board prog board-check`.

Over Ethernet (`rtl/top/arty_ddc_eth_top.sv`, ADR 0011): MII → fpga-eth-core `eth_rx` → `udp_rx` (239.1.1.1:26400)
→ `iq_udp_ingest` (docs/protocol.md datagrams → `{Q_u8, I_u8}`, whole datagrams only) → the same `ddc_top`,
`capture_dump` and dump format. The capture fills from the replay, not on reset. Opening the serial port did not
reset this design (a second replay got no dump, the capture still full), so `eth-check` reprograms the FPGA before
each replay, waits until the link is back (~2.6 s; the host interface loses its address meanwhile), opens the port
and runs `gs-replay`. `make board BOARD_TOP=arty_ddc_eth_top`, `prog`, `eth-check`.

The whole receiver (`rtl/top/arty_rx_eth_top.sv`) keeps that Ethernet plumbing and replaces the capture with `rx_chain`:
`iq_udp_ingest` → `ddc_top` → `rx_chain` → `cadu_packet` (type 2) and `stats_packet` (type 1, fields 18–28 added) → `pkt_arb2`
(whole packets, round robin; eth-core's `udp_tx` takes one payload per tlast and has no arbiter) → `udp_tx`. No new
clock crossing. The NCO word (the host's coarse estimate) is set per replay by a SET_NCO command on the replay port,
read by `ctrl_rx` and accepted only before the DDC's first sample (ADR 0014); loop gains, threshold, flywheel and traceback depth come from
`rx_config_pkg.sv`, generated from the model. Nothing is dropped inside: a slow stage stalls back to the ingest ring,
and past it eth_rx counts lost frames. `make board BOARD_TOP=arty_rx_eth_top`, `rx-check`.
The Ethernet start-up and the request-0005 stopgap are duplicated from `arty_ddc_eth_top`: fold both into one
shared block when P2's fix lands and the stopgap goes.
