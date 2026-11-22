"""Decode a real pass with the float (or bit-true) model and compare its CADUs with SatDump's (buildplan §9, Phase A).

    python -m analysis.real_pass_study REC.cu8 SATDUMP.cadu --start-utc 2026-11-21T19:37:51 [--from-s S --to-s S]
        [--bit-true]

The recording is cut into chunks that overlap by more than one cold-start acquisition, each decoded from a cold
start (the model is a batch decoder), and frames are merged by VCDU key (VCID, counter). A model frame counts only
if all four RS codewords decode. --bit-true runs the bit-true chain instead (what the RTL computes, bit for bit:
host coarse estimate into the NCO, DDC, RRC, AGC, Costas, timing, 4-bit quantizer, frame sync, Viterbi, CADU stage)
and writes real_pass_fixed.csv. Against SatDump: same key and the same 892 data bytes (signal-spec.md, "What
gs-diff can compare") is a match; same key with other bytes is a difference. Writes one row per chunk, then a total row.
"""

from __future__ import annotations

import argparse
import collections
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from analysis.common import write_result
from model.cadu_fixed import cadus_from_windows
from model.framesync_fixed import decode_windows, frame_sync_fixed, windows
from model.receiver import RxConfig, data_bytes, decode_iq, ingest_cu8
from model.sync_fixed import demodulate_fixed, freq_hz
from model.viterbi_fixed import quantize

FS = 1_024_000  # CLAUDE.md §1 capture rate
TUNE_OFFSET_HZ = 150_000.0  # tuned 137.75 MHz, Meteor at 137.9 MHz (data/MANIFEST.md)
FRAME = 1024
DATA = slice(4, 4 + 892)  # signal-spec.md: SatDump leaves parity uncorrected, compare the data bytes only

# The RTL's settings (tb/cocotb/test_rx_chain_full.py, ADR 0005): 4-bit soft, step ONE/4, threshold 0.75, flywheel 4.
SOFT_BITS, SOFT_SHIFT, THR64, FLYWHEEL = 4, 10, 48, 4

Key = tuple[int, int]


def vcdu_key(frame: bytes) -> Key:
    """(VCID, virtual channel frame counter) from the VCDU primary header after the ASM (CCSDS 732.0-B)."""
    return frame[5] & 0x3F, int.from_bytes(frame[6:9], "big")


def decode_chunk(args: tuple[str, float, float]) -> dict[str, object]:
    path, start_s, dur_s = args
    raw = np.fromfile(path, dtype=np.uint8, count=int(dur_s * FS) * 2, offset=int(start_s * FS) * 2)
    r = decode_iq(ingest_cu8(raw), RxConfig(fs=FS, tune_offset_hz=TUNE_OFFSET_HZ))
    good = (r.rs_corrections >= 0).all(axis=1) if len(r.cadus) else np.zeros(0, dtype=bool)
    frames = {vcdu_key(bytes(c)): bytes(d) for c, d, g in zip(r.cadus, data_bytes(r.cadus), good, strict=True) if g}
    return {
        "start_s": start_s,
        "frames": frames,
        "decoded": len(r.cadus),
        "rs_failed": int((~good).sum()),
        "freq_hz": float(np.median(r.costas_freq_hz)),
        # RS-good frames only: the winning hypothesis is the evidence for signal-spec.md's rail/G1 item.
        "hypotheses": collections.Counter(h for h, g in zip(r.hypothesis, good, strict=True) if g),
    }


def decode_chunk_fixed(args: tuple[str, float, float]) -> dict[str, object]:
    path, start_s, dur_s = args
    raw = np.fromfile(path, dtype=np.uint8, count=int(dur_s * FS) * 2, offset=int(start_s * FS) * 2)
    cfg = RxConfig(fs=FS, tune_offset_hz=TUNE_OFFSET_HZ)
    soft, track, tune_hz = demodulate_fixed(raw, cfg)
    u = quantize(soft, SOFT_BITS, SOFT_SHIFT)
    wins, _ = windows(u, frame_sync_fixed(u, THR64, FLYWHEEL))
    cadus = cadus_from_windows(decode_windows(wins), wins)
    good = [min(c.corrections) >= 0 for c in cadus]
    stacked = np.array([c.data for c in cadus], dtype=np.uint8).reshape(-1, FRAME)
    frames = {vcdu_key(bytes(c.data)): bytes(d) for c, d, g in zip(cadus, data_bytes(stacked), good, strict=True) if g}
    return {
        "start_s": start_s,
        "frames": frames,
        "decoded": len(cadus),
        "rs_failed": good.count(False),
        # Carrier = NCO correction from the host's coarse estimate + the Costas loop's frequency register.
        "freq_hz": tune_hz - TUNE_OFFSET_HZ + float(np.median(freq_hz(track, cfg))),
        "hypotheses": collections.Counter((c.alternate, c.swap) for c, g in zip(cadus, good, strict=True) if g),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording", type=Path)
    ap.add_argument("satdump_cadu", type=Path)
    ap.add_argument("--start-utc", required=True, help="UTC of the first sample, ISO")
    ap.add_argument("--from-s", type=float, default=0.0)
    ap.add_argument("--to-s", type=float, default=None)
    ap.add_argument("--chunk-s", type=float, default=30.0)
    ap.add_argument("--overlap-s", type=float, default=2.0, help="> cold-start acquisition (~0.2 s) plus a frame")
    ap.add_argument("--jobs", type=int, default=6, help="each job holds ~0.6 GB per 30 s chunk")
    ap.add_argument("--bit-true", action="store_true", help="the bit-true chain (= RTL); ~16x slower than real time")
    a = ap.parse_args()

    total_s = a.recording.stat().st_size / 2 / FS
    end_s = min(a.to_s if a.to_s is not None else total_s, total_s)
    step = a.chunk_s - a.overlap_s
    starts = np.arange(a.from_s, end_s - a.overlap_s, step)
    jobs = [(str(a.recording), float(s), float(min(a.chunk_s, end_s - s))) for s in starts]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        chunks = list(pool.map(decode_chunk_fixed if a.bit_true else decode_chunk, jobs))

    raw = a.satdump_cadu.read_bytes()
    if len(raw) % FRAME:
        raise SystemExit(f"{a.satdump_cadu}: not a whole number of {FRAME}-byte frames")
    satdump = {vcdu_key(raw[i : i + FRAME]): raw[i : i + FRAME][DATA] for i in range(0, len(raw), FRAME)}

    t0 = datetime.fromisoformat(a.start_utc)
    model: dict[Key, bytes] = {}
    rows: list[list[object]] = []
    for c in chunks:
        frames: dict[Key, bytes] = c["frames"]  # type: ignore[assignment]
        model.update(frames)
        hyp: collections.Counter[tuple[bool, bool]] = c["hypotheses"]  # type: ignore[assignment]
        utc = (t0 + timedelta(seconds=float(c["start_s"]))).strftime("%H:%M:%S")  # type: ignore[arg-type]
        rows.append(
            [
                utc,
                c["start_s"],
                c["decoded"],
                len(frames),
                c["rs_failed"],
                sum(satdump.get(k) == d for k, d in frames.items()),
                sum(k in satdump and satdump[k] != d for k, d in frames.items()),
                sum(k not in satdump for k in frames),
                f"{c['freq_hz']:.0f}",
                ";".join(f"alt={int(h[0])} swap={int(h[1])}:{n}" for h, n in sorted(hyp.items())),
            ]
        )
    common = model.keys() & satdump.keys()
    matched = sum(model[k] == satdump[k] for k in common)
    rows.append(
        [
            "total",
            "",
            "",  # chunks overlap, so per-chunk counts don't add up; the merged count is frames_rs_good
            len(model),
            "",
            matched,
            len(common) - matched,
            len(model.keys() - satdump.keys()),
            "",
            f"satdump_frames={len(satdump)} satdump_only={len(satdump.keys() - model.keys())} "
            f"swap1_rs_good={sum(n for c in chunks for h, n in c['hypotheses'].items() if h[1])}",  # type: ignore[attr-defined]
        ]
    )
    header = [
        "chunk_utc",
        "chunk_start_s",
        "frames_decoded",
        "frames_rs_good",
        "frames_rs_failed",
        "equal_to_satdump",
        "differ_from_satdump",
        "model_only",
        "median_carrier_hz",
        "hypotheses_rs_good",
    ]
    write_result(
        "real_pass_fixed" if a.bit_true else "real_pass_model", header, rows, seed="", recording=a.recording.name
    )
    print(rows[-1])


if __name__ == "__main__":
    main()
