The C++ tool `gs-image` (`gs/msumr.hpp`) on this receiver's own space packets: gs-rx's `packets.bin` from the board replay of the 2026-11-21 pass, in one run, to one PNG per channel. That is the whole chain with no SatDump and no Python: board → gs-rx → gs-image → image.

- **`pixels_differ_model`: 0 on every channel.** gs-image's PNGs are the golden model's images of the same packets (`model/msumr.py`), pixel for pixel, 1,568 × 4,440 per channel. The model equals SatDump when both get the same packets (`msumr_model.csv`), so gs-image draws what SatDump draws.
- **Against SatDump's images of the same CADUs: 14 segments of 8 × 112 pixels differ (5, 8 and 1 per channel), all explained**, the same 14 as the model's `own_packets` case. At each one gs-image has no segment, and the packet SatDump used is not among gs-rx's: gs-rx drops a packet that crosses a CADU gap rather than pass it on damaged (ADR 0015), and SatDump decodes what it can of such a packet.
- `gs_image_s`: wall time of the one gs-image run (22,295 packets read, three PNGs written at zlib level 9), on the development host. Most of it is the PNG compression.

Channels 3, 5 and 6 carried no data on this pass; gs-image writes no file for them, as SatDump does not.
