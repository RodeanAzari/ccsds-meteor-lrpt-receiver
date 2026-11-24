# msumr_model

- **Commit:** `5e98b5138b7f763f770476a4ef2d222021098a6b`
- **Command:** `python -m msumr_study --cadus build/board_gs_rx_real/1_1x/cadus.bin --packets build/board_gs_rx_real/1_1x/packets.bin --satdump-images build/real_pass/msu/MSU-MR --pass-cadu /home/rodea/recordings/2026-11-21_satdump/meteor_m2-x_lrpt.cadu --pass-images /home/rodea/recordings/2026-11-21_satdump/MSU-MR --recording 2026-11-21T1943Z_meteor-m2-4_part2.cu8` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** real recording `2026-11-21T1943Z_meteor-m2-4_part2.cu8` (data/MANIFEST.md).

The MSU-MR image model (`model/msumr.py`, written from `docs/signal-spec.md` and the JPEG standard, not from SatDump's code) against SatDump's own images, pixel by pixel. Channels 1, 2 and 4 are the ones Meteor-M N2-4 sent on this pass; 3, 5 and 6 carry no data, and neither decoder writes them.

- **`model_satdump_demux`:** the board's CADUs split into packets by SatDump's demultiplexer (`model/space_packets.satdump_demux`). These are the same packets SatDump decodes, and the model gives **SatDump's images exactly: 1,568 × 4,440 pixels per channel, 0 different**.
- **`model_satdump_pass`:** the same on a second, independent input, SatDump's own CADUs of the recording: 1,568 × 3,568, 0 different.
- **`own_packets`:** this receiver's own space packets, from gs-rx's `packets.bin`, through the model. That is the full chain: board → gs-rx → image, with no SatDump step. 14 segments of 8 × 112 pixels differ (5, 8 and 1 per channel), out of 3 × 555 × 14 = 23,310. **Every one is explained:**
  - our image has no segment there, and the packet SatDump used for it is not among ours;
  - these are packets that crossed a CADU gap, which gs-rx drops rather than passing on damaged (ADR 0015; 23 dropped in this run, `board_gs_rx_real.csv`);
  - SatDump decodes such packets anyway and keeps whatever part of the segment still decodes.

The reference is the installed SatDump build (`1.2.2+gb79af48`). Its segment-placement code differs from the `1.2.2` tag: every channel spans the same scans and includes the last one. The model written from the tag's reader gave images 8–40 rows shorter than the installed build's, with identical pixels where both had rows. That is how the difference was found.
