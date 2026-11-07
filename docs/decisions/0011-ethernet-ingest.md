# 0011: Ethernet ingest: one 100 MHz core clock, datagrams committed whole

## Context

Phase B's last hardware step feeds the DDC from `gs-replay` over 100 Mb/s Ethernet (buildplan §9) through
fpga-eth-core (`rtl/eth`, submodule at `eth-core-v0.2`). Two choices: which clock the Ethernet core runs on, and
what the ingest does with a datagram that turns out bad (wrong length, or `udp_rx` flags it truncated) after some
of its samples have already arrived. The model comparison needs every sample index to stay `seq × 512`
(ADR 0009); one stray sample shifts every later output.

## Options considered

**Core clock**

| Option | Crossings | Timing | Notes |
|---|---|---|---|
| **One 100 MHz core domain from the MMCM** (eth-core, ingest, DDC, capture) | Only eth-core's own rx_clk FIFO | DDC and chain already met at 100 MHz OOC | eth-core needs only > 12.5 MB/s; its examples were timed at 125 MHz, so 100 MHz is easier |
| eth-core at 125 MHz (as in its examples), DDC at 100 MHz | + one async FIFO core → DDC | Both as already closed | A second crossing and a second FIFO to constrain, for no throughput gain: the link is the bottleneck |
| Everything at 125 MHz | Only eth-core's | The DDC, sync chain and Viterbi were closed at 100 MHz, unknown at 125 | Would reopen timing on every block |

**Bad datagrams**

| Option | RTL | Effect on the DDC |
|---|---|---|
| **Store each datagram in a block-RAM ring, release it on a good `tlast`, rewind on a bad one** | 1 RAMB18 (1,024 samples), three pointers | Sees whole datagrams only; a bad one is counted and absent, like a lost one |
| Pass samples through as they arrive, count bad datagrams | No buffer | A short or truncated datagram's samples reach the DDC; every later index is off |
| Rely on eth-core's store-and-forward | None | `frame_buffer` only drops frames with bad FCS; a well-formed frame with a 1,031-byte payload passes |

## Decision

One 100 MHz core domain (`rtl/lib/xilinx/clk_gen_eth.sv`: MMCM 1000 MHz VCO, /10 core, /40 PHY reference through
an ODDR). `rtl/io/iq_udp_ingest.sv` writes samples into a 1,024-sample ring as they arrive and moves the commit
pointer only when the datagram ends at exactly 1,032 bytes with `tuser` low; otherwise the write pointer returns to
the commit pointer. Only bytes that write a sample wait for room in the ring. The seq, I and surplus bytes are
always taken, so an over-long datagram's `tlast` (and its rewind) can't be blocked by its own samples. The first
simulation found exactly that deadlock at DEPTH = 512.

## Consequences

- The only clock crossings are inside eth-core (its async FIFO, with its scoped XDC) and the MAC reset into the
  rx_clk domain (`docs/design.md`).
- Ingest counters: datagrams released, dropped, sequence gaps, datagrams lost (`seq` jumps). Until the Phase E stats
  packet they are visible only as the sticky error LED (LD7) on `arty_ddc_eth_top`.
- Ingest output is at most one sample per 3 clocks (33 MS/s), against the link's 6.25 MS/s ceiling.
- A lost datagram is not filled in: the DDC sees the stream jump by 512 samples. Filling the gap with zeros or
  holding the NCO phase can come later if real replays show losses.

## Measured evidence

- `test_iq_udp_ingest.py` at DEPTH 1024 and 512: clean, damaged and out-of-sequence, and stalled-sink streams, with
  samples and counters exact against a model of docs/protocol.md. Six planted bugs (the original deadlock, no
  rewind, length off by one, I/Q swapped, loss count off by one, `tuser` ignored) each fail.
- `test_arty_ddc_eth_top.py`: MII pins to UART, DDC output equal to the bit-true model; bad-FCS and wrong-port
  frames don't reach the DDC.
- Hardware (`data/results/ddc_board_eth.csv`): 37 of 40 replays of the 65,536-sample snippet bit-exact at 1×, 5×
  and 5.6× real time. The other 3 lost a datagram (no dump) or received two datagrams swapped. The swap's dump
  equals the model's output for that order bit for bit, which shows the ingest released exactly what arrived, in
  arrival order. The second consequence above (no reordering, no gap fill) is now a measured limitation.
