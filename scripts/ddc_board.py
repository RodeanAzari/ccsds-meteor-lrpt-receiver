"""Phase B board bring-up: the ROM snippet for rtl/top/arty_ddc_rom_top.sv, and the host-side check of its output.

    PYTHONPATH=. python scripts/ddc_board.py rom <out.mem> [n_samples]     # BRAM init file ({Q_u8, I_u8} hex words)
    PYTHONPATH=. python scripts/ddc_board.py check [/dev/ttyUSB1] [n_samples]

`check` waits for the board's UART dump ("DDC1" | u32 n | n x u32 {Q, I} s16, little-endian), compares every
output with the bit-true model on the same snippet, and writes data/results/ddc_board.csv plus the before/after
spectrum data/results/ddc_board_spectrum.csv. Press BTN0 (or RESET) on the board to start a dump.
"""

from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

import numpy as np
import numpy.typing as npt
from scipy import signal

from model import ddc_fixed as m
from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma, to_cu8
from model.coding import build_cadus, encode_stream
from model.receiver import RxConfig

N_SAMPLES = 65536  # 64 ms at 1.024 MS/s; must match arty_ddc_rom_top N_SAMPLES
SEED = 2026
EBN0_DB = 8.0
CARRIER_HZ = 151_000.0  # 1 kHz above the 150 kHz NCO, like a Doppler residual
DC_OFFSET = 0.25  # of sigma, per rail: an RTL-SDR-like DC offset for the DC block to remove
CFG = RxConfig(fs=1_024_000.0, tune_offset_hz=150_000.0)
BAUD = 115_200


def snippet(n: int = N_SAMPLES) -> npt.NDArray[np.uint8]:
    """Interleaved cu8 I/Q: OQPSK frames, carrier 151 kHz, 30 Hz/s ramp, 8 dB Eb/N0, DC offset."""
    tx = TxConfig(timing_offset_sym=0.37, clock_ppm=20.0)
    frames = 1 + n // 100_000
    _, on_air = build_cadus(frames, SEED)
    sigma = noise_sigma(EBN0_DB, tx.fs)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, CARRIER_HZ, 30.0, 0.7), sigma, SEED)
    x = x[:n] + DC_OFFSET * sigma * (1 + 1j)
    return to_cu8(x, full_scale=4 * sigma)


def write_rom(path: Path, n: int = N_SAMPLES) -> None:
    raw = snippet(n)
    words = raw[0::2].astype(np.uint32) | (raw[1::2].astype(np.uint32) << 8)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{w:04x}\n" for w in words.tolist()))


def expected(n: int = N_SAMPLES) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    return m.ddc_fixed_rails(snippet(n), CFG)


def parse_dump(data: bytes) -> npt.NDArray[np.int16]:
    """Board dump -> (n, 2) array of (I, Q). Raises on a bad header or a short read."""
    if data[:4] != b"DDC1":
        raise ValueError(f"bad magic {data[:4]!r}")
    (n,) = struct.unpack_from("<I", data, 4)
    if len(data) < 8 + 4 * n:
        raise ValueError(f"short dump: {len(data)} bytes for {n} words")
    return np.frombuffer(data, dtype="<i2", count=2 * n, offset=8).reshape(n, 2)


def read_dump(port: str, n: int, timeout_s: float) -> bytes:
    import serial  # pyserial; only the hardware path needs it

    need = 8 + 4 * n
    with serial.Serial(port, BAUD, timeout=1.0) as s:
        s.reset_input_buffer()
        print(f"waiting for a dump on {port} (press BTN0 on the board)...", flush=True)
        buf = b""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            buf += s.read(4096)
            k = buf.find(b"DDC1")
            if k >= 0 and len(buf) - k >= need:
                return buf[k : k + need]
    raise TimeoutError(f"no complete dump within {timeout_s} s ({len(buf)} bytes seen)")


def spectrum(x: npt.NDArray[np.complex128], fs: float) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    f, p = signal.welch(x, fs=fs, nperseg=1024, return_onesided=False, scaling="density")
    order = np.argsort(f)
    return f[order], 10 * np.log10(p[order] + 1e-30)


def check(port: str, n: int) -> int:
    from analysis.common import write_result

    got = parse_dump(read_dump(port, n // 4, timeout_s=60.0))
    exp_i, exp_q = expected(n)
    exp = np.stack([exp_i, exp_q], axis=1)
    bad = np.flatnonzero(np.any(got != exp, axis=1))
    first = int(bad[0]) if bad.size else -1
    print(f"{got.shape[0]} outputs, {bad.size} mismatches" + (f", first at {first}" if bad.size else ""))
    write_result(
        "ddc_board",
        ["outputs", "mismatches", "first_mismatch", "n_input_samples", "freq_word_hex", "clk_mhz", "baud"],
        [[got.shape[0], bad.size, first, n, f"{m.freq_word(CFG.tune_offset_hz, CFG.fs):08x}", 100, BAUD]],
        f"synthetic snippet, seed {SEED}, {EBN0_DB} dB, carrier {CARRIER_HZ / 1e3:.0f} kHz "
        f"(scripts/ddc_board.py), played from BRAM on the Arty A7-100T",
        command=f"PYTHONPATH=. python scripts/ddc_board.py check {port}",
    )
    raw = snippet(n).astype(np.float64)
    before = (raw[0::2] - 127.5) + 1j * (raw[1::2] - 127.5)
    after = got[:, 0].astype(np.float64) + 1j * got[:, 1].astype(np.float64)
    f_in, p_in = spectrum(before, CFG.fs)
    f_out, p_out = spectrum(after, CFG.fs / 4)
    rows = [["before", f"{f:.1f}", f"{p:.2f}"] for f, p in zip(f_in, p_in, strict=True)]
    rows += [["after", f"{f:.1f}", f"{p:.2f}"] for f, p in zip(f_out, p_out, strict=True)]
    write_result(
        "ddc_board_spectrum",
        ["stage", "freq_hz", "psd_db_per_hz"],
        rows,
        f"before: the ROM snippet (cu8 - 127.5, 1.024 MS/s); after: the board's DDC output (s16, 256 kS/s); "
        f"Welch, 1024-point segments; seed {SEED}",
        command=f"PYTHONPATH=. python scripts/ddc_board.py check {port}",
    )
    return 1 if bad.size else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["rom"]:
        write_rom(Path(argv[1]), int(argv[2]) if len(argv) > 2 else N_SAMPLES)
        return 0
    if argv[:1] == ["check"]:
        return check(argv[1] if len(argv) > 1 else "/dev/ttyUSB1", int(argv[2]) if len(argv) > 2 else N_SAMPLES)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
