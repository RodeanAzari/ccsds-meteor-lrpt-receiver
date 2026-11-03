# satdump_crosscheck

- **Commit:** `2d5f38084a0f1758b9bae847137ccedec662712a` plus `scripts/satdump_crosscheck.py` (committed alongside this file)
- **Command:** `PYTHONPATH=. python scripts/satdump_crosscheck.py`
- **Tools:** SatDump 1.2.2+gb79af48-2 (Ubuntu 26.04 package), Python 3.14.4, NumPy 2.5.4
- **Input:** synthetic, seed 2026, 300 frames, Eb/N0 8 dB, timing offset 0.37 symbol, 20 ppm clock error, signal
  150 kHz above centre plus the carrier offset in each row. Row 1 is the `make synthetic-iq` recording
  (sha256 `189e66d2…f185b`). No real recording.

SatDump's receive chain decodes our transmit chain: in every case, every CADU SatDump writes matches truth on the
892 data bytes, with no mismatches and no duplicates. That is independent evidence that our modulator, coding and
framing agree with SatDump on the parameters in `docs/signal-spec.md` (RRC, convolutional output order, NRZ-M,
randomizer, RS basis). It is still a synthetic signal; nothing here confirms the spec against the satellite.

The leading frames SatDump misses depend on the carrier offset: it starts at frame 1 with no offset, frame 70 with a
static 1 kHz offset, and frame 38 with 1 kHz plus a 30 Hz/s ramp. That pattern points to SatDump's carrier
acquisition time, not a fault at the start of our signal. The last 4 frames (296–299) are missing in every case,
including zero offset; the cause is not established. SatDump exits with code 1 in every case even though it writes
the CADU file; the cause is not established either. For comparison, our own receiver loses only the first and last
frame of each run (`fer_full_chain.csv`).
