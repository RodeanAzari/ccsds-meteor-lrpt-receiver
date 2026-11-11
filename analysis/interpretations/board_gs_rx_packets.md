The space-packet path works on the board's real output: board → gs-rx → space packets, checked against the truth and against SatDump. In every replay, gs-rx's packets are exactly the packets of the frames the board delivered, and they agree with SatDump wherever both have the frames.

**The recording.** `make_synthetic_iq.py --packets` (seed 2027): 300 VCID-5 CADUs whose packet zones carry random space packets on APIDs 64–70. There are 270 complete packets; the stream is cut mid-packet at the end, as at the end of a pass. The modulation, channel and Eb/N0 (8 dB) are the same as `board_gs_rx.csv`'s recording. SatDump 1.2.2 decoded it with `satdump meteor_m2-x_lrpt baseband <cu8> data/synthetic/satdump_packets_out --samplerate 1024000 --baseband_format cu8 --freq_shift -150000 --dc_block`. It decoded 261 frames, all equal to truth (frames 35–295), and 228 packets (by `satdump_demux`). SatDump exits 1 because it cannot build an image from random data; it does the same on the seed-2026 recording (`satdump_crosscheck.csv`).

**Packets, every replay.**
- `packets_exact = 1`: gs-rx's `packets.bin` equals the golden model's `demux` over the truth CADUs the board delivered, byte for byte and in order. A packet is missing only if it touches a frame the board did not deliver.
- At 1× and 5×, that is 268 of the 270 truth packets. The other 2 touch frame 0 (lost to pull-in) or frame 299 (cut by the end of the recording).
- `packet_diff` against SatDump: 228 (1×, 5×) and 216 (5.6×) packets are equal, none differ, and none are unexplained. Every packet only one side has spans a frame the other side lacks: 40 are in frames before SatDump acquires; at 5.6×, 12 are in CADUs the board lost.

**The CADU losses at 5.6×.**
- Two replay datagrams never left the host: the host interface's kernel `tx_dropped` rose by 2, and the board counted 2 lost (`board_ingest_lost`).
- The board itself lost nothing it received: no CRC errors, no FIFO overflow, no frame-sync slips.
- The two gaps cost 2 CADUs and made RS fail on 10 more. gs-rx's RS gate dropped those 10, as SatDump's `rs_usecheck` does. Its demultiplexer then dropped the packets crossing the counter gaps and emitted none damaged. That is why `result` (gs-diff) passes, but the replay as a whole fails the script's check, which requires no frame that only SatDump has.
- The host was saturated (load ~16 on 16 cores from other sessions). An earlier run at the same load dropped 26 and 28 datagrams at 5× and 5.6× (not recorded in this CSV, which holds the rerun). At load ~7.5, `board_gs_rx.csv` had no loss at 5×.
- This is the cause of the "intermittent replay datagram loss" left open since Phase B: the host's kernel drops datagrams at the USB-Ethernet adapter. It is not on the wire or in the board.

**Limits.** One synthetic recording at a high Eb/N0, one replay per speed. The packets are random, not MSU-MR image data, so this does not show an image; that needs a real pass.
