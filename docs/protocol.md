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
- **Gaps:** the receiver counts `seq` jumps (CLAUDE.md §3 INGEST gap counter). A gap of *g* datagrams is `512 g`
  lost samples. The host sends whole datagrams only; a final partial datagram is not sent, and `gs-replay` reports
  it on stderr.
- **Rate:** 2,000 datagrams/s at 1.024 MS/s real time. On the wire, 1,032 B of payload costs 1,098 B with
  UDP/IP/Ethernet headers, FCS, preamble and inter-frame gap, so 100 Mb/s carries at most 100 / (1,098 × 8 × 2,000)
  ≈ 5.69× real time. This is arithmetic from the format, not a measurement.
- **BER-campaign injection at the RRC input (§8.4):** a separate format and port, `[TBD]` until Phase D/E.

## CADU + stats (board → host)

`[TBD]` (Phase E; needs eth-core-v0.2).

## Debug constellation samples (board → host)

`[TBD]`.

## Control commands (host → board)

`[TBD]`.
