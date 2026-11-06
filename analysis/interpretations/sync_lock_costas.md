This is how fast the carrier loop locks by itself, at the bandwidth the receiver uses (0.001 rad/sample), when the host's coarse estimate leaves some error. The chain starts from reset, and the bit-true model matches the RTL bit for bit (sync_top_rtl_sim).

| Error left (Hz) | Lock time from reset (ms) | Frames decoded (of 12) |
|---|---|---|
| 0 | 19–21 | 10 |
| ±25 to ±50 | 25–65 | 10 |
| ±75 to ±100 | 69–158 | 9–10 |
| 150 | 238–314 | 8–9 |
| 200 | 377–587 | 5–7 |
| 300 | 913–1,200 in 3 seeds; 1 seed never locked in 1.37 s | 0–3 |

Lock time grows faster than linearly with the error. Up to about 100 Hz the loop locks within one frame (114 ms), so the coarse estimate must leave less than about 100 Hz. It leaves 12–18 Hz (sync_lock_range), so there is about 6x margin.

At zero error, 10 of the 12 frames still decode. The first is lost because its sync marker arrives while the loops are still pulling in; the last is lost at the end of the capture. Checked on seed 1: frames 1 to 10 decoded.

Lock times resolve to about 10 ms, the averaging window. Positive and negative errors behave alike; the ramp is always +30 Hz/s.
