# viterbi_rtl_sim

- **Commit:** `ff1f113872a2ebef0ac8b324fdefca5867e08804 (with uncommitted changes)`
- **Command:** `make fec-rtl-results`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Verilator 5.050, cocotb 2.1.0
- **Input:** synthetic, seeds 61-62 in tb/cocotb/test_fec_viterbi.py via fec_vectors.py (random bits, K=7 r=1/2, antipodal at rail rms ONE + AWGN, 4-bit quantized); traceback depth 96 from state 0. No real recording.

The Viterbi decoder RTL (`fec_viterbi`: the 64-state ACS array, then the BRAM traceback at depth 96 from state 0) produces exactly the model's bits: `viterbi_fixed(..., depth=96, start="zero")`, all but the model's last 96 bits, which come from a block-end traceback the streaming RTL doesn't do.

- **1.5 dB, random input gaps and output stalls:** the decoder makes errors (93 against the bits sent), and they are the model's errors, bit for bit. So the hardware BER campaign will measure the model's curve, not just a similar one.
- **4.0 dB, no stalls:** no errors. 95.9 clocks per input bit, set by the traceback's depth + 3 clocks per bit (the first 96 steps produce no bit). At 100 MHz the budget for 72 kbit/s is 1,389 clocks, so there is 14.5x headroom. That headroom also caps how fast the BER campaign can replay.

The ACS array alone runs one step per clock (test_fec_acs_array.py); the traceback sets the rate. A faster traceback (several bits per walk, ADR 0007) would only matter for faster-than-real-time BER replay.
