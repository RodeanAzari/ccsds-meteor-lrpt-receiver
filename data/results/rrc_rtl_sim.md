# rrc_rtl_sim

- **Commit:** `743378e0aa6f35ba5fc467776eb4518f3152302d`
- **Command:** `make sync-rtl-results`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Verilator 5.050, cocotb 2.1.0
- **Input:** synthetic, seeds 11 and 12 in tb/cocotb/test_sync_rrc.py (bit-true DDC output of OQPSK at 6 dB Eb/N0, 151 kHz carrier, 30 Hz/s ramp; Gaussian noise for the rate). No real recording.

The RRC matched filter RTL (`rtl/sync/sync_rrc.sv`) matches `model/rrc_fixed.py` bit for bit on 4,000 samples: the bit-true DDC output (16,000 cu8 input samples, ÷4) of OQPSK frames at 6 dB Eb/N0 with a 151 kHz carrier and a 30 Hz/s ramp. Random stalls ran on both sides of the stream. It reuses the comp FIR's time-shared multiply-accumulate with the 57 RRC taps, so it takes 62 clocks per 256 kS/s sample: 6.3× real time at 100 MHz. That sets the RRC-input injection mux's ceiling for BER campaigns below the ~22× the 100 Mb/s link could carry at 256 kS/s. At 6.3×, the 10⁸ decoded bits a 10⁻⁶ point needs take about 220 s, so it is not worth optimizing yet. Folding the symmetric taps through the DSP pre-adder would halve it. A planted wrong tap fails all four tests. The input is synthetic; a real recording's level is `[TBD]`.
