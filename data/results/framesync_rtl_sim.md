# framesync_rtl_sim

- **Commit:** `ff1f113872a2ebef0ac8b324fdefca5867e08804 (with uncommitted changes)`
- **Command:** `make fec-rtl-results`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Verilator 5.050, cocotb 2.1.0
- **Input:** synthetic, coded frames from model/tests/framesync_stimulus.py (build_cadus seeds 3-8, antipodal at rail rms ONE + AWGN where noted, 4-bit quantized), per scenario in tb/cocotb/test_fec_framesync.py. No real recording.

The frame-sync RTL (`fec_framesync`: correlators, sync FSM, 32,768-symbol ring) sends the Viterbi exactly the windows of the bit-true model, `windows(frame_sync_fixed())` (ADR 0010 and its amendment). Every window's 8,352 pairs, its tuser flags and its tlast match. So do the early, dropped and slip counters, in every scenario. `mismatches` is 0 by construction: any mismatch fails the run.

- **Hypotheses:** all four phase hypotheses lock and derotate. A run-in starting exactly at symbol 0 is emitted; one symbol short, it is counted as early.
- **Flywheel and loss of lock:** a missed ASM's frame comes out flagged. More misses than the flywheel register allows lose lock, and the next acquisition emits no frame twice.
- **Slips:** a carrier slip (d = 0), timing slips of −1 (overlapping windows) and +2 (the window's edge), and a constructed −1/+1 tie, all resolved as the model resolves them.
- **Noise and a low threshold:** noise locks on nothing. At thr 16/64, thousands of false peaks fill the verify queue, and the dropped count equals the model's.
- **Backpressure:** with the sink held (`fs_ring_stall`), the input stalls at the ring and no window is lost. Every scenario's sink is slower than its input, so most stall somewhere (`input_stalled_clocks`). The stall at the descriptor FIFO needs a 128k ring and runs as its own build (`test_fec_framesync_fifo.py`), which is not in this table.

Synthetic coded frames only, fed as 4-bit symbols straight into the frame sync, not through the sync chain. The chain test, with the decode, is the next step.
