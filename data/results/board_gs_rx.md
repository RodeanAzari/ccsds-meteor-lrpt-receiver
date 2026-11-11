# board_gs_rx

- **Commit:** `30058dbe16f18c5b1f14b19e826cb2df6f575702 (with uncommitted changes)`
- **Command:** `PYTHONPATH=. python scripts/board_gs_rx.py data/synthetic/synthetic_seed2026_1024000SPS.cu8 data/synthetic/satdump_out/meteor_m2-x_lrpt.cadu --iface 192.168.10.1 --speed 1,5,5.6 --tune 150000 --bit build/board/arty_rx_eth_top.bit`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, synthetic_seed2026_1024000SPS.cu8 (make synthetic-iq) streamed by gs-replay to arty_rx_eth_top on the Arty A7-100T, one replay per row from a freshly programmed board, received by gs-rx; NCO word 0x25C11200 (coarse estimate 151016.7 Hz) by SET_NCO; compared by gs-diff with data/synthetic/satdump_out/meteor_m2-x_lrpt.cadu (SatDump 1.2.2's decode of the same recording, satdump_crosscheck.csv row 1). No real recording.

The full host path works on the board's real output: board → gs-rx → gs-diff. On the decode of the same recording by SatDump, the reference decoder, it agrees bit for bit.

**Each replay.**
- In every replay gs-rx received all 298 CADU packets the board sent: none missing by pkt_seq, none malformed, no ring overflow.
- Every CADU passed the RS gate, with 0 symbols corrected (8 dB synthetic recording).
- The board echoed the SET_NCO word in its stats.
- gs-diff found every frame SatDump decoded (258) in gs-rx's output, with 0 data bits, 0 ASM frames and 0 parity bytes different, and no frame that only SatDump has.

**The 40 frames only the board decoded.**
- SatDump's decode of this recording (`satdump_crosscheck.csv`, row 1: 1 kHz offset plus a 30 Hz/s ramp) starts at frame 38 and ends at frame 295.
- The board's 298 frames are frames 1 to 298. Frame 0 is lost to pull-in, and frame 299 is cut by the end of the recording.
- So the board has 37 frames that come before SatDump's first and 3 that come after its last.

**Speed and the space-packet path.**
- `achieved_speed` is gs-replay's measured rate: 1.00×, 5.00× and 5.39× (5.6× asked). Nothing was lost at any of them.
- This recording's frames carry random data bytes, not VCID-5 space packets:
  - only the CADUs whose random VCID happens to be 5 reach the demultiplexer;
  - it recovers no packet, as expected;
  - its counters are not checked here.
- The space-packet path against SatDump is tested on loopback (`gs/tests/test_rx_loopback.py`). On hardware it needs a recording that carries packets (a real pass).

**Limits.** One synthetic recording at a high Eb/N0, one replay per speed. This shows the plumbing is correct, not decoding margin; for margin, see `ber_board.csv`.
