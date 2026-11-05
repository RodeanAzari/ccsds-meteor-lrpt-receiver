# costas_rtl_sim

- **Commit:** `84859c45331e5afe8f0bab5fae9c0974dcaee50c`
- **Command:** `make sync-rtl-results`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Verilator 5.050, cocotb 2.1.0
- **Input:** synthetic, seeds 16-18 in tb/cocotb/test_sync_costas.py (bit-true AGC output of OQPSK at 6 dB Eb/N0, 50 Hz residual carrier after the coarse estimate, 30 Hz/s ramp; 20 Hz clamp for the clamp test). No real recording.

The Costas loop RTL (`rtl/sync/sync_costas.sv`) matches `model/sync_fixed.py` `costas()` on every output in three runs. The first is 16,000 samples of bit-true AGC output (OQPSK at 6 dB Eb/N0, gain pre-settled) carrying the 50 Hz residual left after the host's coarse estimate and a 30 Hz/s ramp, with random stalls on both sides. The loop pulls in within the run and ends at the frequency in `final_freq_hz`. The second is 8,000 samples with the frequency clamp set to 20 Hz, below the residual, so the integrator must sit at the clamp. The third is 2,000 samples for throughput. Because the loop is per sample, the RTL keeps one sample in flight: 10 clocks per sample, 39× real time at 100 MHz. Planted bugs each fail: the phase updated with the previous sample's frequency, sgn(0) taken as +1 in the detector (both fail all three tests), and the upper frequency clamp removed (fails the clamp test). Pull-in is slow, as ADR 0002 predicted: in the model at these gains, a 50 Hz residual locks after ~5,000 samples (20 ms), while 100–400 Hz do not lock within 16,000. The lock range and lock time are Phase C measurements still to be made. Input is synthetic.
