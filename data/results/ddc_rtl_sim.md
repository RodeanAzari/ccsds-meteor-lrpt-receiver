# ddc_rtl_sim

- **Commit:** `41efc488a5eeb5a692c24cf2c7e12f103fe2d959`
- **Command:** `make ddc-rtl-results`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Verilator 5.050, cocotb 2.1.0
- **Input:** synthetic, seeds 8 and 9 in tb/cocotb/test_ddc_top.py (OQPSK, 151 kHz carrier, 30 Hz/s ramp, 6 dB Eb/N0, DC offset). No real recording.

The DDC RTL (`rtl/ddc/ddc_top.sv`, Verilator) reproduces the bit-true model `model/ddc_fixed.py` exactly: every s16 output sample matched on a modulated OQPSK signal with a 151 kHz carrier, a 30 Hz/s Doppler ramp, 6 dB Eb/N0 and a DC offset, with random tvalid gaps at the input and tready stalls at the output. With the output always ready, the chain accepts one input sample every 9.0 clock cycles. The bottleneck is the time-shared compensation FIR (34 cycles per 256 kS/s output, i.e. per 4 inputs). At the planned 100 MHz core clock a 1.024 MS/s stream needs one sample per 97.7 cycles, so the DDC has about 10.8x real-time headroom; that is the ceiling on N× replay through the DDC. The 100 MHz clock is a plan: no synthesis or timing run exists yet.
