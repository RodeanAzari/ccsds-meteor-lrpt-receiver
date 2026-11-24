# Signal specification: Meteor-M2-x LRPT, 72k mode

**This file is the spec.** If code and this file disagree, stop and flag it.

**Source:** SatDump tag `1.2.2`, commit `7aef0fe8441bc3eb440b1b6ba053556da5e40991`, pipeline `meteor_m2-x_lrpt`
(`pipelines/Meteor-M.json:121`). Paths below are relative to that tree.

**Status of the evidence:**

- **Read:** taken from SatDump source. Exercised together on a real signal (see below), not one by one.
- **Computed:** also checked by `scripts/verify_signal_spec.py`.
- **Measured:** SatDump doesn't fix this value; it was measured on a recording.

**Confirmed on a real recording (2026-11-21 pass, data/MANIFEST.md):** the float model, built from this file, decodes
5,583 frames of the pass, and the 4,557 it shares with SatDump are equal in every data byte
(`data/results/real_pass_model.csv`; `model/tests/test_real_snippet.py` on the committed snippet). A wrong coding
value (conv code and output order, NRZ-M, frame, PN, RS) fails RS or the comparison; mutants planted in three of
them were caught by that test. The analog values (symbol rate, RRC roll-off) are shown to work, not to be exact.

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
| Which rail leads, and which carries G1 | **The leading rail carries G1:** each G1 symbol goes out half a symbol before its G2 partner. Which of I or Q that is depends on the 90° carrier ambiguity. | Measured | `data/results/real_pass_model.csv` (`swap1_rs_good=0`) |

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

**Measured (2026-11-21 pass):** SatDump's search hides which rail leads and which carries G1, so this came from a
recording. Every RS-good frame the model decoded won with swap = 0: in the time-ordered serial stream each G1 symbol
comes before its G2 partner, so the leading rail carries G1. The rotation hypothesis (0° or 90°) changes from one
cold start to the next: which physical rail (I or Q) leads is the carrier's phase ambiguity, not a property of the
signal. The search over {0°, 90°} stays; the swap hypotheses never won on this signal.

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

## Differences from the build plan

This file wins wherever they differ, as CLAUDE.md itself says. The build plan's §2 and §3 (`docs/buildplan.md`,
moved there from CLAUDE.md with the same numbers) and CLAUDE.md §12 haven't been rewritten.

| # | Build plan | SatDump 1.2.2 | Consequence |
|---|---|---|---|
| 1 | No differential decoder in §3 | NRZ-M is on | **Add an NRZ-M block between Viterbi and the ASM check**, and NRZ-M encode in the §8.1 modulator. Without it no ASM ever matches. |
| 2 | §3.5: correlate against one encoded ASM pattern, 4 rotations | Two complementary patterns, rotations {0°, 90°} | Correlate on absolute value with {0°, 90°} × swap × shift. Confirmed on the 2026-11-21 recording (swap never wins). |
| 3 | §3.7: dual-basis conversion is possible | Conventional | Drop the `[dual-basis conv]` stage in §3. |
| 4 | §3.4: delay I | SatDump delays Q | Not a contradiction: which physical rail leads is the 90° carrier ambiguity (Phase ambiguity, measured). |
| 5 | §3: timing, then carrier | Carrier, then timing | The model shows timing first fails on OQPSK. Carrier first, with a coarse estimate before it: ADR 0002. |
| 6 | §8.5: 100% bit-exact CADUs | SatDump doesn't correct every byte it writes | See below. |

## What `gs-diff` can compare

SatDump's `.cadu` output isn't fully corrected:

- `ReedSolomon::decode` copies back only the 223 corrected data bytes per codeword, so **parity bytes keep their channel
  errors**.
- The ASM is written as received, and `compare_32` tolerates bit errors in it.
- With `rs_usecheck` on, frames with an uncorrectable codeword aren't written at all.

So the acceptance test is **bit-exact on the 892 data bytes** (offsets 4 to 895) of frames both decoders produce. Parity
and ASM differences get reported separately and don't fail the test.

## Frame layers above the CADU (VCDU, M_PDU, space packets)

Read from `plugins/meteor_support/meteor/instruments/msumr/module_meteor_msumr_lrpt.cpp` (the pipeline's
`meteor_msumr_lrpt` product module), `src-core/common/ccsds/ccsds_aos/{vcdu,mpdu,demuxer}.cpp` and
`src-core/common/ccsds/ccsds.cpp`. Nothing here has been seen on a real recording yet.

**Which CADUs reach the demultiplexer.** `module_ccsds_conv_concat_decoder.cpp:213-228`: with `rs_usecheck` on (the
pipeline's setting), a CADU with any uncorrectable codeword is not written, so it never reaches the demultiplexer.
`gs-rx` drops the same CADUs (any `rs[b]` fail bit in the board's CADU packet) to see the same stream.

**CADU byte map** (offsets in the 1,024-byte CADU, after derandomization and RS):

| Bytes | Field | Source |
|---|---|---|
| 0–3 | ASM `1ACFFC1D` | `Parameters` above |
| 4–9 | VCDU primary header: version = byte 4 bits 7–6; spacecraft ID = byte 4 bits 5–0, byte 5 bits 7–6 (8 bits); **VCID = byte 5 bits 5–0**; VCDU counter = bytes 6–8 (24-bit, big-endian); replay flag = byte 9 bit 7 | `vcdu.cpp:12-16` (`parseVCDU`) |
| 10–11 | **VCDU insert zone, 2 bytes**, unused by SatDump | `Demuxer(882, true)` (`module_meteor_msumr_lrpt.cpp:125`); `insertZoneSize` default 2 (`demuxer.h:34`) |
| 12–13 | M_PDU header: **first header pointer = byte 12 bits 2–0, byte 13 (11 bits)**; the top 5 bits are not read | `mpdu.cpp:12` (`parseMPDU`, insert zone on) |
| 14–895 | **M_PDU packet zone, 882 bytes** (`MPDU_DATA_SIZE`) | `module_meteor_msumr_lrpt.cpp:125` |
| 896–1023 | RS parity (4 × 32) | `Parameters` above |

Check: 14 + 882 = 896 = 4 + 892, the end of the RS data bytes.

**Virtual channels.** The MSU-MR imager's packets are on **VCID 5**; SatDump demultiplexes only VCID 5 and
ignores every other VCID (`module_meteor_msumr_lrpt.cpp:143`). APID 70 carries MSU-MR telemetry (line 150); the
image APIDs are read by `lrpt::MSUMRReader`, outside this spec's scope until the optional image step.

**First header pointer.** 2047 (`0x7FF`) = no packet starts in this M_PDU. A value from 882 to 2046 is invalid: SatDump
skips that M_PDU entirely and keeps any packet in progress (`demuxer.cpp:73`).

**Space packet primary header** (6 bytes, `ccsds.cpp:15-21`): version = byte 0 bits 7–5; type = bit 4; secondary
header flag = bit 3; APID = byte 0 bits 2–0, byte 1 (11 bits); sequence flags = byte 2 bits 7–6; sequence count =
byte 2 bits 5–0, byte 3 (14 bits); packet length = bytes 4–5. **Data bytes after the header = packet length + 1**
(`demuxer.cpp:31`). A packet may span M_PDUs, and so may its header (`demuxer.cpp:83-94, 160-168, 191-198`).

**What SatDump's demultiplexer does not do** (`demuxer.cpp`, whole file):

- **No VCDU counter check.** A CADU lost or dropped for RS failure between two others is not noticed: the packet in
  progress continues with the next M_PDU's bytes.
- **No packet length check against the first header pointer.** When a packet in progress is longer than the bytes
  before this M_PDU's first header pointer, SatDump appends `first_header_pointer + 1 − offset` bytes
  (`demuxer.cpp:103`): one byte more than lie before the new header, and it ends the packet there, short of its
  declared length. When the packet fits, it appends exactly what remains.
- **No version, APID or sequence count check** on packets; no idle packet filter.

- **A packet can be emitted one CADU late.** When the first packet starting at a zone's first header pointer ends
  exactly at that zone's end, SatDump pushes it at the start of the next VCID-5 CADU (`demuxer.cpp:116-119`), so the
  last such packet of a recording is never emitted. Packet content is unaffected.

The first two only matter after a lost or dropped CADU: on an unbroken VCID-5 stream they never trigger. `gs-rx`
drops and counts what they would damage (ADR 0015); `model/space_packets.py` has both behaviours (`satdump_demux`,
`demux`).

## MSU-MR image packets (optional image step)

Read from SatDump at commit `b79af48` (`1.2.2+gb79af48`, the installed build that produced every SatDump output in
`data/MANIFEST.md`), `plugins/meteor_support/meteor/instruments/msumr/` (paths below relative to it):
`lrpt/{segment,huffman,idct,tables}`, `lrpt_msumr_reader.cpp` and `module_meteor_msumr_lrpt.cpp`. Against the
`1.2.2` tag the rest of this file was read from, the decoder files and the demultiplexer are unchanged apart from
refactoring; **the reader was rewritten** (segment placement and image extent), so the tag's reader does not give
the installed build's images. SatDump is GPL-3 and this repository is MIT, so the receiver's decoder is written from
this description and the JPEG standard (ITU-T T.81), not ported, and checked against SatDump's output images.

**Channels.** APIDs 64–69 are MSU-MR channels 1–6 (`lrpt_msumr_reader.cpp:37-48`); every other APID is ignored.
The pipeline runs with `m2x_mode` true (`pipelines/Meteor-M.json:203`); it changes only timestamps, not pixels.
Each packet is one **segment**: 14 MCUs of 8×8 pixels, a strip 112 pixels wide and 8 rows high.

**Segment header** (packet data bytes after the 6-byte primary header, `lrpt/segment.cpp:24-49`):

| Bytes | Field | Notes |
|---|---|---|
| 0–7 | day (2), ms of day (4), µs (2) | timestamp, not used for pixels |
| 8 | MCUN | number of the segment's first MCU in its scan |
| 9 | QT | must be 0 |
| 10 | DC / AC table ids | SatDump reads both as the **low** nibble (`segment.cpp:41`: `data[10] & 0xF0 >> 4` is `data[10] & 0x0F` by C precedence); must be 0 |
| 11–12 | QFM | must be `0xFFF0` |
| 13 | QF | quality factor |
| 14– | entropy-coded data | |

A segment counts only if the data is longer than 14 bytes, QT = 0, the low nibble of byte 10 is 0, QFM = `0xFFF0`, and
its first MCU decodes (`segment.cpp:15-19, 24-26, 94-96, 117-119`). Otherwise it is dropped as if never received.

**Entropy decoding** (`segment.cpp:62-167`, `lrpt/huffman.cpp`): bits MSB first. Per MCU, a DC difference coded with
the T.81 Table K.3 luminance DC code (categories 0–11) and added to a running DC that starts at 0 for each segment;
then AC (run, size) symbols with the T.81 Table K.5 luminance AC code: EOB (0,0) ends the block, ZRL (15,0) is 16
zeros. Magnitude bits as in T.81 (a leading 0 bit means negative: value − (2^size − 1)). Behaviours to match:

- A symbol adds its zeros and value only while the block index after it stays **below 64** (`segment.cpp:127`); a
  symbol that would reach index 64 ends the block instead, so coefficient 63 is never set. A block also ends after
  63 coefficients counted, without an EOB.
- No code matching, or too few bits left for a code's magnitude bits: if that happens in the first MCU the segment
  is invalid; in a later MCU decoding stops there, the MCUs already decoded keep their pixels and the rest stay 0
  (`segment.cpp:93-100, 116-123`).

**Dequantization and IDCT.** Coefficient k in zigzag order goes to natural position zigzag(k) (T.81 Figure A.6) and
is multiplied by the T.81 Table K.1 luminance table scaled by QF, computed in **32-bit float**: f = 5000 / QF if
20 < QF < 50, else 200 − 2·QF; q[x] = int(f / 100 · K1[x] + 0.5), at least 1 (`huffman.cpp:13-29`). The inverse DCT
is the fixed-point algorithm of Go's `image/jpeg` (`idct.cpp`, Wang 1984; constants 2048·√2·cos(kπ/16) and 181): rows
with a shortcut for all-zero AC (DC << 3), then columns, arithmetic shifts. Pixel = result + 128, clipped to 0–255.

**Placing segments** (`lrpt_msumr_reader.cpp:33-93`), per channel, in 32-bit unsigned arithmetic:

- 43 packets per 8-row scan (14 segments × 3 channels + 1 telemetry), so a segment's place comes from its 14-bit
  sequence count. `rollover` += 16,384 when the count goes from above 13,926 to below 2,458.
- The channel's first valid segment sets `offset` = (seq + (MCUN/14 > seq ? 16,384 : 0) − MCUN/14 + rollover) mod 43.
  Until then `offset` is 2^32 − 1, which also marks a channel with no data.
- id = (seq + rollover − offset) / 43 · 14 + MCUN/14. The segment is **dropped** if the channel's id span with it,
  max(last, id) − min(first, id), would exceed 20,000; otherwise first, last and the previous sequence count are
  updated and the segment is stored, replacing any earlier one with the same id.
- All of this is unsigned 32-bit. If a channel's first segment has seq < offset (the recording starts just after the
  14-bit count wrapped, part-way into a scan), seq − offset wraps and its id is near 2^32 / 43 · 14 ≈ 1.4 × 10^9.
  The channel's later segments, back in small ids, are then dropped by the 20,000 rule, and the shared extent spans
  the gap between channels. Found while building gs-image's vectors (scripts/gen_msumr_vectors.py); not seen on a
  real pass. gs-image refuses an image over 11,440 rows (`kMaxRows`, the most one channel's span allows) rather
  than allocate it; the Python model would try to.

**Image extent** (`getChannel`, `lrpt_msumr_reader.cpp:96-201`): all channels share one extent.

- L = the channel with the smallest offset below 43, the lowest-numbered on a tie (6 if none). SatDump's "lowest
  transmitted channel" is always channel 0: its loop sets it on the first pass whether or not channel 0 has data.
- Over the channels with data: F = smallest first id, E = largest last id; also the smallest first and largest last
  id of the channels numbered below L (Fb, Eb) and of those at or above it (Fa, Ea), each 2^32 − 1 / 0 when empty.
- If L ≠ 0, with ⌊x⌋ = x − x mod 14: a = ⌊Fb⌋ ≥ ⌊Fa⌋, b = ⌊Eb⌋ < ⌊Ea⌋. A channel below L takes F −= 14 if a and
  E −= 14 if b; a channel at or above L takes F += 14 if not a and E += 14 if not b.
- E += 14 (the last scan is included). For a channel with no segment F = 0 and E = 0. Both are rounded down to a
  multiple of 14; the image is the scans from F up to, not including, E.

1,568 × 8 pixels per scan, segments left to right by id; a missing or invalid segment is 0. A channel with no
segment gives no image. `module_meteor_msumr_lrpt.cpp:272-276` saves each as `MSU-MR-<n>.png` (8-bit grey), with no
fill (`fill_missing` defaults to false, `pipelines/Meteor-M.json:167-171`).
