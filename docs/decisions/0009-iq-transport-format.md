# 0009: IQ transport: 512 raw cu8 samples per datagram behind a 64-bit big-endian sequence

## Context

`gs-replay` streams a recording to the Arty over UDP (CLAUDE.md §2.4 stage 4, §4). The receiver must detect lost
datagrams (the ingest gap counter, §3) and the DDC must see exactly the file's bytes, or the board can't be
bit-exact against the model. The link is 100 Mb/s MII; real time is 16.384 Mb/s of IQ. Until eth-core-v0.1 is tagged
the board side doesn't exist, so the format should also be testable with fpga-eth-core's own `rx_stats` harness,
whose payload contract is "bytes 0–7: big-endian sequence, +1 per datagram".

## Options considered

| Option | Wire efficiency | RTL cost | Notes |
|---|---|---|---|
| **8-byte BE sequence + 512 cu8 samples (1,032 B)** | 93.99% (1,032 / 1,098 B on the wire), ≤ 5.69× real time | Fixed length; sample count a power of two | Matches `rx_stats` byte for byte; `seq × 512` is the sample index |
| 8-byte sequence + 728 samples (1,464 B, fills the frame) | 95.7%, ≤ 5.81× | Non-power-of-two count | +0.1× headroom; awkward index math |
| 4-byte sequence + magic/version/count header | Same or worse | Header parsing in RTL | A 32-bit sequence wraps after 24 days at 1×: harmless, but doesn't match `rx_stats` |
| Convert to signed or 16-bit samples on the host | 47% at 16-bit | Removes the ingest subtract | Doubles the bytes; the host would alter the data the model was checked on |

## Decision

8-byte big-endian sequence, then 512 cu8 samples exactly as in the file: 1,032 bytes per datagram, fixed. Spec in
`docs/protocol.md`. No magic or version field: the group/port filter in `udp_rx` already selects the stream, and the
fixed length rejects anything else.

## Consequences

- fpga-eth-core's `rx_stats` example can soak-test the replay path with no changes, once eth-core-v0.1 exists.
- Headroom over real time on the link is 5.69× at most (arithmetic, `docs/protocol.md`). That caps a hardware BER
  campaign fed through the DDC; the injection-mux format at 256 kS/s (§8.4) is separate and `[TBD]`.
- A recording's last partial datagram (< 512 samples, < 0.5 ms) is not sent; `gs-replay` says so on stderr.
- `gs-replay` paces each datagram to an absolute deadline computed from its index, so jitter doesn't accumulate.
  A datagram sent late is followed by catch-up sends closer together than one period, so the board's RX FIFO
  absorbs short bursts.

## Measured evidence

`data/results/gs_replay_loopback.csv` (`make gs-replay-results`): host loopback only, synthetic recording. At 1× and
5×, all 68,266 datagrams arrived in order and the payload was byte-identical to the file. Flat-out (61–124× on loopback across runs)
overran the Python receiver used to measure it. The link to the Arty is unmeasured until eth-core-v0.1.
