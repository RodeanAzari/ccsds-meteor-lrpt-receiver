"""BER against theory: proves the modulator, noise scaling and Viterbi before any RTL depends on them."""

from __future__ import annotations

from multiprocessing import Pool

import numpy as np
from scipy.special import erfc

from analysis.common import write_result
from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, rrc
from model.coding import build_cadus, conv_encode, encode_stream, nrzm_decode, viterbi_decode
from model.receiver import RxConfig, data_bytes, decode_iq

MIN_ERRORS = 100  # CLAUDE.md §8.4: below this a point is reported as an upper bound
# Soft-decision K=7 r=1/2 distance spectrum (free distance 10, bit-error weights).
SPECTRUM = ((10, 36), (12, 211), (14, 1404), (16, 11633), (18, 77433))
SPS = 8


def q(x: float) -> float:
    return float(0.5 * erfc(x / np.sqrt(2)))


def union_bound(ebn0_db: float) -> float:
    ebn0 = 10 ** (ebn0_db / 10)
    return sum(w * q(np.sqrt(2 * d * 0.5 * ebn0)) for d, w in SPECTRUM)


def uncoded_case(ebn0_db: float) -> list[object]:
    """Real waveform, coherent matched filter at known strobes, no coding. Checks modulate() and noise_sigma()."""
    rng = np.random.default_rng(int(ebn0_db * 10) + 1000)
    tx = TxConfig(fs=SPS * 72_000.0)
    taps = rrc(np.arange(-8 * SPS, 8 * SPS + 1) / SPS) / SPS
    errors, bits = 0, 0
    while errors < MIN_ERRORS and bits < 4_000_000:
        data = rng.integers(0, 2, 200_000, dtype=np.uint8)
        noisy = awgn(modulate(data, tx), noise_sigma(ebn0_db, tx.fs, code_rate=1.0), int(rng.integers(1 << 31)))
        y = np.convolve(noisy, taps, mode="same")
        strobes = np.arange(16, data.size // 2 - 16)
        i_hat = y.real[strobes * SPS] > 0
        q_hat = y.imag[strobes * SPS + SPS // 2] > 0
        errors += int(np.count_nonzero(i_hat != data[0::2][strobes]) + np.count_nonzero(q_hat != data[1::2][strobes]))
        bits += 2 * strobes.size
    return ["uncoded_waveform", ebn0_db, bits, errors, errors / bits, q(np.sqrt(2 * 10 ** (ebn0_db / 10)))]


def viterbi_case(args: tuple[float, bool]) -> list[object]:
    """Soft Viterbi on an AWGN symbol channel, measured before or after NRZ-M decoding."""
    ebn0_db, nrzm = args
    rng = np.random.default_rng(int(ebn0_db * 10) + 2000 + nrzm)
    ebn0 = 10 ** (ebn0_db / 10)
    sigma = np.sqrt(1 / ebn0)  # Es = Eb/2 at r=1/2, sigma^2 = N0/2 per symbol, amplitude 1
    blocks, n, edge = 128, 4096, 64
    errors, bits = 0, 0
    while errors < MIN_ERRORS and bits < 60_000_000:
        data = rng.integers(0, 2, (blocks, n), dtype=np.uint8)
        coded = np.stack([conv_encode(d) for d in data]).astype(np.float64) * 2 - 1
        decoded = viterbi_decode(coded + sigma * rng.standard_normal(coded.shape))
        if nrzm:
            # Transmit bits are the NRZ-M encoding of the payload, so compare decoded differences.
            got = np.stack([nrzm_decode(d) for d in decoded])[:, edge:-edge]
            want = np.stack([nrzm_decode(d) for d in data])[:, edge:-edge]
        else:
            got, want = decoded[:, edge:-edge], data[:, edge:-edge]
        errors += int(np.count_nonzero(got != want))
        bits += got.size
    label = "viterbi_after_nrzm" if nrzm else "viterbi_soft"
    return [label, ebn0_db, bits, errors, errors / bits, union_bound(ebn0_db)]


def chain_case(args: tuple[float, int]) -> list[object]:
    """Whole receiver from samples to RS output, with a Doppler ramp and timing offset."""
    ebn0_db, seed = args
    frames = 40
    plain, on_air = build_cadus(frames, seed)
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    x = apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, 1000.0, 30.0, 0.7)
    result = decode_iq(awgn(x, noise_sigma(ebn0_db, tx.fs), seed), RxConfig())
    truth = {bytes(p) for p in data_bytes(plain)}
    good = sum(bytes(c) in truth for c in data_bytes(result.cadus))
    return [ebn0_db, seed, frames, result.cadus.shape[0], good]


def main() -> None:
    with Pool() as pool:
        rows = pool.map(uncoded_case, [float(e) for e in range(0, 9)])
        rows += pool.map(viterbi_case, [(e / 2, False) for e in range(0, 11)])
        rows += pool.map(viterbi_case, [(e / 2, True) for e in range(0, 11)])
        write_result(
            "ber_awgn",
            ["curve", "ebn0_db", "bits", "errors", "ber", "theory"],
            rows,
            "seeds derived from Eb/N0. Theory: Q(sqrt(2Eb/N0)) for uncoded, union bound for Viterbi",
        )
        rows = pool.map(chain_case, [(e / 2, s) for e in range(2, 13) for s in range(1, 6)])
        write_result(
            "fer_full_chain",
            ["ebn0_db", "seed", "frames_sent", "frames_synced", "frames_good"],
            rows,
            "seeds 1 to 5, 1 kHz offset, 30 Hz/s ramp, 0.37 symbol timing offset, 20 ppm clock",
        )


if __name__ == "__main__":
    main()
