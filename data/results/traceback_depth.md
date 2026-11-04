# traceback_depth

- **Commit:** `07796c5d856eabce132776052c7496f500d0a498`
- **Command:** `python -m traceback_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, noise seed from Eb/N0 and job index; 4-bit soft, step ONE/4; depth 0 = full-block traceback. No real recording.

BER of the 4-bit decoder against traceback depth, starting from the best state or from state 0, with full-block traceback (depth 0) as the reference. Every configuration sees the same noise and the same ACS decisions, so differences come only from the traceback. From the best state, depth 48 is within 2% of full-block at 3 dB and 5% at 2.5 dB; depth 60 within 1%. From state 0, the survivors need longer to merge: depth 72 is within 1–4%, depth 96 within 0.1% at 2.5 dB and equal at 3 and 4 dB. Every point has at least 100 errors. AWGN symbol channel; synthetic only. Decision: ADR 0008 (state 0, depth 96).
