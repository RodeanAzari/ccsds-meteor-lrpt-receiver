# gs_image_real

- **Commit:** `7654f98f30ab98d577c9f86db295200f2f3eeb3d (with uncommitted changes)`
- **Command:** `python -m msumr_study --cadus ../build/board_gs_rx_real/1_1x/cadus.bin --packets ../build/board_gs_rx_real/1_1x/packets.bin --satdump-images ../build/real_pass/msu/MSU-MR --pass-cadu /home/rodea/recordings/2026-11-21_satdump/meteor_m2-x_lrpt.cadu --pass-images /home/rodea/recordings/2026-11-21_satdump/MSU-MR --gs-image ../build/gs-Release/gs-image --recording 2026-11-21T1943Z_meteor-m2-4_part2.cu8` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** real recording `2026-11-21T1943Z_meteor-m2-4_part2.cu8` (data/MANIFEST.md).

The C++ tool `gs-image` (`gs/msumr.hpp`) on this receiver's own space packets: gs-rx's `packets.bin` from the board replay of the 2026-11-21 pass, in one run, to one PNG per channel. That is the whole chain with no SatDump and no Python: board → gs-rx → gs-image → image.

- **`pixels_differ_model`: 0 on every channel.** gs-image's PNGs are the golden model's images of the same packets (`model/msumr.py`), pixel for pixel, 1,568 × 4,440 per channel. The model equals SatDump when both get the same packets (`msumr_model.csv`), so gs-image draws what SatDump draws.
- **Against SatDump's images of the same CADUs: 14 segments of 8 × 112 pixels differ (5, 8 and 1 per channel), all explained**, the same 14 as the model's `own_packets` case. At each one gs-image has no segment, and the packet SatDump used is not among gs-rx's: gs-rx drops a packet that crosses a CADU gap rather than pass it on damaged (ADR 0015), and SatDump decodes what it can of such a packet.
- `gs_image_s`: wall time of the one gs-image run (22,295 packets read, three PNGs written at zlib level 9), on the development host. Most of it is the PNG compression.

Channels 3, 5 and 6 carried no data on this pass; gs-image writes no file for them, as SatDump does not.
