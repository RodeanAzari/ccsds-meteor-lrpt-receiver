# rx_top_rtl_real_snippet

- **Commit:** `86ae365db9b610aa3000e94109573ff7298298f8`
- **Command:** `make rx-top-rtl-results`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Verilator 5.050, cocotb 2.1.0
- **Input:** real recording `2026-11-21T195100Z_meteor-m2-4_2.4s.cu8` (data/MANIFEST.md).

The RTL decodes the satellite: the whole board top, in Verilator from reset, turns 2.4 s of the real 2026-11-21 Meteor-M N2-4 pass into the same 20 CADUs SatDump decoded there, each bit-exact with the bit-true model.

- **Input:** data/samples' snippet at 19:51:00 UTC as 4,800 replay datagrams over MII at the 100 Mb/s line rate (5.69× real time), after a SET_NCO with the host's coarse estimate of this recording: 147,375.7 Hz, word 0x24D80C00, about 2.6 kHz below the 150 kHz tuning (Doppler and the dongle's offset at this point of the pass).
- **CADUs:** 20 packets out (21 frames in 2.4 s; the first is lost to the cold start's pull-in). Every packet's header, status bytes and 1,024 CADU bytes equal the bit-true model chain on the same input (20,960 bytes, 0 mismatches), and every CADU's 892 data bytes equal one of SatDump's 20 frames at this time: all 20 are found. The status bytes say 0 RS corrections and 0 ASM errors in every frame, swap = 0.
- **Counters:** 2,110 stats packets, consecutive; the last counts every datagram through eth_rx, udp_rx, the ingest and the DDC with no loss anywhere, the frame sync's counters equal to the model's, the second (late) SET_NCO refused. eth_rx FIFO high-water 1 byte: at the fastest replay the receiver keeps up with a real signal, not only a synthetic one.
- **Why it matters:** every earlier RTL test ran on this project's own synthetic signal, so a spec error shared by the modulator and the receiver would have passed them all. Here the input is the satellite's and the reference is SatDump.
- **Run:** `COCOTB_TEST_FILTER=real_pass_snippet_in_satdump_cadus_out` of `make rx-top-rtl-results`, 26 min 51 s wall clock (1,583 s simulated-test time).
- **Limits:** simulation, not the board; 2.4 s at high SNR (~14 dB soft SNR in the float model), one cold start. Not separately mutated: the RTL-vs-model checks are the synthetic test's (bugs planted there, docs/log.md 2026-11-08), and the SatDump comparison was mutated in model/tests/test_real_snippet.py. The full pass on the board is the next step.
