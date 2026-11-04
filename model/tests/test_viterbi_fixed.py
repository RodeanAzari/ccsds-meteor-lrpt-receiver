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
