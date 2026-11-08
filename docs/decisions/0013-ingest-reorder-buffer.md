# 0013: Ingest reorder buffer

## Context

ADR 0011's ingest released datagrams in arrival order. On hardware the host's network stack (WSL2 → Hyper-V →
NIC) swaps datagrams now and then: 3–21 times per 34 s replay at 5×–5.6×, 0–12 at 1× (`board_rx_eth.csv`,
2026-11-08). The datagrams all arrive; they are just out of order. Each swap moves 512 samples (0.5 ms) to the wrong
place, a burst of bit errors after the Viterbi. In the first receiver campaign RS repaired all of them in 15
replays (0 corrections in every replay without a swap, 9–84 with), but one earlier replay lost a frame to them. For
the BER campaign (buildplan §8.4) they are worse: a few hundred bit errors per replay regardless of Eb/N0, a floor
of roughly 1e-5 to 1e-4 under the pre-RS curve, right where the Viterbi curve has to be measured. The BER campaign
needs 5.6× replays to finish in reasonable time, and at that speed every replay so far reordered.

## Options considered

| Option | Cost | Effect |
|---|---|---|
| **Reorder buffer in the ingest: slots addressed by `seq`, released in `seq` order** | 1 RAMB36 (4 slots, was 1 RAMB18), a `seq`-wide head and compare | Swaps within 4 datagrams vanish; a loss is skipped once a datagram 4 further on arrives; late and duplicate datagrams dropped and counted |
| Discard replays with `ingest_gap > 0`, rerun | None in RTL | Honest, but at 5.6× almost every replay is discarded: the campaign runs at 1×, several hours per sweep |
| Fix the host (WSL mirrored networking, `gs-replay` on Windows) | Host setup, partly manual | Unknown whether it stops the swaps; real-pass replays from WSL keep the problem |
| Fill or flag: mark CADUs that overlap a swapped datagram, exclude them from BER | CADU status bits, host bookkeeping | Biases the BER sample towards frames that weren't disturbed; doesn't help real-pass decoding |

## Decision

`rtl/io/iq_udp_ingest.sv`: the ring holds `DEPTH / 512` slots (default 2048 samples = 4 slots); datagram `seq`
lives in slot `seq mod 4`. A good datagram inside the window `[head, head + 4)` is written into its slot and marks
it valid; the reader releases valid slots in `seq` order from `head`. A datagram beyond the window waits on its first
sample byte while the head is released (if it arrived) or skipped as lost (if not). Late datagrams (behind `head`)
and duplicates (slot already valid) are consumed and dropped. Bad datagrams never mark their slot, so no rewind is
needed. Lost datagrams are still not filled in (ADR 0011).

Counters: `ingest_gap` keeps its arrival-order meaning (placed `seq` ≠ previous placed + 1), `ingest_lost` now counts
skipped datagrams instead of forward jumps, and `ingest_late` (stats field 25, receiver top only) counts the dropped
ones. Because field 3's meaning changed, stats packets are version 2 (`docs/protocol.md`).

Window size: the swaps seen were adjacent, with occasional jumps of two (`ingest_lost` slightly above `ingest_gap`
/ 2 in the old counters). Four slots cover that with margin in one RAMB36.

## Consequences

- A datagram lost near the end of a replay holds the ones after it (at most 3) until a datagram 4 further on
  arrives, which at the end of a file never happens: up to 1.5 ms of the tail is not released. A timeout could
  release them; not worth it for a replay's last milliseconds.
- `gap_cnt` is no longer an error by itself: the receiver top's LD7 lights on `lost` instead.
  `arty_ddc_eth_top` keeps `gap` on LD7 (its replays are 65,536-sample snippets checked bit for bit).
- Ingest throughput is unchanged (one sample per 3 clocks).

## Measured evidence

- `test_iq_udp_ingest.py` at 4, 2 and 1 slots against `ingest_model` (written from these rules): clean stream,
  damaged datagrams, the host's swap pattern released in file order (4 slots: 0 lost), a loss skipped and the late
  arrival dropped, a late repeat after its slot drained, stalled sink. Six planted bugs (duplicates not detected,
  skipped datagrams not counted, window off by one, gap counted against the release pointer, head slot never freed,
  late datagrams placed) each fail. The last one only failed at 4 slots once the late repeat arrived after its slot
  had drained; the first version of that test let it pass.
- `test_arty_ddc_eth_top.py`, `test_arty_rx_eth_top_full.py`: board tops with the new ingest.
- Hardware: `[TBD]` (receiver campaign rerun at 5.6×, expected RS corrections 0 in every replay).
