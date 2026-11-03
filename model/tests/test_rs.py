"""Reed-Solomon checks, including an independent reference: the library SatDump itself uses."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from model.coding import lrpt_rs
from model.rs import RSCode

VECTORS = Path(__file__).parents[2] / "data" / "samples" / "rs223_libcorrect.json"


def _random_word(code: RSCode, seed: int) -> tuple[list[int], np.random.Generator]:
    rng = np.random.default_rng(seed)
    return code.encode(rng.integers(0, code.q + 1, code.k).tolist()), rng


def _corrupt(word: list[int], count: int, code: RSCode, rng: np.random.Generator) -> list[int]:
    out = word[:]
    for p in rng.choice(code.n, size=count, replace=False):
        out[int(p)] ^= int(rng.integers(1, code.q + 1))
    return out


def test_encoder_matches_libcorrect() -> None:
    # If our field or generator differed from SatDump's, this is where it shows.
    code = lrpt_rs()
    for text in json.loads(VECTORS.read_text()):
        word = list(bytes.fromhex(text))
        assert code.encode(word[:223]) == word
        assert not any(code.syndromes(word))


def test_corrects_up_to_the_limit() -> None:
    code = lrpt_rs()
    for count in (0, 1, 2, 8, 15, 16):
        word, rng = _random_word(code, 100 + count)
        fixed, found = code.decode(_corrupt(word, count, code, rng))
        assert fixed == word
        assert found == count


def test_errors_in_parity_are_corrected_too() -> None:
    code = lrpt_rs()
    word, _ = _random_word(code, 7)
    bad = word[:]
    bad[-1] ^= 0x5A
    bad[223] ^= 0x01
    assert code.decode(bad) == (word, 2)


def test_past_the_limit_is_flagged_not_silently_returned_as_correct() -> None:
    # 17 errors must never come back reported as a successful decode of the original word.
    code = lrpt_rs()
    flagged = 0
    for seed in range(30):
        word, rng = _random_word(code, 200 + seed)
        fixed, found = code.decode(_corrupt(word, 17, code, rng))
        assert fixed != word
        flagged += found == -1
    assert flagged == 30


def test_parameterization_is_real_rs544_514_over_gf1024() -> None:
    # CLAUDE.md §3.7: the same code must instantiate as a shortened GF(2^10) code.
    code = RSCode(m=10, prim_poly=0x409, fcr=0, prim=1, nroots=30, n=544)
    assert code.k == 514
    word, rng = _random_word(code, 9)
    fixed, found = code.decode(_corrupt(word, 15, code, rng))
    assert fixed == word
    assert found == 15
