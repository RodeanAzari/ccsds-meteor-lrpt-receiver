"""Quick look at a raw RTL-SDR recording (cu8): is there a signal, and is the capture healthy?

    python -m analysis.capture_quicklook time FILE START_UTC [--row-s 20] [--band MHZ ...]
    python -m analysis.capture_quicklook diff FILE ON0 ON1 OFF0 OFF1          (seconds from file start)

`time`: one row per --row-s seconds: rms of I (LSB), samples at 0 or 255 (%), and the power in each band relative
to the reference band (dB). A pass shows as the signal band rising and falling around the predicted maximum
elevation; local interference usually doesn't follow the pass. `diff`: on-pass minus off-pass power in 20 kHz bins
across the whole window, to find where a signal actually landed.

Field triage before SatDump (docs/log.md, 2026-11-13/14), not a measurement: nothing here writes data/results/.
PSDs are averaged over snapshots, so a 2.7 GB file takes about a minute. Defaults match the capture settings in
CLAUDE.md §1: 1.024 MS/s tuned to 137.75 MHz, Meteor at 137.9 MHz, reference 137.5 MHz (inside the SAWbird+
passband, clear of Meteor), 100 kHz bands.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import numpy as np

FS = 1.024e6  # CLAUDE.md §1 capture rate
TUNE_MHZ = 137.75  # CLAUDE.md §1: tuned 150 kHz below the signal
SIGNAL_MHZ = 137.9  # signal-spec.md: Meteor-M N2-4 LRPT
REF_MHZ = 137.5
BW_HZ = 100e3
NFFT = 4096
SNAP_FFTS = 16  # FFTs per snapshot
SNAPS_PER_ROW = 10


def iq(raw: np.ndarray) -> np.ndarray:
    """Interleaved unsigned 8-bit I/Q (I first) to complex, DC removed."""
    b = raw.astype(np.float32)
    z = (b[0::2] - 127.5) + 1j * (b[1::2] - 127.5)
    return z - z.mean()


def psd(z: np.ndarray) -> np.ndarray:
    """Mean Hann-windowed periodogram, fftshifted (bin k is at freqs()[k])."""
    m = len(z) // NFFT
    if m == 0:
        raise ValueError(f"need at least {NFFT} samples, got {len(z)}")
    frames = z[: m * NFFT].reshape(m, NFFT) * np.hanning(NFFT)
    return np.asarray(np.mean(np.abs(np.fft.fftshift(np.fft.fft(frames, axis=1), axes=1)) ** 2, axis=0))


def freqs(fs: float = FS) -> np.ndarray:
    return np.fft.fftshift(np.fft.fftfreq(NFFT, 1 / fs))


def band_db(p: np.ndarray, f: np.ndarray, centre_hz: float, ref_hz: float, bw_hz: float = BW_HZ) -> float:
    """Mean power in the band at centre_hz over the band at ref_hz (both baseband offsets), in dB."""
    sig, ref = np.abs(f - centre_hz) < bw_hz / 2, np.abs(f - ref_hz) < bw_hz / 2
    if not sig.any() or not ref.any():
        raise ValueError(f"band at {centre_hz:.0f} or {ref_hz:.0f} Hz is outside the captured window")
    return float(10 * np.log10(p[sig].mean() / p[ref].mean()))


def snapshot_psd(raw: np.ndarray, start: int, stop: int) -> np.ndarray:
    """PSD averaged over SNAPS_PER_ROW evenly spaced snapshots of raw[start:stop] (byte offsets)."""
    n = 2 * NFFT * SNAP_FFTS
    starts = np.linspace(start, max(start, stop - n), SNAPS_PER_ROW).astype(int) & ~1
    return np.mean([psd(iq(raw[s : s + n])) for s in starts], axis=0)


def health(raw: np.ndarray) -> tuple[float, float]:
    """(rms of I in LSB, % of all bytes at 0 or 255)."""
    clip = float(np.count_nonzero((raw == 0) | (raw == 255))) / len(raw) * 100
    return float(np.std(raw[0::2].astype(np.float32))), clip


def cmd_time(a: argparse.Namespace) -> None:
    raw = np.memmap(a.file, dtype=np.uint8, mode="r")
    f, t0 = freqs(a.fs), datetime.fromisoformat(a.start)
    offs = [(m - a.tune) * 1e6 for m in a.band]
    ref = (a.ref - a.tune) * 1e6
    n_row = int(a.row_s * a.fs) * 2
    print("time      rms_I  clip%  " + "  ".join(f"{m:.3f}MHz-ref_dB" for m in a.band))
    for r in range(len(raw) // n_row):
        rms, clip = health(np.asarray(raw[r * n_row : (r + 1) * n_row]))
        p = snapshot_psd(raw, r * n_row, (r + 1) * n_row)
        d = [band_db(p, f, o, ref, a.bw) for o in offs]
        bar = "#" * max(0, round(d[0] * 4))
        cells = "  ".join(f"{v:17.2f}" for v in d)
        print(f"{t0 + timedelta(seconds=r * a.row_s):%H:%M:%S}  {rms:5.1f}  {clip:5.2f}  {cells}  {bar}")


def cmd_diff(a: argparse.Namespace) -> None:
    raw = np.memmap(a.file, dtype=np.uint8, mode="r")
    f = freqs(a.fs)

    def window(t0: float, t1: float) -> np.ndarray:
        return snapshot_psd(raw, int(t0 * a.fs) * 2, int(t1 * a.fs) * 2)

    on, off = window(a.on0, a.on1), window(a.off0, a.off1)
    half = int(a.fs / 2 / 20e3) * 20
    for lo in range(-half, half, 20):
        m = (f >= lo * 1e3) & (f < (lo + 20) * 1e3)
        d = 10 * np.log10(on[m].mean() / off[m].mean())
        print(f"{a.tune + lo / 1e3:8.3f} MHz  {d:+5.2f}  {'#' * max(0, round(d * 5))}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fs", type=float, default=FS, help="sample rate, S/s")
    ap.add_argument("--tune", type=float, default=TUNE_MHZ, help="tuner centre frequency, MHz")
    ap.add_argument("--bw", type=float, default=BW_HZ, help="band width for band power, Hz")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("time", help="health and band power over time")
    t.add_argument("file")
    t.add_argument("start", help="UTC time of the first sample, ISO (e.g. 2026-11-14T18:49:17)")
    t.add_argument("--row-s", type=float, default=20.0)
    t.add_argument("--band", type=float, nargs="+", default=[SIGNAL_MHZ], help="band centres, MHz (first is barred)")
    t.add_argument("--ref", type=float, default=REF_MHZ, help="reference band centre, MHz")
    d = sub.add_parser("diff", help="on-pass minus off-pass spectrum, 20 kHz bins")
    d.add_argument("file")
    for name in ("on0", "on1", "off0", "off1"):
        d.add_argument(name, type=float)
    a = ap.parse_args(argv)
    {"time": cmd_time, "diff": cmd_diff}[a.cmd](a)


if __name__ == "__main__":
    main()
