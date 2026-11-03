"""Coding-layer checks. Each pins a spec fact whose loss would silently stop frames decoding."""

from __future__ import annotations

import numpy as np

from model.coding import (
    ASM_BYTES,
    build_cadus,
    conv_encode,
    encode_stream,
    encoded_asm_pattern,
    lrpt_rs,
    nrzm_decode,
    nrzm_encode,
    pn_table,
    randomize,
    viterbi_decode,
)


def test_encoded_asm_matches_satdump_constant() -> None:
    # A wrong pattern means the correlator never finds a frame. Constant from SatDump's
    # module_meteor_lrpt_decoder.cpp, with the 12 state-dependent symbols excluded.
    constant = 0xFC4EF4FD0CC2DF89
    expected = np.array([(constant >> (51 - i)) & 1 for i in range(52)])
    pattern = (encoded_asm_pattern() > 0).astype(int)
    assert np.array_equal(pattern, expected) or np.array_equal(pattern, 1 - expected)


def test_pn_starts_like_satdump_table_and_has_period_255() -> None:
    pn = pn_table()
    assert pn[:8].tolist() == [0xFF, 0x48, 0x0E, 0xC0, 0x9A, 0x0D, 0x70, 0xBC]
    body = np.zeros(510, dtype=np.uint8)
    out = randomize(body)
    assert np.array_equal(out[:255], out[255:])


def test_asm_is_not_randomized_and_body_is() -> None:
    plain, on_air = build_cadus(1, seed=3)
    assert bytes(on_air[0, :4]) == ASM_BYTES
    assert np.array_equal(randomize(on_air[0, 4:]), plain[0, 4:])


def test_nrzm_survives_inversion() -> None:
    # This property is why a 180 degree carrier ambiguity needs no correction.
    rng = np.random.default_rng(1)
    bits = rng.integers(0, 2, 200, dtype=np.uint8)
    encoded = nrzm_encode(bits)
    assert np.array_equal(nrzm_decode(encoded)[1:], bits[1:])
    assert np.array_equal(nrzm_decode(1 - encoded)[1:], bits[1:])


def test_conv_impulse_response_is_g1_then_g2() -> None:
    # Output order and absence of inversion are from signal-spec.md.
    impulse = np.zeros(7, dtype=np.uint8)
    impulse[0] = 1
    coded = conv_encode(impulse)
    assert coded[0::2].tolist() == [1, 1, 1, 1, 0, 0, 1]  # 171 octal
    assert coded[1::2].tolist() == [1, 0, 1, 1, 0, 1, 1]  # 133 octal


def test_viterbi_corrects_errors_a_hard_slicer_cannot() -> None:
    rng = np.random.default_rng(2)
    bits = rng.integers(0, 2, 400, dtype=np.uint8)
    soft = 2.0 * conv_encode(bits).astype(np.float64) - 1.0
    flips = rng.choice(np.arange(20, 780, 30), size=20, replace=False)
    soft[flips] = -soft[flips]
    assert np.array_equal(viterbi_decode(soft)[:390], bits[:390])


def test_viterbi_decodes_complemented_stream_to_complement() -> None:
    # Both generators have odd weight, so an inverted carrier gives inverted bits. NRZ-M then removes them.
    rng = np.random.default_rng(4)
    bits = rng.integers(0, 2, 300, dtype=np.uint8)
    soft = 2.0 * conv_encode(bits).astype(np.float64) - 1.0
    assert np.array_equal(viterbi_decode(-soft)[10:290], 1 - bits[10:290])


def test_cadu_codewords_are_valid_and_interleaved_by_position() -> None:
    # Wrong interleave order makes every codeword uncorrectable even on a perfect signal.
    plain, _ = build_cadus(1, seed=5)
    rs = lrpt_rs()
    body = plain[0, 4:]
    for c in range(4):
        assert not any(rs.syndromes(body[c::4].tolist()))
    assert any(rs.syndromes(body[0:255].tolist()))


def test_stream_length_is_rate_half() -> None:
    _, on_air = build_cadus(2, seed=6)
    assert encode_stream(on_air).size == 2 * 2 * 1024 * 8
