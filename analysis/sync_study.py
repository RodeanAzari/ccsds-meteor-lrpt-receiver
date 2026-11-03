"""Measure the synchronization choices: loop order, Costas bandwidth, timing gain and pull-in."""

from __future__ import annotations

from multiprocessing import Pool

import numpy as np

from analysis.common import write_result
from model.channel import Floats, TxConfig, apply_carrier, awgn, modulate, noise_sigma
from model.coding import build_cadus, encode_stream
from model.receiver import (
    Complex,
    RxConfig,
    coarse_frequency,
    costas,
    data_bytes,
    ddc,
    decode_soft,
    matched_filter,
    oqpsk_timing,
    serial_soft,
)

FS2 = 256_000.0
TX = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
BANDWIDTHS = (0.0005, 0.001, 0.002, 0.003, 0.005, 0.008)
SEEDS = range(1, 5)


def _signal(frames: int, seed: int, ebn0: float, offset: float, ramp: float) -> tuple[Complex, set[bytes]]:
    plain, on_air = build_cadus(frames, seed)
    x = apply_carrier(modulate(encode_stream(on_air), TX), TX.fs, offset, ramp, 0.7)
    return awgn(x, noise_sigma(ebn0, TX.fs), seed), {bytes(p) for p in data_bytes(plain)}


def _prepared(x: Complex, cfg: RxConfig) -> Complex:
    """Matched-filtered signal with the coarse offset removed, so tracking is measured apart from pull-in."""
    mf = matched_filter(ddc(x, cfg), FS2, cfg.rrc_span)
    t = np.arange(mf.size) / FS2
    out: Complex = mf * np.exp(-2j * np.pi * coarse_frequency(mf, FS2, cfg) * t)
    return out


def _good(soft: Floats, truth: set[bytes]) -> int:
    return sum(bytes(c) in truth for c in data_bytes(decode_soft(soft).cadus))


def _order_case(args: tuple[str, float, int]) -> list[object]:
    order, offset, seed = args
    x, truth = _signal(14, seed, 8.0, offset, 0.0)
    cfg = RxConfig()
    mf = _prepared(x, cfg)
    max_rad = 2 * np.pi * cfg.costas_max_hz / FS2
    if order == "carrier_then_rail_gardner":
        y = oqpsk_timing(costas(mf, 0.002, max_rad)[0], FS2, cfg.timing_kp, cfg.timing_ki)
    else:
        per_rail = order == "rail_gardner_then_carrier"
        timed = oqpsk_timing(mf, FS2, cfg.timing_kp, cfg.timing_ki, per_rail_ted=per_rail)
        y = costas(timed, 0.002 * FS2 / 144_000.0, 2 * np.pi * cfg.costas_max_hz / 144_000.0)[0]
    return [order, offset, seed, 14, _good(serial_soft(y), truth)]


def _bw_case(args: tuple[float, float, int]) -> list[object]:
    bw, ebn0, seed = args
    x, truth = _signal(24, seed, ebn0, 1000.0, 30.0)
    cfg = RxConfig()
    locked = costas(_prepared(x, cfg), bw, 2 * np.pi * cfg.costas_max_hz / FS2)[0]
    y = oqpsk_timing(locked, FS2, cfg.timing_kp, cfg.timing_ki)
    return [bw, ebn0, seed, 24, _good(serial_soft(y), truth)]


def _timing_case(args: tuple[float, float, int]) -> list[object]:
    kp, ebn0, seed = args
    x, truth = _signal(24, seed, ebn0, 1000.0, 30.0)
    cfg = RxConfig()
    locked = costas(_prepared(x, cfg), cfg.costas_bw, 2 * np.pi * cfg.costas_max_hz / FS2)[0]
    y = oqpsk_timing(locked, FS2, kp, kp * kp / 4.0)
    return [kp, ebn0, seed, 24, _good(serial_soft(y), truth)]


def _pull_case(args: tuple[float, float, int]) -> list[object]:
    bw, offset, seed = args
    x, _ = _signal(30, seed, 6.0, offset, 0.0)
    cfg = RxConfig()
    mf = matched_filter(ddc(x, cfg), FS2, cfg.rrc_span)
    _, freq = costas(mf, bw, 2 * np.pi * cfg.costas_max_hz / FS2)
    # Average out loop jitter over 10 ms before comparing with the true offset.
    width = int(0.01 * FS2)
    hz = np.convolve(freq * FS2 / (2 * np.pi), np.ones(width) / width, mode="valid")
    outside = np.flatnonzero(np.abs(hz - offset) > 50.0)
    settled = outside.size == 0 or outside[-1] < hz.size - 1
    lock_s = (0.0 if outside.size == 0 else float(outside[-1] + 1) / FS2) if settled else float("nan")
    return [bw, offset, seed, f"{x.size / TX.fs:.2f}", f"{lock_s:.3f}"]


def main() -> None:
    orders = ("carrier_then_rail_gardner", "rail_gardner_then_carrier", "plain_gardner_then_carrier")
    with Pool() as pool:
        rows = pool.map(_order_case, [(o, f, s) for o in orders for f in (0.0, 300.0, 1000.0, 3000.0) for s in SEEDS])
        write_result(
            "sync_loop_order",
            ["order", "offset_hz", "seed", "frames_sent", "frames_good"],
            rows,
            "seeds 1 to 4, 8 dB, coarse estimate applied",
        )
        rows = pool.map(
            _bw_case, [(b, e, s) for b in BANDWIDTHS for e in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0) for s in SEEDS]
        )
        write_result(
            "sync_costas_bw",
            ["costas_bw", "ebn0_db", "seed", "frames_sent", "frames_good"],
            rows,
            "seeds 1 to 4, 1 kHz offset, 30 Hz/s ramp, coarse estimate applied",
        )
        rows = pool.map(
            _timing_case, [(k, e, s) for k in (0.005, 0.01, 0.02, 0.04) for e in (2.0, 3.0, 4.0, 6.0) for s in SEEDS]
        )
        write_result(
            "sync_timing_gain",
            ["timing_kp", "ebn0_db", "seed", "frames_sent", "frames_good"],
            rows,
            "seeds 1 to 4, 1 kHz offset, 30 Hz/s ramp, coarse estimate applied, Costas at the default bandwidth",
        )
        offsets = (100.0, 300.0, 1000.0, 2000.0, 3400.0)
        rows = pool.map(_pull_case, [(b, f, s) for b in BANDWIDTHS[2:] for f in offsets for s in SEEDS])
        write_result(
            "sync_pull_in",
            ["costas_bw", "offset_hz", "seed", "duration_s", "lock_time_s"],
            rows,
            "seeds 1 to 4, 6 dB, no coarse estimate. Lock is within 50 Hz (10 ms average) to the end of the run; "
            "nan means no lock",
        )


if __name__ == "__main__":
    main()
