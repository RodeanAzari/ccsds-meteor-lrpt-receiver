The receiver on the Arty decodes at a measured implementation loss of 0.12 to 0.36 dB against the model. That loss is measured from the waveform (DDC, RRC, timing and carrier loops, 4-bit soft decisions) through the Viterbi decoder and NRZ-M. After RS, no bit error was seen from 3.0 dB up.

**Before RS (`viterbi_board`: Viterbi, NRZ-M and the derandomizer, over the 1,020-byte RS body).**
- Six points have at least 100 errors: 1.19e-2 at 2.0 dB, 3.13e-3 at 2.5, 7.73e-4 at 3.0, 1.79e-4 at 3.5, 3.78e-5 at 4.0 and 4.85e-6 at 4.5 dB.
- At 5.0 dB the 20 recordings gave 80 errors in 48.6 M bits, so that point is an upper bound: BER < 1.98e-6 (95%).
- The model's `viterbi_after_nrzm` curve (`ber_awgn.csv`) has unquantized soft decisions on an AWGN symbol channel with ideal synchronization. At equal Eb/N0 the board's BER is 1.5 to 2.1 times the model's.
- Read along the Eb/N0 axis instead, with the model curve log-interpolated between its points, the model reaches each board BER this much earlier:

  | Eb/N0 | 2.0 | 2.5 | 3.0 | 3.5 | 4.0 | 4.5 dB |
  |---|---|---|---|---|---|---|
  | Implementation loss | 0.36 | 0.25 | 0.21 | 0.15 | 0.19 | 0.12 dB |

- The loss is largest at low Eb/N0, where the timing and carrier loops are noisiest.
- From 3.5 dB up it is close to the 0.13 dB that 4-bit soft decisions alone cost the model at BER 1e-5 (`soft_width_ber.csv`), so the sync chain adds little there.
- Log-interpolating between 4.0 and 4.5 dB, the board reaches BER 1e-5 at 4.32 dB (after NRZ-M). Uncoded OQPSK theory needs 9.59 dB, so that is a hardware coding gain of about 5.3 dB.

**After RS (`viterbi_rs_board`: the 892 data bytes of each CADU).**
- 1.31e-3 at 2.0 dB and 9.64e-5 at 2.5 dB.
- At 3.0, 3.5, 4.0, 4.5 and 5.0 dB: 0 errors in 42.5 M data bits per point (20 recordings, 5,960 CADUs), so BER < 7.0e-8 (95%) at each.
- The pre-RS build counts how RS would fare on exactly the bytes it decoded:
  - 2.0 dB: 30 of 1,192 codewords uncorrectable (2.5%).
  - 2.5 dB: 3 of 1,192.
  - 3.0 dB and up: none of 23,840 per point.
- The RS cliff therefore sits between 2.5 and 3.0 dB, where the pre-RS BER drops from 3e-3 to 8e-4.

**Frame accounting.**
- Every usable frame came back at every point: `frames_missing` is 0, and the ingest gap, lost, late and Ethernet-overflow counters are all 0.
- At 2.0 dB, 2 of 298 CADUs on each build were farther than 20% of their bits from every sent frame. Those 2 are left out of the bit count, so the 2.0 dB figures are slightly optimistic. From 2.5 dB up, every CADU matched.

**Limits.**
- Each point is one recording (2.0 and 2.5 dB, stopped once both curves had 100 errors) or 20 recordings. The recordings use 4 payloads with fresh noise each time.
- The channel is synthetic AWGN with a fixed 151 kHz carrier, a 0.37-symbol timing offset and a 20 ppm clock. There is no Doppler ramp, fading or real-recording impairment.
- The pre-RS and post-RS curves come from two bitstreams, each replaying the same recording.
- Uncoded BER was not measured on hardware: the board has no tap before the Viterbi decoder.
