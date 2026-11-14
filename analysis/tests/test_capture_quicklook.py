"""capture_quicklook: the triage that decides whether a pass recording had a signal at all.

Why it matters: a wrong sign or I/Q order puts Meteor's band at the mirror frequency, so a real signal reads as
"nothing at 137.9 MHz" and we blame the antenna; a wrong dB scale (20 log vs 10 log) or a misplaced row turns a
marginal pass into a strong one or puts it at the wrong time. Synthetic cu8 with known content pins each of these.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from analysis import capture_quicklook as q

FS = q.FS
RNG = np.random.default_rng(7)


def to_cu8(z: np.ndarray) -> np.ndarray:
    """Complex samples (LSB) to interleaved unsigned 8-bit I/Q, I first, as rtl_sdr writes it."""
    out = np.empty(2 * len(z), dtype=np.uint8)
    out[0::2] = np.clip(np.round(z.real + 127.5), 0, 255)
    out[1::2] = np.clip(np.round(z.imag + 127.5), 0, 255)
    return out


def noise(n: int, rms: float = 20.0) -> np.ndarray:
    return (RNG.standard_normal(n) + 1j * RNG.standard_normal(n)) * rms / np.sqrt(2)


def band_noise(n: int, centre_hz: float, width_hz: float, power: float) -> np.ndarray:
    """Noise flat over centre ± width/2, total power `power` (LSB²)."""
    spec = np.fft.fft(noise(n, 1.0))
    f = np.fft.fftfreq(n, 1 / FS)
    spec[np.abs(f - centre_hz) >= width_hz / 2] = 0
    z = np.fft.ifft(spec)
    return z * np.sqrt(power / np.mean(np.abs(z) ** 2))


def test_positive_offset_lands_above_centre() -> None:
    # A tone at +150 kHz must read at +150 kHz, not at the mirror -150 kHz (I/Q swap or missing fftshift).
    n = 1 << 18
    t = np.arange(n) / FS
    raw = to_cu8(noise(n) + 30 * np.exp(2j * np.pi * 150e3 * t))
    p, f = q.psd(q.iq(raw)), q.freqs()
    # Tone power 900 over a floor of 400 LSB² spread across a 100 kHz band: 10 log10(1 + 900 / (400 * bw/fs)).
    assert q.band_db(p, f, 150e3, -250e3) == pytest.approx(10 * np.log10(1 + 900 / (400 * 100e3 / FS)), abs=0.5)
    assert abs(q.band_db(p, f, -150e3, -250e3)) < 0.5


def test_band_3db_above_floor_reads_3db() -> None:
    # In-band power equal to the floor's in-band power doubles it: +3.01 dB, not 6 (20 log) or 1.5.
    n = 1 << 19
    floor_rms = 20.0
    sig = band_noise(n, 150e3, 120e3, floor_rms**2 * 120e3 / FS)
    p, f = q.psd(q.iq(to_cu8(noise(n, floor_rms) + sig))), q.freqs()
    assert q.band_db(p, f, 150e3, -250e3) == pytest.approx(3.01, abs=0.3)


def test_health_counts_rms_and_clipping() -> None:
    raw = np.array([0, 255, 128, 127] * 250, dtype=np.uint8)  # half the bytes clipped
    rms, clip = q.health(raw)
    assert clip == pytest.approx(50.0)
    assert rms == pytest.approx(np.std(raw[0::2].astype(np.float32)))
    _, clean = q.health(to_cu8(noise(10_000, 5.0)))
    assert clean == 0.0


def test_band_outside_window_is_an_error() -> None:
    p, f = q.psd(q.iq(to_cu8(noise(1 << 14)))), q.freqs()
    with pytest.raises(ValueError, match="outside"):
        q.band_db(p, f, 600e3, -250e3)  # > fs/2: e.g. Meteor on 137.1 MHz with 137.75 tuning


def test_time_rows_follow_the_signal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Signal only in the second 2 s row: row 0 flat, row 1 up, and stamped 2 s after the start.
    n_row = int(2 * FS)
    z = noise(2 * n_row)
    z[n_row:] += band_noise(n_row, 150e3, 120e3, 20.0**2 * 120e3 / FS * 3)  # +6 dB in band
    path = tmp_path / "pass.cu8"
    to_cu8(z).tofile(path)
    q.main(["time", str(path), "2026-11-14T18:49:17", "--row-s", "2"])
    rows = [line.split() for line in capsys.readouterr().out.splitlines()[1:]]
    assert [r[0] for r in rows] == ["18:49:17", "18:49:19"]
    assert abs(float(rows[0][3])) < 0.5
    assert float(rows[1][3]) == pytest.approx(6.0, abs=0.6)
