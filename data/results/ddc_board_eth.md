# ddc_board_eth

- **Commit:** `4462a517adccd3911c6695ece9a6105c19b48d3e`
- **Command:** `PYTHONPATH=. python scripts/ddc_board.py eth-check /dev/ttyUSB1 --iface 169.254.235.36 --speed 1,1,1,1,1,1,1,1,1,1,5,5,5,5,5,5,5,5,5,5,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6,5.6 --bit build/board/arty_ddc_eth_top.bit`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, snippet seed 2026, 8.0 dB, carrier 151 kHz (scripts/ddc_board.py), streamed by gs-replay (achieved_speed: its own report) over 100 Mb/s Ethernet to arty_ddc_eth_top on the Arty A7-100T (fpga-eth-core eth-core-v0.2), one replay per row, each after a reset. No real recording.

The DDC on the Arty A7-100T fed over Ethernet: gs-replay streams the 65,536-sample snippet (as in `ddc_board.csv`)
as 128 IQ replay datagrams (docs/protocol.md) through fpga-eth-core's eth_rx and udp_rx and iq_udp_ingest into
ddc_top; the first 16,384 outputs are dumped over the UART. One row per replay, the FPGA reprogrammed before each.
The counter columns are the board's own stats packet (docs/protocol.md "Stats") read after the replay.

- `dump = yes, mismatches = 0`: every sample of every datagram reached the DDC once, in order and unaltered.
- `dump = yes, mismatches > 0`, Ethernet counters clean, `ingest_gap > 0`: the board received every datagram
  intact but out of order, so the order was wrong before the cable (WSL2, Windows, I225 NIC). An adjacent swap
  shows as gap 3, lost 2; the 1,112 mismatches from output 133 are the bit-true model's output for datagrams 1 and
  2 swapped (matched bit for bit on 2026-11-07). The ingest releases datagrams in arrival order (ADR 0011).
- `dump = no`: the capture never filled. In earlier campaigns every such case was eth_rx's RX FIFO corrupted at
  PHY link-up (level 4,095 > its 2,048-byte depth, then garbage on every cycle; fpga-coord request 0005), each
  after a link-up >= 3.1 s. This build detects that state and restarts the MAC alone (`mac_restarts`); in this
  campaign no link-up took longer than 2.6 s, `mac_restarts` stayed 0 and no replay lost a datagram, so the
  stopgap was not exercised on hardware (it is tested in simulation).

40 replays of a 64 ms snippet; not sustained loss over a full pass.
