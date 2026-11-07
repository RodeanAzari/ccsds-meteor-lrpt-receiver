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
| 0 | `type`, u8 | 1 = stats. 2 = CADU `[TBD]` |
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
the first `n` fields it knows and ignores the rest. Fields, in order (`rtl/top/arty_ddc_eth_top.sv`):

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
| 15 | `ddc_out` | `ddc_top` | DDC output samples handed to the capture |
| 16 | `tx_underrun` | `eth_tx` | Transmit underruns (must stay 0) |

Packet size: 16 + 4 × 17 = 84 bytes. Parsed by `scripts/board_stats.py`.

## CADU (board → host), type 2

`[TBD]` (Phase E).

## Debug constellation samples (board → host)

`[TBD]`.

## Control commands (host → board)

`[TBD]`.
