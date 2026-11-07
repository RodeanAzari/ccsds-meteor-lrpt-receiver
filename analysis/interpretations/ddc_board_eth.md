The DDC on the Arty A7-100T fed over Ethernet: gs-replay streams the same 65,536-sample snippet as the BRAM test
(`ddc_board.csv`) as 128 IQ replay datagrams (docs/protocol.md) through fpga-eth-core's eth_rx and udp_rx and
iq_udp_ingest into ddc_top, and the first 16,384 outputs are dumped over the UART. One row per replay; the FPGA is
reprogrammed before each one (opening the serial port does not reset it) and the replay starts 3 s after the host
interface is back.

- `dump = yes, mismatches = 0`: every sample of every datagram reached the DDC once, in order and unaltered. This
  is the Phase B result: the board's DDC is bit-exact when fed over Ethernet, at 1×, 5× and 5.6× real time.
- `dump = yes, mismatches > 0`: all 65,536 samples arrived but not in file order. Each such dump checked on
  2026-11-07 equals the bit-true model fed the snippet with whole datagrams reordered: in this file, 1,034
  mismatches from output 13,059 = datagrams 102 and 103 swapped (bit for bit against the saved dump). Earlier
  campaigns the same day: 0 and 1 swapped (1,082 from output 5), arrival order 2, 0, 1, 3 (1,328 from output 6),
  1 and 2 swapped (1,112 from output 133). The data inside each datagram was intact and the board's path is
  first-in, first-out, so the order was already wrong on the cable: host-side reordering (WSL2, Windows, I225
  NIC), as fpga-eth-core also saw. Pinning gs-replay to one CPU did not help.
- `dump = no`: fewer than 65,536 samples reached the capture, so at least one datagram was lost. Where, the board
  can't yet say: its gap and overflow counters reach the host only with the Phase E stats packet. Across three
  campaigns every loss came on a replay whose link took >= 3.1 s to return after programming (the usual is
  2.3–2.9 s); a 3 s wait after the link returns did not remove them, and 15 reprogrammings all negotiated 100 Mb/s
  full duplex, none of them slow. Cause not established.

The faults are intermittent and not tied to replay speed (1×: 8/10 bit-exact, 5×: 9/10, 5.6×: 20/20 in this
campaign; an earlier one had 1× and 5× 10/10 and 5.6× 19/20). This is 40 replays of a 64 ms snippet, not sustained loss over a full pass.
