"""Bit-level LRPT coding: frames, randomizer, NRZ-M, K=7 r=1/2 convolutional code, Viterbi.

Every parameter comes from docs/signal-spec.md.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from model.rs import RSCode

Bits = npt.NDArray[np.uint8]
Soft = npt.NDArray[np.float64]

ASM = 0x1ACFFC1D
ASM_BYTES = ASM.to_bytes(4, "big")
CADU_BYTES = 1024
CADU_BITS = CADU_BYTES * 8
CODED_FRAME_SYMBOLS = CADU_BITS * 2
RS_INTERLEAVE = 4
RS_K = 223
RS_N = 255
DATA_BYTES = RS_K * RS_INTERLEAVE
# First 12 encoded ASM symbols depend on the previous frame's last 6 bits.
ASM_TRANSIENT_SYMBOLS = 12

_G1_TAPS = (0, 1, 2, 3, 6)  # 171 octal
_G2_TAPS = (0, 2, 3, 5, 6)  # 133 octal
_N_STATES = 64


def lrpt_rs() -> RSCode:
    return RSCode(m=8, prim_poly=0x187, fcr=112, prim=11, nroots=32)


def pn_table() -> npt.NDArray[np.uint8]:
    """CCSDS randomizer: h(x) = x^8+x^7+x^5+x^3+1, all-ones seed, 255 bytes."""
    reg = [1] * 8
    bits = np.zeros(255 * 8, dtype=np.uint8)
    for i in range(bits.size):
        bits[i] = reg[0]
        reg = [*reg[1:], reg[0] ^ reg[3] ^ reg[5] ^ reg[7]]
    table: npt.NDArray[np.uint8] = np.packbits(bits)
    return table


_PN = pn_table()


def randomize(body: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    """XOR with the PN sequence restarted at the first byte. Its own inverse."""
    pn: npt.NDArray[np.uint8] = _PN[np.arange(body.size) % 255]
    out: npt.NDArray[np.uint8] = np.bitwise_xor(body, pn)
    return out


def nrzm_encode(bits: Bits, last: int = 0) -> Bits:
    state = np.bitwise_xor.accumulate(np.concatenate(([last], bits)).astype(np.uint8))
    out: Bits = state[1:]
    return out


def nrzm_decode(bits: Bits, last: int = 0) -> Bits:
    prev = np.concatenate(([last], bits[:-1])).astype(np.uint8)
    out: Bits = np.bitwise_xor(bits, prev)
    return out


def conv_encode(bits: Bits, state: int = 0) -> Bits:
    """Encode to G1, G2, G1, G2, ... with no inversion. `state` holds 6 prior bits, newest in the LSB."""
    prior = np.array([(state >> (5 - i)) & 1 for i in range(6)], dtype=np.uint8)
    full = np.concatenate((prior, bits))
    n = bits.size
    out = np.zeros(2 * n, dtype=np.uint8)
    for rail, taps in enumerate((_G1_TAPS, _G2_TAPS)):
        acc = np.zeros(n, dtype=np.uint8)
        for d in taps:
            acc ^= full[6 - d : 6 - d + n]
        out[rail::2] = acc
    return out


def encoded_asm_pattern() -> npt.NDArray[np.float64]:
    """Bipolar encoded NRZ-M ASM, without the state-dependent first 12 symbols."""
    asm_bits = np.unpackbits(np.frombuffer(ASM_BYTES, dtype=np.uint8))
    coded = conv_encode(nrzm_encode(asm_bits, last=0))
    pattern: npt.NDArray[np.float64] = 2.0 * coded[ASM_TRANSIENT_SYMBOLS:].astype(np.float64) - 1.0
    return pattern


def _trellis() -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Return predecessor states and branch signs (+1 if the coded bit is 1) for each next state."""
    pred = np.zeros((_N_STATES, 2), dtype=np.int64)
    sign_g1 = np.zeros((_N_STATES, 2))
    sign_g2 = np.zeros((_N_STATES, 2))
    for ns in range(_N_STATES):
        for j in range(2):
            s = (ns >> 1) | (j << 5)
            reg = (s << 1) | (ns & 1)
            pred[ns, j] = s
            g1 = sum((reg >> d) & 1 for d in _G1_TAPS) & 1
            g2 = sum((reg >> d) & 1 for d in _G2_TAPS) & 1
            sign_g1[ns, j] = 2 * g1 - 1
            sign_g2[ns, j] = 2 * g2 - 1
    return pred, sign_g1, sign_g2


_PRED, _SIGN_G1, _SIGN_G2 = _trellis()


def viterbi_decode(soft: npt.NDArray[Any]) -> Bits:
    """Maximum-likelihood decode of a batch, shape (blocks, 2*bits). Positive soft = bit 1.

    Uses full-block traceback from the best end state. Traceback depth is a Phase D study.
    """
    if soft.ndim == 1:
        return viterbi_decode(soft[np.newaxis, :])[0]
    blocks, n_sym = soft.shape
    n = n_sym // 2
    metrics = np.zeros((blocks, _N_STATES))
    decisions = np.zeros((n, blocks, _N_STATES), dtype=bool)
    p0, p1 = _PRED[:, 0], _PRED[:, 1]
    s10, s11 = _SIGN_G1[:, 0], _SIGN_G1[:, 1]
    s20, s21 = _SIGN_G2[:, 0], _SIGN_G2[:, 1]
    for t in range(n):
        a = soft[:, 2 * t, np.newaxis]
        b = soft[:, 2 * t + 1, np.newaxis]
        m0 = metrics[:, p0] + a * s10 + b * s20
        m1 = metrics[:, p1] + a * s11 + b * s21
        choose1 = m1 > m0
        decisions[t] = choose1
        metrics = np.where(choose1, m1, m0)
        metrics -= metrics.max(axis=1, keepdims=True)
    out = np.zeros((blocks, n), dtype=np.uint8)
    state = metrics.argmax(axis=1)
    rows = np.arange(blocks)
    for t in range(n - 1, -1, -1):
        out[:, t] = state & 1
        state = (state >> 1) | (decisions[t, rows, state].astype(np.int64) << 5)
    return out


def build_cadus(n_frames: int, seed: int) -> tuple[npt.NDArray[np.uint8], npt.NDArray[np.uint8]]:
    """Return (plain, on_air) arrays of shape (n_frames, 1024).

    `plain` has the RS-encoded body before randomization. `on_air` is what enters NRZ-M.
    """
    rng = np.random.default_rng(seed)
    rs = lrpt_rs()
    plain = np.zeros((n_frames, CADU_BYTES), dtype=np.uint8)
    on_air = np.zeros_like(plain)
    asm = np.frombuffer(ASM_BYTES, dtype=np.uint8)
    for f in range(n_frames):
        data = rng.integers(0, 256, size=DATA_BYTES, dtype=np.uint8)
        body = np.zeros(RS_N * RS_INTERLEAVE, dtype=np.uint8)
        for c in range(RS_INTERLEAVE):
            body[c::RS_INTERLEAVE] = rs.encode(data[c::RS_INTERLEAVE].tolist())
        plain[f] = np.concatenate((asm, body))
        on_air[f] = np.concatenate((asm, randomize(body)))
    return plain, on_air


def encode_stream(on_air: npt.NDArray[np.uint8]) -> Bits:
    """Serialize CADUs through NRZ-M and the convolutional code."""
    bits = np.unpackbits(on_air.reshape(-1))
    coded: Bits = conv_encode(nrzm_encode(bits))
    return coded
