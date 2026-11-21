The float model decodes a real Meteor-M N2-4 pass, and every frame it shares with SatDump (the reference decoder) is identical in its 892 data bytes.

**Totals (2026-11-21 pass, 19:41:51–20:00:33 UTC, 30 s chunks overlapping 2 s, each from a cold start).**
- The model decoded 5,583 frames with all four RS codewords good; SatDump decoded 4,583.
- 4,557 frames are in both, and all 4,557 are equal. None differ.
- `equal_to_satdump`, `differ_from_satdump` and `model_only` per chunk count against SatDump's whole file; the total row counts the frames merged across chunks by (VCID, counter), since overlapping chunks decode some frames twice.

**Every difference is explained (counters placed against SatDump's first, last and missing frames, scratch run of this script's `decode_chunk`).**
- 946 model-only frames come before SatDump's first frame: 19:45:35 to about 19:48:10, where the model already decodes (90 to 263 RS-good frames per chunk) and SatDump has not yet synced.
- The other 80 model-only frames fall in SatDump's gaps as the signal fades at the end (19:56–19:57).
- The 26 SatDump-only frames are in the same fade, where the model's RS fails (63 and 12 failed frames in the 19:56:47 and 19:57:15 chunks).
- So the model starts decoding about 2.5 minutes earlier on the rising signal, and the two decoders trade a few frames as it fades. The model is a batch decoder restarted every 28 s, so its edge-of-pass numbers depend on the chunking.

**Rails and phase (signal-spec.md, "Which rail leads").**
- `hypotheses_rs_good` counts the winning hypothesis of every RS-good frame. swap = 0 in all of them (`swap1_rs_good=0`): the G1 symbol goes out half a symbol before its G2 partner.
- alt (the 90° rotation) changes between chunks: it is the carrier's phase ambiguity at each cold start, not a property of the signal.

**Other columns.** `median_carrier_hz` is the carrier left after the 150 kHz tuning offset: from about −350 Hz to −6.4 kHz, a ~6 kHz Doppler swing centred near −3.4 kHz (most likely the dongle's frequency error; not measured separately), changing fastest (closest approach) around 19:51–19:52. It stays well inside the ±15 kHz lock range. Chunks before 19:45 and after 19:57 decode nothing that passes RS (a few false frames each).

**Limits.** One pass, one recording, float model only (not the bit-true model or the RTL). SatDump's file runs from 0 s, the model from 240 s (19:41:51), which is before either decoder finds a frame.
