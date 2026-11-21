"""The float model on a real signal: 2.4 s of the 2026-11-21 Meteor-M N2-4 pass (data/samples/, its .md sidecar).

Synthetic tests check the model against our own idea of the signal. This one checks it against the satellite and
against SatDump, the reference decoder (signal-spec.md): a wrong spec parameter (rail order, conv output order, NRZ-M,
PN, RS interleave or basis) that our modulator shares with our demodulator fails here and nowhere else.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from model.receiver import RxConfig, data_bytes, decode_iq, ingest_cu8

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
SNIPPET = SAMPLES / "2026-11-21T195100Z_meteor-m2-4_2.4s.cu8"
SATDUMP = SAMPLES / "2026-11-21T195100Z_satdump.cadu"
CFG = RxConfig(fs=1_024_000.0, tune_offset_hz=150_000.0)  # data/MANIFEST.md: tuned 137.75 MHz, signal 137.9 MHz


def _key(frame: bytes) -> tuple[int, int]:
    """(VCID, virtual channel frame counter) from the VCDU primary header after the ASM."""
    return frame[5] & 0x3F, int.from_bytes(frame[6:9], "big")


def test_real_pass_snippet_decodes_to_satdumps_frames() -> None:
    result = decode_iq(ingest_cu8(np.fromfile(SNIPPET, dtype=np.uint8)), CFG)
    raw = SATDUMP.read_bytes()
    # signal-spec.md, "What gs-diff can compare": SatDump leaves parity uncorrected, so compare the 892 data bytes.
    satdump = {_key(raw[i : i + 1024]): raw[i + 4 : i + 896] for i in range(0, len(raw), 1024)}

    assert (result.rs_corrections >= 0).all(), "an RS codeword failed at 14 dB soft SNR"
    ours = {_key(bytes(c)): bytes(d) for c, d in zip(result.cadus, data_bytes(result.cadus), strict=True)}
    # 2.4 s holds 21 frames; the first goes to acquisition. SatDump has the 20 the model decoded on 2026-11-21.
    assert ours == satdump
    # signal-spec.md, "Which rail leads": every frame decodes with G1 on the symbol half a symbol before its G2
    # partner (no swap). The rotation (alternate) is the carrier's 90-degree ambiguity and may take either value.
    assert not any(swap for _, swap in result.hypothesis)
