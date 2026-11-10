"""Hardware BER campaign (buildplan §8.4): synthetic recordings at Eb/N0 points, replayed through the board.

    PYTHONPATH=. python scripts/ber_board.py --iface <host IP on the cable> [--points 2,2.5,...] [--max-files N]
        [--speed X] [--post BIT] [--pre BIT]

Each recording is one of WAVEFORMS clean waveforms (FRAMES CADUs each, cached in build/ber/) plus fresh AWGN at the
point's Eb/N0, quantized to cu8. It is replayed twice from a freshly programmed board: on the normal receiver
(post-RS CADUs) and on the RS_WRITEBACK = 0 build (pre-RS CADUs: after Viterbi, NRZ-M and the derandomizer). Each
CADU that comes back is matched to its sent frame (nearest in Hamming distance, in order), and bit errors are
counted over the RS body (pre-RS, 1,020 bytes) or the 892 data bytes (post-RS). A point stops once both curves have
MIN_ERRORS errors or after --max-files recordings; below MIN_ERRORS errors a point is an upper bound (CLAUDE.md).

Eb/N0 is per bit into the convolutional encoder (model/channel.noise_sigma, code rate 1/2), the same axis as the
model's ber_awgn.csv; the RS and ASM overheads are not taken out. In AWGN the errors come from the noise, so fresh
noise on a repeated payload gives independent samples; the payloads only vary the bit patterns.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import numpy.typing as npt
from scipy.stats import chi2

from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from scripts.board_rx import replay

OUT = Path("build/ber")
FRAMES = 300
WAVEFORMS = 4
WAVE_SEEDS = [3000 + k for k in range(WAVEFORMS)]
CARRIER_HZ = 151_000.0  # the NCO word below is 151,016.7 Hz: a 16.7 Hz residual for the loops
NCO_WORD = 0x25C1_1200  # set by SET_NCO before each replay (docs/protocol.md "Control commands")
USABLE = FRAMES - 2  # frame 0 is lost to pull-in, the last one is cut by the end of the recording
MIN_ERRORS = 100
WINDOW = 40  # frames searched ahead of the last match
UNMATCHED = 0.2  # a CADU farther than this fraction of bits from every candidate is no sent frame
PRE = slice(4, 1024)  # RS body: what RS sees
POST = slice(4, 4 + 892)  # data bytes after RS (signal-spec.md)


def _wave(seed: int) -> None:
    """Cache one clean waveform (complex64) and its truth frames (plain CADUs, 1,024 bytes each)."""
    path = OUT / f"wave_{seed}.npy"
    if path.exists():
        return
    plain, on_air = build_cadus(FRAMES, seed)
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    x = apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, CARRIER_HZ, 0.0, 0.7)
    np.save(OUT / f"truth_{seed}.npy", plain)
    np.save(path, x.astype(np.complex64))


def recording(ebn0_db: float, wave_seed: int, noise_seed: int, path: Path) -> None:
    x = np.load(OUT / f"wave_{wave_seed}.npy").astype(np.complex128)
    sigma = noise_sigma(ebn0_db, TxConfig().fs)
    to_cu8(awgn(x, sigma, noise_seed), full_scale=4 * sigma).tofile(path)


@dataclass
class Count:
    matched: int = 0
    unmatched: int = 0
    bits: int = 0
    errors: int = 0


def count_errors(cadus: list[bytes], truth: npt.NDArray[np.uint8], region: slice) -> Count:
    """Match each received CADU (in arrival order) to the nearest sent frame at most WINDOW after the last match;
    count bit errors over `region` of the matched ones."""
    c = Count()
    nbits = 8 * len(range(*region.indices(truth.shape[1])))
    t_bits = np.unpackbits(truth[:, region], axis=1)
    last = -1
    for data in cadus:
        got = np.unpackbits(np.frombuffer(data, dtype=np.uint8)[region])
        lo, hi = last + 1, min(last + 1 + WINDOW, truth.shape[0])
        if lo >= hi:
            c.unmatched += 1
            continue
        dist = np.count_nonzero(t_bits[lo:hi] != got, axis=1)
        k = int(np.argmin(dist))
        if dist[k] > UNMATCHED * nbits:
            c.unmatched += 1
            continue
        c.matched += 1
        c.bits += nbits
        c.errors += int(dist[k])
        last = lo + k
    return c


def upper95(errors: int, bits: int) -> float:
    """One-sided 95% upper bound on the error rate (Poisson; 3.0 / bits at zero errors)."""
    return float(chi2.ppf(0.95, 2 * (errors + 1)) / 2 / bits) if bits else float("nan")


def campaign(iface: str, points: list[float], max_files: int, speed: str, post_bit: str, pre_bit: str) -> int:
    from analysis.common import write_result

    OUT.mkdir(parents=True, exist_ok=True)
    with Pool(WAVEFORMS) as pool:
        pool.map(_wave, WAVE_SEEDS)
    truths = {s: np.load(OUT / f"truth_{s}.npy") for s in WAVE_SEEDS}
    cu8 = OUT / "point.cu8"
    rows: list[list[object]] = []
    for ebn0 in points:
        acc = {"pre": Count(), "post": Count()}
        rs_words = rs_failed = gap = lost = late = ovf = files = 0
        while files < max_files and min(acc["pre"].errors, acc["post"].errors) < MIN_ERRORS:
            wave = WAVE_SEEDS[files % WAVEFORMS]
            recording(ebn0, wave, int(ebn0 * 1000) * 1000 + files, cu8)
            for mode, bit in (("pre", pre_bit), ("post", post_bit)):
                rp = replay(cu8, iface, speed, bit, NCO_WORD)
                c = count_errors([x.data for x in rp.cadus], truths[wave], PRE if mode == "pre" else POST)
                a = acc[mode]
                a.matched, a.unmatched, a.bits, a.errors = (a.matched + c.matched, a.unmatched + c.unmatched,
                                                            a.bits + c.bits, a.errors + c.errors)
                if mode == "pre":  # the pre-RS build reports what RS would do, on exactly these bytes
                    rs_words += 4 * len(rp.cadus)
                    rs_failed += sum(x < 0 for cd in rp.cadus for x in cd.corrections)
                gap += rp.stats.get("ingest_gap", 0)
                lost += rp.stats.get("ingest_lost", 0)
                late += rp.stats.get("ingest_late", 0)
                ovf += rp.stats.get("eth_ovf_lost", 0)
            files += 1
            print(f"{ebn0} dB, file {files}: pre-RS {acc['pre'].errors}/{acc['pre'].bits}, post-RS "
                  f"{acc['post'].errors}/{acc['post'].bits}", flush=True)
        for mode, curve in (("pre", "viterbi_board"), ("post", "viterbi_rs_board")):
            a = acc[mode]
            enough = a.errors >= MIN_ERRORS
            rows.append([curve, ebn0, files, files * USABLE, a.matched, max(0, files * USABLE - a.matched -
                         a.unmatched), a.unmatched, a.bits, a.errors, a.errors / a.bits if enough and a.bits else "",
                         "" if enough else upper95(a.errors, a.bits), rs_words if mode == "pre" else "",
                         rs_failed if mode == "pre" else "", gap, lost, late, ovf])
        write_result(  # after every point, so a stopped campaign keeps what it measured
            "ber_board",
            ["curve", "ebn0_db", "files", "frames_usable", "frames_matched", "frames_missing", "frames_unmatched",
             "bits", "errors", "ber", "ber_upper95", "rs_codewords", "rs_codewords_failed", "ingest_gap",
             "ingest_lost", "ingest_late", "eth_ovf_lost"],
            rows,
            f"seeds {WAVE_SEEDS} (payloads, {FRAMES} CADUs each, scripts/ber_board.py), noise seed per recording "
            f"ebn0*1e6 + file; OQPSK at {CARRIER_HZ / 1e3:.0f} kHz, 0.37 symbol timing offset, 20 ppm clock, cu8 at "
            f"4 sigma full scale; replayed by gs-replay at {speed}x to arty_rx_eth_top (post-RS) and its "
            "RS_WRITEBACK=0 build (pre-RS), board reprogrammed per replay",
            command="PYTHONPATH=. python scripts/ber_board.py " + " ".join(sys.argv[1:]),
        )
    cu8.unlink(missing_ok=True)
    return 0


def main(argv: list[str]) -> int:
    opts = dict(zip(argv[0::2], argv[1::2], strict=False))
    if "--iface" not in opts:
        print(__doc__, file=sys.stderr)
        return 2
    points = [float(p) for p in opts.get("--points", "2,2.5,3,3.5,4,4.5,5").split(",")]
    return campaign(opts["--iface"], points, int(opts.get("--max-files", "20")), opts.get("--speed", "5.6"),
                    opts.get("--post", "build/board/arty_rx_eth_top.bit"),
                    opts.get("--pre", "build/board/arty_rx_eth_top_prers.bit"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
