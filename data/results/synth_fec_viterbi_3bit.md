# synth_fec_viterbi_3bit

- **Commit:** `ed6c0d69a222019ac745e5d108f8d168a76ade82 (with uncommitted changes)`
- **Command:** `make synth-ooc TOP=fec_viterbi GENERICS="SOFT_BITS=3 PM_BITS=8" NAME=fec_viterbi_3bit`
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1, Vivado 2025.2
- **Input:** synthetic, no input data: out-of-context place and route of fec_viterbi with SOFT_BITS=3 PM_BITS=8 on xc7a100tcsg324-1. No real recording.

The Viterbi decoder built for 3-bit soft decisions (`SOFT_BITS=3`, `PM_BITS=8` from `path_metric_bits(3)`, ADR 0006) instead of the shipped 4-bit / 9-bit, out of context at 100 MHz on the xc7a100t-1: 1,365 LUTs, 630 flip-flops, one RAMB36, WNS +2.628 ns, no failing endpoints. The 4-bit build (`synth_fec_viterbi.csv`) uses 1,621 LUTs and 694 flip-flops at +1.895 ns, so the fourth soft bit costs 256 LUTs (16% of the decoder, 0.4% of the device's 63,400), 64 flip-flops (one path-metric bit per state) and 0.73 ns of slack, almost all of it in the ACS array (1,288 vs. 1,544 LUTs). This is the measured area half of ADR 0005's comparison; the BER half is `soft_width_ber.csv` (4-bit 0.11 dB better at 1e-5). The 3-bit configuration is synthesized only: it lints clean, but no cocotb test runs it, and it is not the configuration the receiver uses.
