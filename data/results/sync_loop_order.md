# sync_loop_order

- **Commit:** `950a988244d0dd72432f974d62e8da0ffc88fea3`
- **Command:** `python -m sync_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, seeds 1 to 4, 8 dB, coarse estimate applied. No real recording.

Carrier recovery has to come before OQPSK timing recovery. Carrier first decoded all 48 reachable frames at every offset. A per-rail Gardner run first was erratic (9 to 48 of 48), and a plain QPSK Gardner run first decoded none. A per-rail detector on an unresolved carrier sees the other rail half a symbol off, which scales its error by cos(2θ), so the average is zero while the carrier rotates. See ADR 0002.
