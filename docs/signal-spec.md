# Signal specification: Meteor-M2-x LRPT, 72k mode

**This file is the spec.** If code and this file disagree, stop and flag it.

**Source:** SatDump tag `1.2.2`, commit `7aef0fe8441bc3eb440b1b6ba053556da5e40991`, pipeline `meteor_m2-x_lrpt`
(`pipelines/Meteor-M.json:121`). Paths below are relative to that tree.

**Status of the evidence:**

- **Read:** taken from SatDump source. Not yet exercised on a real signal.
- **Computed:** also checked by `scripts/verify_signal_spec.py`.
- **Open:** SatDump doesn't fix this value. It has to be measured from a recording.

Nothing here has been confirmed on a real recording yet. That is the remaining Phase 0 work.

## Parameters

| Parameter | Value | Evidence | Source |
|---|---|---|---|
| Frequency | 137.9 MHz primary, 137.1 MHz backup | Read | `pipelines/Meteor-M.json:134` |
| Modulation | OQPSK | Read | `pipelines/Meteor-M.json:178` |
| Symbol rate | 72,000 sym/s | Read | `pipelines/Meteor-M.json:179` |
| RRC roll-off | **0.5** | Read | `pipelines/Meteor-M.json:180` |
| Convolutional code | K = 7, r = ½, masks `{79, 109}` = 171₈, 133₈ | Computed | `src-core/common/codings/viterbi/viterbi_1_2.cpp` (constructor) |
| Conv output order | **G1 (171₈) first, then G2 (133₈)** | Read | `cc_encoder.cpp`, `CCEncoder::work` |
| Conv output inversion | **None.** Both masks are positive, and a negative mask would mean inversion. | Read | `cc_encoder.cpp`, `CCEncoder::work` |
| Soft-bit polarity | Positive soft value = bit 1 | Read | `cc_decoder.cpp:121`, `signed_soft_to_unsigned` |
| **Differential coding** | **NRZ-M. Decode after Viterbi and before the ASM check: `out[n] = in[n] ^ in[n-1]`.** | Read, Computed | `pipelines/Meteor-M.json:190`, `module_ccsds_conv_concat_decoder.cpp` (`diff.decode_bits`), `differential/nrzm.cpp` |
| Frame | 8,192 bits (1,024 B), ASM `0x1ACFFC1D` | Read | `pipelines/Meteor-M.json:191`, `bpsk_ccsds_deframer.h:62` |
| Randomizer | CCSDS PN over bytes 4 to 1023, indexed `i % 255` from byte 4. Runs **before** RS on receive. | Computed | `module_ccsds_conv_concat_decoder.cpp`, `randomization.cpp` |
| Reed-Solomon | RS(255,223), poly 0x187, FCR 112, root spacing 11, 32 roots | Read | `reedsolomon.cpp:32`, `libs/correct/correct.h:180` |
| RS interleave | Depth 4: codeword *b* byte *n* is at offset `n*4 + b` from byte 4 | Read | `pipelines/Meteor-M.json:195`, `reedsolomon.cpp:145` |
| **RS basis** | **Conventional.** No dual-basis conversion for this pipeline. | Read | `pipelines/Meteor-M.json:196` |
| Which rail leads, and which carries G1 | **Open.** See below. | Open | `viterbi_1_2.cpp`, `Viterbi1_2::work` |

`rs_dualbasis` defaults to `true` in the decoder module. Only the pipeline's explicit `false` makes it conventional.

## Transmit chain this implies

```
CADU: ASM + randomized CVCDU → NRZ-M encode → conv encode (G1, G2) → OQPSK
```

## Encoded ASM

NRZ-M comes before the convolutional code, so the pattern on the air is the encoded form of the NRZ-M-encoded ASM. It
has two polarities, depending on the bit before the ASM.

| Input | 64 encoded symbols, starting from zero state | Note |
|---|---|---|
| ASM, last NRZ-M bit 0 | `03B10B02F33D2076` | Computed |
| ASM, last NRZ-M bit 1 | `DAFEF4FD0CC2DF89` | Computed |

- **Correlate only the last 52 symbols.** The first 12 depend on the previous frame.
- **The two polarities are complements** over those 52 symbols, since both generators have odd weight. They look the
  same as a 180° rotation.
- **Checked against SatDump:** the last 52 symbols match the constant `0xFC4EF4FD0CC2DF89` in
  `plugins/meteor_support/meteor/module_meteor_lrpt_decoder.cpp`. That constant belongs to SatDump's older QPSK path,
  not the 72k pipeline.

## Phase ambiguity

SatDump's 72k path has no pre-Viterbi correlator. It decodes 2,048 soft bits, re-encodes them and compares, for every
combination of:

- rotation `{0°, 90°}`
- I/Q swap `{no, yes}`
- one-soft-bit shift `{0, 1}`

It keeps the lowest BER under a threshold of 0.300, and declares loss after more than 20 bad buffers
(`pipelines/Meteor-M.json:192-193`, `module_ccsds_conv_concat_decoder.cpp:76,107`).

180° and 270° aren't searched because NRZ-M decoding removes bit inversion, so 180° needs no correction.

**Open:** because SatDump searches, its source doesn't say which rail leads on the air or which rail carries G1. Measure
both on a recording in Phase A, and record the winning hypothesis here.

## SatDump demodulator, for reference

These values describe SatDump's implementation. They are not requirements on this receiver.

| Item | Value | Source |
|---|---|---|
| Order | AGC → RRC → Costas (order 4) → delay **Q** by one sample → Mueller & Müller | `module_psk_demod.cpp`, `init` |
| Working rate | 168 kS/s, 2.33 samples/symbol (computed from the rules in the source) | `module_demod_base.cpp:65,74`, `module_psk_demod.cpp:62` |
| RRC taps | 31 | `module_psk_demod.h:27` |
| Costas bandwidth | 0.002 | `pipelines/Meteor-M.json:181` |
| AGC rate | 1e-2 | `module_demod_base.h:48` |
| Clock | gain_mu 8.7e-3, gain_omega (8.7e-3)²/4, relative limit 0.005 | `module_psk_demod.h:32-35` |
| Soft scale | sample × 100, clamped to int8 | `module_psk_demod.cpp:209` |

## Differences from CLAUDE.md

This file wins wherever they differ, as CLAUDE.md itself says. CLAUDE.md §2, §3 and §12 haven't been rewritten.

| # | CLAUDE.md | SatDump 1.2.2 | Consequence |
|---|---|---|---|
| 1 | No differential decoder in §3 | NRZ-M is on | **Add an NRZ-M block between Viterbi and the ASM check**, and NRZ-M encode in the §8.1 modulator. Without it no ASM ever matches. |
| 2 | §3.5: correlate against one encoded ASM pattern, 4 rotations | Two complementary patterns, rotations {0°, 90°} | Correlate on absolute value with {0°, 90°} × swap × shift. Confirm on a recording in Phase A. |
| 3 | §3.7: dual-basis conversion is possible | Conventional | Drop the `[dual-basis conv]` stage in §3. |
| 4 | §3.4: delay I | SatDump delays Q | Not a contradiction yet. It depends on the Open item above. |
| 5 | §3: timing, then carrier | Carrier, then timing | Architecture choice, not a signal parameter. Keep CLAUDE.md's order unless the model shows a problem; record in the OQPSK timing ADR. |
| 6 | §8.5: 100% bit-exact CADUs | SatDump doesn't correct every byte it writes | See below. |

## What `gs-diff` can compare

SatDump's `.cadu` output isn't fully corrected:

- `ReedSolomon::decode` copies back only the 223 corrected data bytes per codeword, so **parity bytes keep their channel
  errors**.
- The ASM is written as received, and `compare_32` tolerates bit errors in it.
- With `rs_usecheck` on, frames with an uncorrectable codeword aren't written at all.

So the acceptance test is **bit-exact on the 892 data bytes** (offsets 4 to 895) of frames both decoders produce. Parity
and ASM differences get reported separately and don't fail the test.
