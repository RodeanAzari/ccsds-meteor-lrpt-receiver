# Recording manifest

Full recordings stay off-repo. List each one here. Gain is the RTL-SDR tuner gain, with the SAWbird+ NOAA LNA
powered from the V3 bias tee (CLAUDE.md §1).

| File | SHA-256 | Satellite | UTC start | Max elev. | Centre freq. | Sample rate | Gain | Mode | SatDump decoded? | SatDump version |
|---|---|---|---|---|---|---|---|---|---|---|
| `~/recordings/2026-11-13T1914Z_meteor-m2-4.cu8` (2,345,402,368 B, cu8) | `d6cf4e72a290112663f08f6215c9b884372324a9099162f38ca80d2d2a778070` | Meteor-M N2-4 | 2026-11-13 19:14:55 (to 19:34:00) | 64° predicted (own SGP4 from SatDump TLE epoch 26315.27, not cross-checked) | 137.75 MHz (signal 137.9, +150 kHz) | 1.024 MS/s | 3.7 dB | 72k assumed (not confirmed for Nov.) | **No**: 72k and 80k pipelines both NOSYNC (peak SNR 0.3 / 1.0 dB). Signal visible ~19:22–19:24 only, 4–5 dB above the floor in 100 kHz | 1.2.2+gb79af48-2 |
| `~/recordings/2026-11-14T1855Z_meteor-m2-4.cu8` (2,730,491,904 B, cu8) | `b76b1531f1713c92d11c83cd090a8cd90cbe95e9a616688e3eb742ee6aa5f652` | Meteor-M N2-4 | 2026-11-14 18:49:17 (to 19:11:30; the name's 1855Z is the predicted rise) | 41.5° predicted (`analysis/passes.py`) | 137.75 MHz (signal 137.9, +150 kHz) | 1.024 MS/s | 12.5 dB (1.4–2.7% of samples at 0 or 255) | 72k assumed (not confirmed for Nov.) | **No**: 72k pipeline NOSYNC, peak SNR 0.0 dB, 0 CADUs. No Meteor at 137.9 MHz; a ~100 kHz hump drifting 137.35–137.63 MHz for the whole file (interference). Open field, antenna on a chair (photo `docs/media/2026-11-14_phase-0_antenna-setup.webp`) | 1.2.2+gb79af48-2 (prints v1.2.3) |
