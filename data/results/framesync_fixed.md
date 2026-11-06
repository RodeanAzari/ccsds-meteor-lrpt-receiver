# framesync_fixed

- **Commit:** `44c121b72c119b036395c193d38a11ae0d707393 (with uncommitted changes)`
- **Command:** `python -m framesync_study` (module in `analysis/`)
- **Tools:** Python 3.14.4, NumPy 2.5.4, SciPy 1.18.1
- **Input:** synthetic, seeds 1 to 3, 30 frames, 1 kHz offset + 30 Hz/s, 0.37-symbol timing offset, 20 ppm clock; host coarse estimate, bit-true chain from reset; threshold 0.75 (48/64), flywheel 4, 4-candidate queue. No real recording.

This compares the streaming, bit-true frame sync the RTL will implement (`model/framesync_fixed.py`, ADR 0010) with the float model's offline one, on the same bit-true sync-chain output and through the same back end.

- **Decoded frames:** the streaming version decodes at least as many correct frames in every run. From 2.5 dB up it finds the identical frame list.
- **Seed 1 slip:** this seed has a slip at frame 20, where the timing loop drops one sample, shifting the ASM by a symbol and changing the phase hypothesis. The streaming version follows it (`fixed_slips` = 1). At 2.0 dB that gives it 27 good frames against the float model's 25, which loses lock and searches again.
- **Below 2 dB:** at 1.5 dB both decode 0–8 of 30, and the streaming version emits more frames that fail RS. It emits flywheel frames at once, flagged, instead of holding them back.
- **No queue overflow:** no candidate peak was ever dropped (`fixed_dropped`).

Out of 30 frames sent, 28 at most decode: the first and last are lost at the capture edges, as in every chain run.
