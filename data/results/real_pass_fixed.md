# real_pass_fixed

- **Commit:** `09999dcc163ca82416e5a65ddef4624d439b2d27`
- **Command:** `python -m real_pass_study /home/rodea/recordings/2026-11-21T1943Z_meteor-m2-4_part2.cu8 /home/rodea/recordings/2026-11-21_satdump/meteor_m2-x_lrpt.cadu --start-utc 2026-11-21T19:37:51 --from-s 240 --to-s 1350 --jobs 4 --bit-true` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** real recording `2026-11-21T1943Z_meteor-m2-4_part2.cu8` (data/MANIFEST.md).

The bit-true chain, which computes what the RTL computes bit for bit, decodes the real Meteor-M N2-4 pass: it finds 4,582 of the 4,583 frames SatDump decoded, every one identical in its 892 data bytes, and 1,003 more.

**Totals (2026-11-21 pass, 19:41:51–20:00:33 UTC, 30 s chunks overlapping 2 s, each from a cold start as after a reset).**
- 5,585 frames with all four RS codewords good, merged across chunks by (VCID, counter). SatDump: 4,583.
- 4,582 frames in both, all equal; none differ. 1 SatDump-only frame (not placed; the fade at the end is where the per-chunk counts leave room for it).
- Chain per chunk, as on the board: the host's coarse estimate sets the NCO (ADR 0002), then DDC, RRC, AGC, Costas, Farrow/Gardner timing, 4-bit quantizer (step ONE/4), frame sync (threshold 48/64, flywheel 4), Viterbi (traceback 96), NRZ-M, PN, RS ×4.

**Where the model-only frames are.** SatDump's own file has no gaps until the fade at the end (its counter gaps start at VCID 63 counter 941,500), so every model-only frame in a chunk before 19:56 comes before SatDump's first frame: the bit-true chain decodes from the 19:45:35 chunk, SatDump from partway through the 19:47:55 chunk. The rest are in SatDump's gaps in the fade (19:56:19 to 19:57:15 chunks). The merged split between the two was not computed.

**Against the float model (real_pass_model.csv, same chunks).** Between 19:46:59 and 19:56 both decode every frame, 262–263 per chunk. On the rising signal the bit-true chain finds fewer in the first chunks (52 vs. 90 at 19:45:35); on the fade it holds on longer (141 vs. 76 at 19:56:47, 8 vs. 2 at 19:57:15), which is why it misses only 1 SatDump frame where the float model missed 26. The difference is the frame sync: the RTL's causal, locally normalized correlation and its verify queue (ADR 0010) against the float model's batch search. Neither loses a frame in the strong part of the pass.

**Rails and phase.** swap = 0 for every RS-good frame (`swap1_rs_good=0`), as in the float model (signal-spec.md); alt changes from one cold start to the next.

**Carrier.** `median_carrier_hz` is the NCO correction from the coarse estimate plus the Costas loop's frequency register, relative to the 150 kHz tuning: from about −450 Hz to −6.4 kHz, the same Doppler curve as the float model, within 1 Hz in every chunk from 19:46:59 to 19:56:19. Chunks without a frame show only what the loops did on noise.

**Limits.** This is the model of the RTL, not the RTL: the RTL is bit-exact with it on synthetic recordings (rx_chain_rtl_decode.csv, rx_top_rtl_decode.csv), and the RTL on a real recording is the next check. Each chunk starts cold, where the board would run the whole pass from one reset.
