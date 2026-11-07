# 0012: Reed-Solomon: one fpga-rs-core decoder, deinterleaving outside it

## Context

Each CADU carries four RS(255,223) codewords interleaved at depth 4: codeword b, byte n sits at offset 4 + 4n + b
(`docs/signal-spec.md`). buildplan §3.7 asks for four decoder instances or one time-multiplexed one. The decoder
comes from fpga-rs-core at `rs-core-v1.0` (git submodule `rtl/rs/`), which P3 owns and P4 also uses for KP4. It
takes one symbol per clock, codewords in sequence, and passes an uncorrectable codeword through unchanged with a
fail flag (fpga-rs-core ADR 0001).

The rate it must keep up with is set by the Viterbi: about 96 clocks per decoded bit (`docs/viterbi.md`), so a
1,024-byte CADU arrives every 8,352 × 96 ≈ 802,000 clocks (one Viterbi window per frame).

## Options considered

| Option | Area (OOC, fpga-rs-core reports) | Time per CADU | Notes |
|---|---|---|---|
| Four instances, one per interleave branch | 4 × 4,142 LUT, 4 × 1.5 BRAM36 | ~800 clocks | Needs no deinterleave buffer, but each instance idles > 99.9% of the time |
| **One instance; deinterleave buffer in, re-interleave buffer out** | 4,142 LUT, 1.5 BRAM36, plus two 1 KB buffers (1 BRAM18 each) | ~4 × 255 + ~800 latency ≈ 1,900 clocks | 0.24% of the time between CADUs |
| One instance fed in arrival order | Same | n/a | Not possible: consecutive bytes belong to different codewords |

## Decision

One `rs_decoder` (M = 8, poly 0x187, FCR 112, PRIM 11, NROOTS 32, N 255), in `fec_rs_ccsds`:

1. The 1,020 body bytes of a frame, already derandomized, are written into a buffer in arrival order.
2. They are read out codeword by codeword (address 4n + b for b = 0..3, n = 0..254) into the decoder.
3. The decoder's output is written back at the same addresses, so the buffer again holds the CADU body in
   transmission order, now corrected. It is read out after the 4 ASM bytes as one 1,024-byte CADU.
4. Per codeword, `{fail, corrected}` from the decoder's `tuser` goes into the frame's status. An uncorrectable
   codeword stays as received, as SatDump leaves it.

One frame at a time: the next frame's bits wait (backpressure into the Viterbi) until the previous CADU has gone
out. At ~1,900 clocks against ~802,000 between frames, this never stalls the Viterbi unless the output is blocked.

## Consequences

- Dual-basis conversion is not needed (`docs/signal-spec.md`: the pipeline sets `rs_dualbasis: false`).
- The derandomizer runs before the RS buffer, bit-serially as the frame arrives (the model's order:
  `model/receiver.py` `decode_frames()`).
- If the Viterbi is ever made faster than ~2 clocks per bit, a second buffer (ping-pong) is needed.

## Measured evidence

- fpga-rs-core `rs-core-v1.0`: CCSDS suite bit-exact, OOC 100 MHz +1.457 ns, 4,142 LUT, 1.5 BRAM36
  (fpga-rs-core `docs/reports/ooc/rs_decoder_ccsds/`).
- Chain throughput and area of `fec_rs_ccsds`: `[TBD]`.
