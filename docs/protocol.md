# Packet formats

Single source of truth for the RTL and the C++ ground station (CLAUDE.md §3.1). All multi-byte integers are
big-endian. Formats not yet defined are marked `[TBD]`.

## IQ replay (host → board), ADR 0009

One UDP datagram carries 512 consecutive samples of the recording.

| Bytes | Field | Notes |
|---|---|---|
| 0–7 | `seq`, u64 big-endian | 0 for the first datagram of a replay, +1 per datagram. The first sample's index in the file is `seq × 512` |
| 8–1031 | 512 samples, cu8 | Exactly the file's bytes: I, Q, I, Q, … unsigned 8-bit, midpoint 127.5. No conversion on the host |

- **Length:** always 1,032 bytes. A datagram of any other length is malformed. One datagram fits one untagged
  Ethernet frame (UDP payload ≤ 1,472 B), so it is never fragmented.
- **Destination:** default `239.1.1.1:26400`, the group and port of fpga-eth-core's `examples/rx_stats`, whose payload
  contract (bytes 0–7 a big-endian sequence, +1 per datagram) this format satisfies. Both are `gs-replay` options.
- **Receiver:** `rtl/io/iq_udp_ingest.sv` (ADR 0011). It releases a datagram's samples only if the datagram is exactly
  1,032 bytes and `udp_rx` did not flag it truncated; otherwise none of them reach the DDC and it is counted as bad.
  The first expected `seq` after reset is 0.
- **Gaps:** the receiver counts `seq` jumps (CLAUDE.md §3 INGEST gap counter). A gap of *g* datagrams is `512 g`
  lost samples. The host sends whole datagrams only; a final partial datagram is not sent, and `gs-replay` reports
  it on stderr.
- **Rate:** 2,000 datagrams/s at 1.024 MS/s real time. On the wire, 1,032 B of payload costs 1,098 B with
  UDP/IP/Ethernet headers, FCS, preamble and inter-frame gap, so 100 Mb/s carries at most 100 / (1,098 × 8 × 2,000)
  ≈ 5.69× real time. This is arithmetic from the format, not a measurement.
- **BER-campaign injection at the RRC input (§8.4):** a separate format and port, `[TBD]` until Phase D/E.

## Board → host packets: common header

Every board → host datagram starts with this 16-byte header. All fields big-endian.

| Bytes | Field | Notes |
|---|---|---|
| 0 | `type`, u8 | 1 = stats. 2 = CADU |
| 1 | `version`, u8 | 1. Changes only if existing fields change meaning; new fields are appended, never reordered |
| 2–3 | `n`, u16 | Number of u32 fields after the header (stats) or payload bytes (other types) |
| 4–7 | `pkt_seq`, u32 | Packets of this type sent since reset, starting at 0 |
| 8–15 | `uptime`, u64 | Core clock cycles (100 MHz) since the MAC left reset, sampled when the packet starts |

- **Addressing:** to the MAC and IP that sent the most recent good IQ replay datagram (learned, no ARP), UDP
  destination port **26401**, source port 26400, source IP 192.168.10.2 (fpga-eth-core's example address, so its
  documented Hyper-V firewall rule for WSL2 also admits these). Nothing is sent before the first replay datagram.

## Stats (board → host), type 1

Sent every 100 ms (`STATS_PERIOD`) once a replay sender is known. Payload: `n` u32 counters, cumulative since reset,
modulo 2³², snapshotted together on the packet's first byte, so one packet is self-consistent. The receiver uses
the first `n` fields it knows and ignores the rest. Fields, in order: 0–17 from both Ethernet tops
(`rtl/top/arty_ddc_eth_top.sv`, `n` = 18), 18–24 appended by the receiver top (`rtl/top/arty_rx_eth_top.sv`, `n` = 25):

| # | Field | Source | Meaning |
|---|---|---|---|
| 0 | `ingest_ok` | `iq_udp_ingest` | Replay datagrams released to the DDC |
| 1 | `ingest_bad` | `iq_udp_ingest` | Datagrams dropped: wrong length or truncated |
| 2 | `ingest_gap` | `iq_udp_ingest` | Good datagrams whose `seq` was not the expected one |
| 3 | `ingest_lost` | `iq_udp_ingest` | Sum of forward `seq` jumps: datagrams that never arrived |
| 4 | `eth_ok` | `eth_rx` | Frames with good FCS |
| 5 | `eth_crc_err` | `eth_rx` | Frames with bad FCS |
| 6 | `eth_rx_err` | `eth_rx` | Frames with `rx_er` or an odd nibble count |
| 7 | `eth_runt` | `eth_rx` | Frames under 64 bytes |
| 8 | `eth_oversize` | `eth_rx` | Frames over 1,518 bytes |
| 9 | `eth_ovf_lost` | `eth_rx` | Frames lost to RX FIFO overflow |
| 10 | `udp_ok` | `udp_rx` | Datagrams delivered for 239.1.1.1:26400 |
| 11 | `udp_filtered` | `udp_rx` | Frames for other addresses or ports (not errors) |
| 12 | `udp_ip_csum_err` | `udp_rx` | Bad IPv4 header checksum |
| 13 | `udp_malformed` | `udp_rx` | Malformed IPv4/UDP |
| 14 | `rx_fifo_hwm` | `eth_rx` | RX async FIFO high-water mark, bytes (a level, not a count) |
| 15 | `ddc_out` | `ddc_top` | DDC output samples handed on (to the capture, or to `rx_chain`) |
| 16 | `tx_underrun` | `eth_tx` | Transmit underruns (must stay 0) |
| 17 | `mac_restarts` | top | Times the MAC was put through reset again because the RX FIFO level read above its depth (request 0005 stopgap). **Not reset by a MAC restart**, unlike fields 0–16 |
| 18 | `cadus_sent` | top | CADU packets (type 2) handed to `udp_tx` |
| 19 | `fs_locked` | `fec_framesync` | 1 while the frame sync is locked (a level, not a count) |
| 20 | `fs_dropped` | `fec_framesync` | Correlation peaks dropped because the verify queue was full |
| 21 | `fs_slips` | `fec_framesync` | Hypothesis or position switches while locked |
| 22 | `fs_early` | `fec_framesync` | Frames not emitted: their Viterbi run-in would start before the first symbol |
| 23 | `flag_ovf` | `fec_frame_extract` | Window-flag FIFO overflows (must stay 0) |
| 24 | `len_err` | `fec_cadu` | Frames whose `tlast` disagreed with the 8,192-bit count (must stay 0) |

Packet size: 16 + 4 × `n` bytes (88 or 116). Parsed by `scripts/board_stats.py`.

## CADU (board → host), type 2

One packet per CADU out of `fec_cadu` (`rtl/fec/fec_cadu.sv`, ADR 0012), in decode order. `n` = 1,032 payload bytes;
UDP payload 16 + 1,032 = 1,048 bytes. `pkt_seq` counts CADUs sent, so a gap in it means a packet lost between the
board and the host (the board never drops one: the chain stalls instead). `uptime` is sampled at the packet's
first byte, after RS.

| Bytes | Field | Notes |
|---|---|---|
| 0 | `flags`, u8 | bit 0 `alternate`, bit 1 `swap` (phase hypothesis the frame sync locked to), bit 2 `flywheel` (frame emitted under a missed ASM); bits 7–3 zero |
| 1 | `asm_errors`, u8 | Bit errors in the received ASM, 0–32, after Viterbi and NRZ-M |
| 2–5 | `rs[0..3]`, u8 each | Codeword b (bytes 4 + 4n + b of the CADU): bit 7 `fail` (uncorrectable: left as received), bits 4–0 symbols corrected, 0–16 (0 when `fail`); bits 6–5 zero |
| 6–7 | reserved | Zero |
| 8–1,031 | `cadu`, 1,024 bytes | ASM as received, then the body derandomized and RS-corrected per codeword. Same bytes as the model's `RxResult.cadus` and SatDump's output data bytes 4–895 (`docs/signal-spec.md`: SatDump leaves parity errors in place, so compare the 892 data bytes) |

The status fields are `fec_cadu`'s `m_tuser` (`model/cadu_fixed.py` `CaduOut.status_word()`), repacked into bytes.

## Debug constellation samples (board → host)

`[TBD]`.

## Control commands (host → board)

`[TBD]`.
