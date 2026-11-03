# ddc_nco_sfdr

- **Commit:** `ea90d38c53fb7dbfce2a230411ed2954439b44d8`
- **Command:** `python -m ddc_fixed_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, 2026 (random words). No real recording.

The NCO meets its requirement with margin. Across 64 random tuning words, spur-free dynamic range is 71.6–72.8 dB, matching the −6.02·12 ≈ −72 dB estimate for 12 bits of table phase, and about 24 dB under the 8-bit input's dynamic range. Row 1, the 150 kHz default tuning word, reads 109.9 dB only because 150 kHz is an exact multiple of the table's phase step, so there is no truncation error; Doppler pre-correction will move the word, so the random words are the figure to quote. See ADR 0003.
