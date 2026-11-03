"""Whole-chain checks on synthetic signals: the data must come back, whatever the channel did."""

from __future__ import annotations

import numpy as np
import pytest

from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, rrc, to_cu8
from model.coding import CODED_FRAME_SYMBOLS, build_cadus, encode_stream
from model.receiver import RxConfig, data_bytes, decode_iq, frame_sync, ingest_cu8

N_FRAMES = 6
SEED = 11


def _recovered(tx: TxConfig, ebn0_db: float = 12.0, rx: RxConfig | None = None, **carrier: float) -> tuple[int, int]:
    """Return (frames recovered intact, frames with any uncorrectable codeword)."""
    plain, on_air = build_cadus(N_FRAMES, SEED)
    x = apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, **carrier)
    y = awgn(x, noise_sigma(ebn0_db, tx.fs), SEED)
    result = decode_iq(y, rx or RxConfig(fs=tx.fs))
    truth = {bytes(p) for p in data_bytes(plain)}
    good = sum(bytes(c) in truth for c in data_bytes(result.cadus))
    return good, int(np.any(result.rs_corrections < 0, axis=1).sum())


def test_rrc_has_unit_energy_per_symbol() -> None:
    # noise_sigma assumes this. If it broke, every BER curve would shift sideways.
    t = np.arange(-40, 40, 1 / 64)
    assert np.isclose(np.sum(rrc(t) ** 2) / 64, 1.0, atol=1e-3)


@pytest.mark.parametrize("q_leads", [False, True])
@pytest.mark.parametrize("swap_rails", [False, True])
@pytest.mark.parametrize("phase", [0.2, 0.2 + np.pi / 2, 0.2 + np.pi, 0.2 + 3 * np.pi / 2])
def test_every_phase_and_rail_arrangement_decodes(q_leads: bool, swap_rails: bool, phase: float) -> None:
    # Which rail leads and which carries G1 are open in signal-spec.md. The receiver must not care,
    # or a wrong guess about the real satellite would look like a dead receiver.
    tx = TxConfig(q_leads=q_leads, swap_rails=swap_rails)
    good, bad = _recovered(tx, phase_rad=phase, offset_hz=300.0)
    assert good >= N_FRAMES - 3
    assert bad == 0


def test_timing_offset_and_clock_error_decode() -> None:
    good, bad = _recovered(TxConfig(timing_offset_sym=0.37, clock_ppm=50.0), offset_hz=200.0)
    assert good >= N_FRAMES - 3
    assert bad == 0


def test_doppler_ramp_decodes() -> None:
    # 30.7 Hz/s is the peak rate for an overhead pass at 830 km. Test beyond it.
    good, bad = _recovered(TxConfig(), offset_hz=2000.0, ramp_hz_per_s=-60.0)
    assert good >= N_FRAMES - 3
    assert bad == 0


def test_tuning_offset_and_cu8_round_trip_decode() -> None:
    # Follows the real capture path: tuned off-signal, 8-bit samples, a DC spike from the RTL-SDR.
    plain, on_air = build_cadus(N_FRAMES, SEED)
    tx = TxConfig()
    sigma = noise_sigma(12.0, tx.fs)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, offset_hz=150_000.0), sigma, SEED)
    raw = to_cu8(x + 0.5 * sigma, full_scale=4 * sigma)
    result = decode_iq(ingest_cu8(raw), RxConfig(fs=tx.fs, tune_offset_hz=150_000.0))
    truth = {bytes(p) for p in data_bytes(plain)}
    assert sum(bytes(c) in truth for c in data_bytes(result.cadus)) >= N_FRAMES - 3


def test_random_data_cannot_false_lock_before_the_real_frame() -> None:
    # Regression: at threshold 0.55, two chance peaks one frame apart locked a wrong hypothesis,
    # and the flywheel then held it through the real frames. Zero frames decoded, with a perfect signal.
    for seed in range(5):
        plain, on_air = build_cadus(N_FRAMES, seed)
        tx = TxConfig(q_leads=True)
        x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, 300.0, phase_rad=1.77), 1.0, seed)
        result = decode_iq(x, RxConfig())
        truth = {bytes(p) for p in data_bytes(plain)}
        assert sum(bytes(c) in truth for c in data_bytes(result.cadus)) >= N_FRAMES - 3


def test_lock_loss_never_emits_a_frame_twice() -> None:
    # Regression: after a carrier cycle slip, frames emitted under the flywheel were found again
    # under the new phase hypothesis, so frames synced exceeded frames sent (223 of 200 in
    # data/results/fer_full_chain.csv). That would inflate every frame count.
    _, on_air = build_cadus(12, 3)
    soft = 2.0 * encode_stream(on_air).astype(np.float64) - 1.0
    slip = 5 * CODED_FRAME_SYMBOLS
    soft[slip + 1 :: 2] *= -1.0  # a 90 degree slip from frame 5 onward
    starts = [s for s, _, _ in frame_sync(soft, RxConfig().sync_threshold, RxConfig().flywheel)]
    assert len(starts) == len(set(starts))
    assert starts == [f * CODED_FRAME_SYMBOLS for f in range(12)]


def test_noise_only_produces_no_frames() -> None:
    # False locks would feed garbage to the RS decoder and inflate frame counts.
    rng = np.random.default_rng(1)
    x = rng.standard_normal(600_000) + 1j * rng.standard_normal(600_000)
    assert decode_iq(x, RxConfig()).cadus.shape[0] == 0
