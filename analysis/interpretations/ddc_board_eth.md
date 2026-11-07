The DDC on the Arty A7-100T fed over Ethernet: gs-replay streams the same 65,536-sample snippet as the BRAM test
(`ddc_board.csv`) as 128 IQ replay datagrams (docs/protocol.md) through fpga-eth-core's eth_rx and udp_rx and
iq_udp_ingest into ddc_top, and the first 16,384 outputs are dumped over the UART. One row per replay; the FPGA is
reprogrammed before each one (opening the serial port does not reset it).

- `dump = yes, mismatches = 0`: every sample of every datagram reached the DDC once, in order and unaltered.
- `dump = yes, mismatches > 0`: all 65,536 samples arrived (the capture filled) but not in file order. On
  2026-11-07 each such dump was reproduced exactly by the bit-true model fed the snippet with datagrams reordered
  near the start of the replay (1,082 mismatches from output 5 = datagrams 0 and 1 swapped; 1,328 from output 6 =
  arrival order 2, 0, 1, 3; 1,112 from output 133 = 1 and 2 swapped). The ingest is first-in, first-out from the
  wire, so the order was already wrong on the cable: host-side reordering (WSL2 → Windows → I225 NIC), which
  fpga-eth-core also saw at high rates. Pinning gs-replay to one CPU made no difference (3 of 20 at 5.6×).
- `dump = no`: fewer than 65,536 samples reached the capture: at least one datagram lost, on the host or the link.
  Which, the board can't yet say: its gap and overflow counters reach the host only with the Phase E stats packet.

Faults appeared only near the link limit (5.69× is the ceiling from the format, docs/protocol.md); replays at 1×
and 5× were all bit-exact. This measures replays of a 64 ms snippet, not sustained loss over a full pass.
