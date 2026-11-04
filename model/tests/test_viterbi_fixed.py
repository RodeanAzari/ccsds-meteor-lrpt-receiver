"""Bit-true quantizer and Viterbi ACS: each choice has a reason; these tests fail if the reason stops holding."""

from __future__ import annotations

import numpy as np

from model.coding import conv_encode, viterbi_decode
from model.sync_fixed import ONE
from model.viterbi_fixed import MEMORY, max_branch_metric, path_metric_bits, quantize, viterbi_fixed

SEED = 13


def _noisy_soft(
    rng: np.random.Generator, sigma: float, blocks: int = 32, n: int = 4096
) -> tuple[np.ndarray, np.ndarray]:
    """Coded +-1 plus noise, power-normalized as the AGC does, in sync units."""
    data = rng.integers(0, 2, (blocks, n), dtype=np.uint8)
    coded = np.stack([conv_encode(d) for d in data]).astype(np.float64) * 2 - 1
    x = (coded + sigma * rng.standard_normal(coded.shape)) / np.sqrt(1 + sigma * sigma)
    return data, np.round(x * ONE).astype(np.int64)


def test_quantizer_levels_are_symmetric() -> None:
    # An asymmetric quantizer favours one bit value in every branch metric. Negating a sample (in one's
    # complement, -s-1, which is what flips the sign of a midrise level) must mirror its level.
    s = np.arange(-3 * ONE, 3 * ONE, dtype=np.int64)
    for bits, shift in ((3, 10), (4, 9)):
        top = (1 << bits) - 1
        assert np.array_equal(quantize(-s - 1, bits, shift), top - quantize(s, bits, shift))


def test_modulo_path_metrics_decide_exactly_as_the_float_decoder() -> None:
    # The RTL never normalizes path metrics; it relies on modulo comparison at the derived width. At very low SNR
    # (the largest metric spread), the integer decoder must still match the float decoder bit for bit, and the
    # spread must stay within the bound the width was derived from.
    rng = np.random.default_rng(SEED)
    for bits, shift in ((3, 10), (4, 9)):
        _, soft = _noisy_soft(rng, sigma=1.0)
        u = quantize(soft, bits, shift)
        got, spread = viterbi_fixed(u, bits, path_metric_bits(bits))
        want = viterbi_decode((u - ((1 << bits) - 1) / 2).astype(np.float64))
        assert np.array_equal(got, want)
        assert spread <= MEMORY * max_branch_metric(bits)


def test_the_exactness_check_is_not_vacuous() -> None:
    # If the input never spread the metrics, the test above would pass with any width. Registers with half-range
    # below the observed spread must break decoding on the same kind of input.
    rng = np.random.default_rng(SEED)
    _, soft = _noisy_soft(rng, sigma=1.0)
    u = quantize(soft, 3, 10)
    good, spread = viterbi_fixed(u, 3, path_metric_bits(3))
    narrow = (spread // 2).bit_length() + 1  # half-range 2^(narrow-1) <= spread / 2
    bad, _ = viterbi_fixed(u, 3, narrow)
    assert not np.array_equal(bad, good)


def test_sliding_traceback_decides_the_right_bit_at_the_right_time() -> None:
    # An off-by-one in the traceback shifts every output bit by one step. On a clean signal every depth and both
    # start rules must return the data exactly (state 0 needs enough depth for the paths to merge first).
    rng = np.random.default_rng(SEED)
    data, soft = _noisy_soft(rng, sigma=0.0, blocks=4, n=1024)
    u = quantize(soft, 4, 10)
    for start, depth in (("best", 6), ("best", 48), ("zero", 48)):
        got, _ = viterbi_fixed(u, 4, path_metric_bits(4), depth=depth, start=start)
        assert np.array_equal(got, data)


def test_long_traceback_reproduces_full_block_decisions() -> None:
    # The RTL decides each bit after a finite traceback; that is only safe if, at a depth well past the survivors'
    # merge length, it agrees with the maximum-likelihood (full-block) decision on every bit.
    rng = np.random.default_rng(SEED)
    _, soft = _noisy_soft(rng, sigma=np.sqrt(1 / 10 ** (3.0 / 10)), blocks=32, n=4096)
    u = quantize(soft, 4, 10)
    full, _ = viterbi_fixed(u, 4, path_metric_bits(4))
    for start in ("best", "zero"):
        sliding, _ = viterbi_fixed(u, 4, path_metric_bits(4), depth=120, start=start)
        assert np.array_equal(sliding[:, :-120], full[:, :-120])
