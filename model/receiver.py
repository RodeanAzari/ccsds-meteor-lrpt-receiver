"""Floating-point LRPT receiver: the algorithm model in CLAUDE.md §8.1.

Chain: ingest -> DDC -> RRC -> Costas -> OQPSK timing -> frame sync -> Viterbi -> NRZ-M -> derandomize -> RS.
The carrier comes before timing because a per-rail Gardner detector fails on an unresolved carrier.
Evidence: docs/decisions/0002-oqpsk-timing.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
from scipy import ndimage, signal

from model.channel import RRC_ALPHA, SYMBOL_RATE, Complex, Floats, rrc
from model.coding import (
    ASM_TRANSIENT_SYMBOLS,
    CADU_BITS,
    CADU_BYTES,
    CODED_FRAME_SYMBOLS,
    RS_INTERLEAVE,
    RS_K,
    encoded_asm_pattern,
    frame_to_cadu,
    viterbi_decode,
)


@dataclass(frozen=True)
class RxConfig:
    fs: float = 1_024_000.0
    tune_offset_hz: float = 0.0
    decimation: int = 4
    cic_order: int = 3
    comp_taps: int = 31
    rrc_span: int = 8
    # rad/sample at 256 kS/s. data/results/sync_costas_bw.csv: 0.0005 to 0.001 decode the most frames.
    # 0.001 keeps twice the bandwidth of 0.0005 for Doppler-rate and coarse-estimate error.
    costas_bw: float = 0.001
    costas_max_hz: float = 15_000.0
    timing_kp: float = 0.02
    timing_ki: float = 1e-4
    # Fraction of the ideal peak. Random data has sigma ~ 1/sqrt(52) = 0.14 and reaches about 0.7 across a
    # 100k-position search, so 0.55 caused false locks that blocked the real one.
    sync_threshold: float = 0.75
    flywheel: int = 4  # consecutive sync misses before returning to search
    viterbi_margin_bits: int = 64
    coarse_log2: int = 18  # about 1 s of signal at 256 kS/s
    coarse_threshold: float = 11.0  # peak over median. Noise reaches about 9; the signal 13 at 2 dB


@dataclass
class RxResult:
    cadus: npt.NDArray[np.uint8]  # shape (frames, 1024), derandomized and RS-corrected data
    rs_corrections: npt.NDArray[np.int64]  # shape (frames, 4), -1 for uncorrectable
    asm_errors: npt.NDArray[np.int64]
    frame_starts: npt.NDArray[np.int64]
    hypothesis: list[tuple[bool, bool]] = field(default_factory=list)  # (alternate_sign, swap_pairs) per frame
    costas_freq_hz: Floats = field(default_factory=lambda: np.zeros(0))
    soft: Floats = field(default_factory=lambda: np.zeros(0))


def ingest_cu8(raw: npt.NDArray[np.uint8]) -> Complex:
    x = (raw.astype(np.float64) - 127.5) / 127.5
    iq: Complex = x[0::2] + 1j * x[1::2]
    return iq


def ddc(x: Complex, cfg: RxConfig) -> Complex:
    """Remove DC, mix down the tuning offset, then CIC decimate and compensate."""
    t = np.arange(x.size) / cfg.fs
    mixed = (x - x.mean()) * np.exp(-2j * np.pi * cfg.tune_offset_hz * t)
    kernel = np.ones(1)
    for _ in range(cfg.cic_order):
        kernel = np.convolve(kernel, np.ones(cfg.decimation) / cfg.decimation)
    decimated = signal.fftconvolve(mixed, kernel, mode="same")[:: cfg.decimation]
    out: Complex = signal.fftconvolve(decimated, comp_fir_taps(cfg), mode="same")
    return out


def comp_fir_taps(cfg: RxConfig) -> Floats:
    """Inverse-droop FIR flat across the signal band (72k * 1.5 / 2 = 54 kHz plus Doppler margin)."""
    fs2 = cfg.fs / cfg.decimation
    freq = np.array([0.0, 20e3, 40e3, 60e3, 70e3, 100e3, fs2 / 2])
    droop = (np.sinc(freq / fs2) / np.sinc(freq / cfg.fs)) ** cfg.cic_order
    gain = 1.0 / droop
    gain[-2:] = 0.0
    taps: Floats = signal.firwin2(cfg.comp_taps, freq, gain, fs=fs2)
    return taps


def rrc_taps(fs: float, span: int) -> Floats:
    """RRC matched-filter taps, `span` symbols each side, unity DC gain."""
    sps = fs / SYMBOL_RATE
    half = round(span * sps)
    taps: Floats = rrc(np.arange(-half, half + 1) / sps, RRC_ALPHA) / sps
    return taps


def normalize_rails(y: Complex) -> Complex:
    """Scale to unit average rail power: the AGC's job in hardware, so loop gains don't depend on signal level."""
    power = float(np.mean(np.abs(y) ** 2))
    normalized: Complex = y / np.sqrt(power / 2.0)
    return normalized


def matched_filter(x: Complex, fs: float, span: int) -> Complex:
    """RRC matched filter, then normalize to unit average rail power."""
    y: Complex = signal.fftconvolve(x, rrc_taps(fs, span), mode="same")
    return normalize_rails(y)


def costas(x: Complex, bw: float, max_rad: float) -> tuple[Complex, Floats]:
    """Fourth-order Costas loop run on every sample. Returns (derotated, frequency in rad/sample)."""
    denom = 1.0 + 2 * 0.707 * bw + bw * bw
    alpha = 4 * 0.707 * bw / denom
    beta = 4 * bw * bw / denom
    re = x.real.tolist()
    im = x.imag.tolist()
    out_re = [0.0] * len(re)
    out_im = [0.0] * len(re)
    track = [0.0] * len(re)
    phase, freq = 0.0, 0.0
    cos, sin = np.cos, np.sin
    for n, (a, b) in enumerate(zip(re, im, strict=True)):
        c, s = float(cos(phase)), float(sin(phase))
        i = a * c + b * s
        q = b * c - a * s
        out_re[n] = i
        out_im[n] = q
        err = (q if i > 0 else -q) - (i if q > 0 else -i)
        err = max(-1.0, min(1.0, err))
        freq = max(-max_rad, min(max_rad, freq + beta * err))
        phase += freq + alpha * err
        track[n] = freq
    y: Complex = np.array(out_re) + 1j * np.array(out_im)
    return y, np.array(track)


def coarse_frequency(x: Complex, fs: float, cfg: RxConfig) -> float:
    """Estimate the carrier offset in Hz from the fourth-power spectral line, or 0.0 if no line stands out.

    Scans windows in time because a real pass starts in noise. Narrow Costas loops pull in too slowly on
    their own (data/results/sync_pull_in.csv).
    """
    size = 2**cfg.coarse_log2
    freqs = np.fft.fftfreq(2 * size, 1 / fs)
    search = np.abs(freqs) < 4 * cfg.costas_max_hz
    window = np.hanning(size)
    for start in range(0, max(1, x.size - size + 1), size // 2):
        seg = x[start : start + size]
        spectrum = np.abs(np.fft.fft(seg**4 * window[: seg.size], 2 * size))
        peak = int(np.argmax(np.where(search, spectrum, 0.0)))
        if spectrum[peak] > cfg.coarse_threshold * np.median(spectrum):
            return float(freqs[peak]) / 4.0
    return 0.0


def _cubic(p0: float, p1: float, p2: float, p3: float, mu: float) -> float:
    """Catmull-Rom interpolation between p1 and p2 (Farrow-style in the RTL)."""
    return p1 + 0.5 * mu * (p2 - p0 + mu * (2 * p0 - 5 * p1 + 4 * p2 - p3 + mu * (3 * (p1 - p2) + p3 - p0)))


def oqpsk_timing(x: Complex, fs: float, kp: float, ki: float, per_rail_ted: bool = True) -> Complex:
    """Resample to 2 samples/symbol with a Gardner detector.

    Even outputs are strobes on the real rail and midpoints on the imaginary rail. Odd outputs are the reverse.
    The loop settles wherever that holds, so rail parity needs no later correction.
    """
    nominal = fs / SYMBOL_RATE / 2.0
    limit = nominal * 0.01
    re = x.real.tolist()
    im = x.imag.tolist()
    last = len(re) - 3
    out_re: list[float] = []
    out_im: list[float] = []
    pos, integ = 1.0, 0.0
    n = 0
    while pos < last:
        k = int(pos)
        mu = pos - k
        yi = _cubic(re[k - 1], re[k], re[k + 1], re[k + 2], mu)
        yq = _cubic(im[k - 1], im[k], im[k + 1], im[k + 2], mu)
        out_re.append(yi)
        out_im.append(yq)
        err = 0.0
        if n >= 2:
            if per_rail_ted:
                rail = out_re if n % 2 == 0 else out_im
                err = rail[n - 1] * (rail[n - 2] - rail[n])
            elif n % 2 == 0:  # plain QPSK Gardner: both rails at the same instants, once per symbol
                err = out_re[n - 1] * (out_re[n - 2] - out_re[n]) + out_im[n - 1] * (out_im[n - 2] - out_im[n])
        err = max(-1.0, min(1.0, err))
        integ = max(-limit, min(limit, integ + ki * err))
        pos += nominal + integ + kp * err
        n += 1
    y: Complex = np.array(out_re) + 1j * np.array(out_im)
    return y


def serial_soft(y: Complex) -> Floats:
    """Interleave strobes into one soft stream: re[0], im[1], re[2], im[3], ...

    Normalized by a running mean of |soft| over one coded frame, not the whole stream: frame sync's threshold is a
    fraction of the ideal peak, and a real pass fades and swells within a run (docs/log.md, 2026-11-21).
    """
    soft = y.imag.copy()
    soft[0::2] = y.real[0::2]
    window = min(CODED_FRAME_SYMBOLS, soft.size)
    level = ndimage.uniform_filter1d(np.abs(soft), window, mode="nearest")
    normalized: Floats = soft / level
    return normalized


def _hypothesis_patterns() -> list[tuple[bool, bool, Floats]]:
    """All distinct phase hypotheses on the serial stream (signal-spec.md, Phase ambiguity).

    Carrier rotations reduce to alternate-sign masks at some stream offset. Absolute correlation
    absorbs overall inversion, so 0 and 180 degrees are one case and 90 and 270 are another.
    """
    base = encoded_asm_pattern()
    out: list[tuple[bool, bool, Floats]] = []
    for swap in (False, True):
        p = base.copy()
        if swap:
            # The pattern begins on a G1 symbol, since 12 is even.
            p[0::2], p[1::2] = base[1::2].copy(), base[0::2].copy()
        for alternate in (False, True):
            q = p.copy()
            if alternate:
                q[1::2] = -q[1::2]
            out.append((alternate, swap, q))
    return out


def _undo_hypothesis(soft: Floats, alternate: bool, swap: bool) -> Floats:
    """Soft must start on a frame-aligned even symbol."""
    out = soft.copy()
    if alternate:
        out[1::2] = -out[1::2]
    if swap:
        pairs = out.size // 2
        first = out[0 : 2 * pairs : 2].copy()
        out[0 : 2 * pairs : 2] = out[1 : 2 * pairs : 2]
        out[1 : 2 * pairs : 2] = first
    return out


def frame_sync(soft: Floats, threshold: float, flywheel: int) -> list[tuple[int, bool, bool]]:
    """SEARCH -> VERIFY -> LOCK with a flywheel. Returns (frame start, alternate, swap)."""
    hypotheses = _hypothesis_patterns()
    ideal = float(hypotheses[0][2].size)
    corrs = [np.abs(signal.fftconvolve(soft, p[::-1], mode="valid")) / ideal for _, _, p in hypotheses]
    size = corrs[0].size
    frames: list[tuple[int, bool, bool]] = []
    pos = 0
    while pos < size:
        # SEARCH: the earliest peak confirmed one frame later (VERIFY).
        best: tuple[int, int] | None = None
        for h, corr in enumerate(corrs):
            above = np.flatnonzero(corr[pos:] > threshold) + pos
            confirmed = above[(above + CODED_FRAME_SYMBOLS < size)]
            confirmed = confirmed[corr[confirmed + CODED_FRAME_SYMBOLS] > threshold]
            if confirmed.size and (best is None or confirmed[0] < best[0]):
                best = (int(confirmed[0]), h)
        if best is None:
            break
        p, h = best
        alternate, swap, _ = hypotheses[h]
        # LOCK. Frames under a missed ASM are held back and emitted only if the lock is later confirmed.
        # On loss, search resumes just past the last confirmed ASM, so no frame is emitted twice.
        pending: list[tuple[int, bool, bool]] = []
        last_good = p
        while p < size and len(pending) <= flywheel:
            frame = (p - ASM_TRANSIENT_SYMBOLS, alternate, swap)
            if corrs[h][p] > threshold:
                frames.extend(pending)
                frames.append(frame)
                pending = []
                last_good = p
            else:
                pending.append(frame)
            p += CODED_FRAME_SYMBOLS
        pos = last_good + 1 if len(pending) > flywheel else size
    return frames


def decode_soft(soft: Floats, cfg: RxConfig = RxConfig()) -> RxResult:
    """Frame sync, Viterbi, NRZ-M, ASM check, derandomize, RS. Input is the serial soft stream."""
    return decode_frames(soft, frame_sync(soft, cfg.sync_threshold, cfg.flywheel), cfg)


def decode_frames(soft: Floats, frames: list[tuple[int, bool, bool]], cfg: RxConfig = RxConfig()) -> RxResult:
    """Viterbi, NRZ-M, ASM check, derandomize, RS on the frames a frame sync found: (start, alternate, swap)."""
    margin = cfg.viterbi_margin_bits * 2
    usable = [f for f in frames if f[0] >= margin + 2 and f[0] + CODED_FRAME_SYMBOLS + margin <= soft.size]
    n = len(usable)
    cadus = np.zeros((n, CADU_BYTES), dtype=np.uint8)
    corrections = np.zeros((n, RS_INTERLEAVE), dtype=np.int64)
    asm_errors = np.zeros(n, dtype=np.int64)
    window = CODED_FRAME_SYMBOLS + 2 * margin
    for chunk in range(0, n, 16):
        batch = usable[chunk : chunk + 16]
        blocks = np.stack(
            [_undo_hypothesis(soft[s - margin : s - margin + window], alt, swap) for s, alt, swap in batch]
        )
        decoded = viterbi_decode(blocks)
        for j in range(len(batch)):
            first = cfg.viterbi_margin_bits
            f = chunk + j
            cadus[f], asm_errors[f], corrections[f] = frame_to_cadu(
                decoded[j, first : first + CADU_BITS], int(decoded[j, first - 1])
            )
    return RxResult(
        cadus=cadus,
        rs_corrections=corrections,
        asm_errors=asm_errors,
        frame_starts=np.array([u[0] for u in usable], dtype=np.int64),
        hypothesis=[(u[1], u[2]) for u in usable],
        soft=soft,
    )


def demodulate(x: Complex, cfg: RxConfig = RxConfig()) -> tuple[Floats, Floats, Complex]:
    """Return (serial soft stream, Costas frequency in Hz, 2-sps samples)."""
    return demodulate_baseband(ddc(x, cfg), cfg)


def demodulate_baseband(baseband: Complex, cfg: RxConfig = RxConfig()) -> tuple[Floats, Floats, Complex]:
    """demodulate() from the DDC output on, so the bit-true DDC (model/ddc_fixed.py) can feed it."""
    return demodulate_filtered(matched_filter(baseband, cfg.fs / cfg.decimation, cfg.rrc_span), cfg)


def demodulate_filtered(filtered: Complex, cfg: RxConfig = RxConfig()) -> tuple[Floats, Floats, Complex]:
    """demodulate() from the RRC output on, so the bit-true RRC (model/rrc_fixed.py) can feed it."""
    fs2 = cfg.fs / cfg.decimation
    filtered = normalize_rails(filtered)
    coarse_hz = coarse_frequency(filtered, fs2, cfg)
    derotated: Complex = filtered * np.exp(-2j * np.pi * coarse_hz * np.arange(filtered.size) / fs2)
    locked, freq = costas(derotated, cfg.costas_bw, 2 * np.pi * cfg.costas_max_hz / fs2)
    samples = oqpsk_timing(locked, fs2, cfg.timing_kp, cfg.timing_ki)
    return serial_soft(samples), coarse_hz + freq * fs2 / (2 * np.pi), samples


def decode_iq(x: Complex, cfg: RxConfig = RxConfig()) -> RxResult:
    soft, freq, _ = demodulate(x, cfg)
    result = decode_soft(soft, cfg)
    result.costas_freq_hz = freq
    return result


def data_bytes(cadus: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    """The bytes gs-diff compares: per-codeword data, excluding parity. See signal-spec.md."""
    stop: int = 4 + RS_K * RS_INTERLEAVE
    out: npt.NDArray[np.uint8] = cadus[:, 4:stop]
    return out
