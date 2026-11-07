"""Phase B board bring-up: the ROM snippet for rtl/top/arty_ddc_rom_top.sv, and the host-side check of its output.

    PYTHONPATH=. python scripts/ddc_board.py rom <out.mem> [n_samples]     # BRAM init file ({Q_u8, I_u8} hex words)
    PYTHONPATH=. python scripts/ddc_board.py check [/dev/ttyUSB1] [n_samples]
    PYTHONPATH=. python scripts/ddc_board.py ila-check <ila.csv> [n_samples]  # ILA capture (make ila-capture)
    PYTHONPATH=. python scripts/ddc_board.py eth-check [/dev/ttyUSB1] --iface <host IP on the cable> \
        [--speed X[,Y...]] [--bit <bitstream>]

`eth-check` is `check` for rtl/top/arty_ddc_eth_top.sv: the snippet goes to the board over Ethernet instead of
from BRAM. Per replay it reprograms the FPGA with --bit (a clean start: opening the port does not reset it), waits
for the link, opens the serial port, streams the snippet with gs-replay (docs/protocol.md), then compares the dump
the board sends once its capture fills. Result: data/results/ddc_board_eth.csv, one row per replay speed.

`check` waits for the board's UART dump ("DDC1" | u32 n | n x u32 {Q, I} s16 | u32 CRC-32, little-endian; saved
to build/board/ddc_dump.bin), skips any dump whose CRC fails (opening the port resets the board, so a cut-off
dump can precede the real one), compares every
output with the bit-true model on the same snippet, and writes data/results/ddc_board.csv plus the before/after
spectrum data/results/ddc_board_spectrum.csv. Press BTN0 (or RESET) on the board to start a dump.

`ila-check` does the same comparison on an ILA capture of the DDC output handshake (`make board ILA=1`,
syn/ila_capture.tcl), written by Vivado as CSV, and writes data/results/ddc_board_ila.csv plus the first
ILA_PLOT_SAMPLES outputs, board and model, for the plot (data/results/ddc_board_ila_iq.csv).
"""

from __future__ import annotations

import re
import struct
import subprocess
import sys
import time
import zlib
from collections.abc import Callable
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
DUMP = Path("build/board/ddc_dump.bin")
DUMP_ETH = Path("build/board/ddc_eth_dump.bin")  # one file per replay: ddc_eth_dump.<row>.bin
GS_REPLAY = Path("build/gs-Release/gs-replay")  # make gs
IFACE_DOWN_WAIT_S = 3.0  # after programming, how long to watch for the link (and host address) to drop
MAC_START_WAIT_S = 1.0  # arty_ddc_eth_top releases the MAC 200 ms after reset
DUMP_WAIT_S = 20.0  # a 16,384-word dump takes 5.7 s at 115,200 baud; none by then means the capture never filled
ILA_PLOT_SAMPLES = 512  # 2 ms at 256 kS/s


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


def dump_size(n: int) -> int:
    return 8 + 4 * n + 4


def parse_dump(data: bytes) -> npt.NDArray[np.int16]:
    """Board dump -> (n, 2) array of (I, Q). Raises on a bad header, a short read or a CRC mismatch."""
    if data[:4] != b"DDC1":
        raise ValueError(f"bad magic {data[:4]!r}")
    (n,) = struct.unpack_from("<I", data, 4)
    if len(data) < dump_size(n):
        raise ValueError(f"short dump: {len(data)} bytes for {n} words")
    (crc,) = struct.unpack_from("<I", data, 8 + 4 * n)
    if zlib.crc32(data[: 8 + 4 * n]) != crc:
        raise ValueError(f"CRC mismatch: dump says {crc:08x}, bytes give {zlib.crc32(data[: 8 + 4 * n]):08x}")
    return np.frombuffer(data, dtype="<i2", count=2 * n, offset=8).reshape(n, 2)


def find_dump(buf: bytes, n: int, start: int = 0) -> tuple[bytes | None, int]:
    """First valid n-word dump in buf at or after `start`. Returns (dump or None, where to resume scanning).

    A header whose dump fails its CRC (e.g. cut off by a reset, with the next dump's bytes after it) is skipped.
    """
    need = dump_size(n)
    while (k := buf.find(b"DDC1", start)) >= 0 and len(buf) - k >= need:
        try:
            parse_dump(buf[k : k + need])
            return buf[k : k + need], k
        except ValueError as e:
            print(f"skipping dump at byte {k}: {e}", flush=True)
            start = k + 1
    return None, start


def read_dump(port: str, n: int, timeout_s: float, after_open: Callable[[], None] | None = None) -> bytes:
    import serial  # pyserial; only the hardware path needs it

    with serial.Serial(port, BAUD, timeout=1.0) as s:
        s.reset_input_buffer()
        print(f"waiting for a dump on {port} (opening the port resets the board and starts one; BTN0 repeats it)...",
              flush=True)
        if after_open is not None:
            after_open()
        buf = b""
        start = 0  # first byte not yet ruled out as the start of a dump
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            buf += s.read(4096)
            dump, start = find_dump(buf, n, start)
            if dump is not None:
                return dump
    raise TimeoutError(f"no valid dump within {timeout_s} s ({len(buf)} bytes seen)")


def spectrum(x: npt.NDArray[np.complex128], fs: float) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    # detrend=False: the default removes each segment's mean, which would hide the DC offset the DDC must remove
    f, p = signal.welch(x, fs=fs, nperseg=1024, return_onesided=False, scaling="density", detrend=False)
    order = np.argsort(f)
    return f[order], 10 * np.log10(p[order] + 1e-30)


def compare(dump: bytes, n: int, path: Path) -> tuple[npt.NDArray[np.int16], int, int]:
    """Save the raw dump (for re-analysis without the board), compare it with the model.
    Returns (outputs, mismatches, first mismatch or -1)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dump)
    got = parse_dump(dump)
    exp_i, exp_q = expected(n)
    exp = np.stack([exp_i, exp_q], axis=1)
    if got.shape != exp.shape:
        raise ValueError(f"dump holds {got.shape[0]} outputs, model has {exp.shape[0]}")
    bad = np.flatnonzero(np.any(got != exp, axis=1))
    first = int(bad[0]) if bad.size else -1
    print(f"{got.shape[0]} outputs, {bad.size} mismatches" + (f", first at {first}" if bad.size else ""))
    return got, int(bad.size), first


def check(port: str, n: int) -> int:
    from analysis.common import write_result

    got, n_bad, first = compare(read_dump(port, n // 4, timeout_s=60.0), n, DUMP)
    write_result(
        "ddc_board",
        ["outputs", "mismatches", "first_mismatch", "n_input_samples", "freq_word_hex", "clk_mhz", "baud"],
        [[got.shape[0], n_bad, first, n, f"{m.freq_word(CFG.tune_offset_hz, CFG.fs):08x}", 100, BAUD]],
        f"snippet seed {SEED}, {EBN0_DB} dB, carrier {CARRIER_HZ / 1e3:.0f} kHz "
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
        f"Welch, 1024-point segments, no detrending; seed {SEED}",
        command=f"PYTHONPATH=. python scripts/ddc_board.py check {port}",
    )
    return 1 if n_bad else 0


def wait_for_iface(ip: str, timeout_s: float = 30.0) -> None:
    """Wait until the link is down (the address goes) and back up (it returns), or until it is present after
    IFACE_DOWN_WAIT_S if it never went away. Raises if it is not back within timeout_s."""
    def present() -> bool:
        out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, check=True).stdout
        return f"inet {ip}/" in out

    t0 = time.monotonic()
    while present() and time.monotonic() - t0 < IFACE_DOWN_WAIT_S:
        time.sleep(0.2)
    while not present():
        if time.monotonic() - t0 > timeout_s:
            raise TimeoutError(f"interface {ip} not back {timeout_s} s after programming")
        time.sleep(0.2)
    print(f"link up {time.monotonic() - t0:.1f} s after programming", flush=True)


def eth_check(port: str, iface: str, speeds: list[str], bit: str | None, n: int = N_SAMPLES) -> int:
    """One replay per speed, each from a fresh board; one result row per replay. With `bit`, the FPGA is
    reprogrammed before each replay, because opening the port does not reset the design (2026-11-07: replays
    without it got no dump, the capture still full from the one before, even 5 s after the open). Reprogramming
    drops the Ethernet link, so the replay waits until the host interface has its address again."""
    from analysis.common import write_result

    cu8 = Path("build/board/ddc_snippet.cu8")
    cu8.parent.mkdir(parents=True, exist_ok=True)
    cu8.write_bytes(snippet(n).tobytes())
    rows: list[list[object]] = []
    failed = 0
    for speed in speeds:
        if bit is not None:
            subprocess.run(["openFPGALoader", "-b", "arty_a7_100t", bit], capture_output=True, check=True)
            wait_for_iface(iface)
        cmd = [str(GS_REPLAY), str(cu8), "--iface", iface, "--speed", speed]
        said: list[str] = []

        def send(cmd: list[str] = cmd, said: list[str] = said) -> None:
            time.sleep(MAC_START_WAIT_S)  # the port open reset the board; the MAC leaves reset after 200 ms
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)
            said.append((r.stdout + r.stderr).strip())
            print(f"gs-replay exit {r.returncode}: {said[-1]}", flush=True)
            if r.returncode != 0:
                raise RuntimeError("gs-replay failed")

        try:
            dump = read_dump(port, n // 4, timeout_s=DUMP_WAIT_S, after_open=send)
        except TimeoutError as e:  # the capture never filled: samples were lost before the DDC
            print(f"speed {speed}: {e}", flush=True)
            dump = None
        got_n, n_bad, first = 0, -1, -1
        if dump is not None:
            got, n_bad, first = compare(dump, n, DUMP_ETH.with_suffix(f".{len(rows)}.bin"))
            got_n = got.shape[0]
        rate = re.search(r"rate=(\d+) S/s \(([\d.]+)x", said[0]) if said else None
        rows.append([speed, rate.group(2) if rate else "", "yes" if dump is not None else "no", got_n, n_bad, first,
                     n, n // 512, f"{m.freq_word(CFG.tune_offset_hz, CFG.fs):08x}", 100, BAUD])
        failed |= n_bad != 0
    write_result(
        "ddc_board_eth",
        ["replay_speed", "achieved_speed", "dump", "outputs", "mismatches", "first_mismatch", "n_input_samples",
         "datagrams",
         "freq_word_hex", "clk_mhz", "baud"],
        rows,
        f"snippet seed {SEED}, {EBN0_DB} dB, carrier {CARRIER_HZ / 1e3:.0f} kHz (scripts/ddc_board.py), streamed "
        f"by gs-replay (achieved_speed: its own report) over 100 Mb/s Ethernet to arty_ddc_eth_top on the Arty "
        f"A7-100T (fpga-eth-core eth-core-v0.2), one replay per row, each after a reset",
        command=f"PYTHONPATH=. python scripts/ddc_board.py eth-check {port} --iface {iface} --speed {','.join(speeds)}"
        + (f" --bit {bit}" if bit else ""),
    )
    return 1 if failed else 0


def parse_ila_csv(text: str) -> npt.NDArray[np.int64]:
    """Vivado ILA CSV -> (n, 2) array of (I, Q), in buffer order. Raises unless the window starts at the trigger
    and every stored sample is a handshake (tvalid 1, full 0), i.e. the capture conditions really applied."""
    lines = text.strip().splitlines()
    header = lines[0].split(",")
    if not lines[1].startswith("Radix"):
        raise ValueError("not a Vivado ILA CSV")
    col = {name.split("[")[0]: k for k, name in enumerate(header)}
    rows = [line.split(",") for line in lines[2:]]
    if int(rows[0][col["TRIGGER"]]) != 1 or int(rows[0][col["Sample in Window"]]) != 0:
        raise ValueError("ILA window does not start at the trigger")
    # probe order from impl_board.tcl: 0 bb_tdata, 1 bb_tvalid, 2 full (LD6), 3 rom_done (LD5)
    valid = [int(r[4], 16) for r in rows]
    full = [int(r[5], 16) for r in rows]
    if any(v != 1 for v in valid) or any(f != 0 for f in full):
        raise ValueError("ILA stored a sample that was not an output handshake")
    words = np.array([int(r[3], 16) for r in rows], dtype=np.int64)
    return np.stack([_s16(words), _s16(words >> 16)], axis=1)  # tdata = {Q, I}


def _s16(w: npt.NDArray[np.int64]) -> npt.NDArray[np.int64]:
    return ((w & 0xFFFF) ^ 0x8000) - 0x8000


def ila_check(csv_path: Path, n: int) -> int:
    from analysis.common import write_result

    got = parse_ila_csv(csv_path.read_text())
    exp_i, exp_q = expected(n)
    exp = np.stack([exp_i, exp_q], axis=1)
    if got.shape != exp.shape:
        print(f"ILA holds {got.shape[0]} outputs, model has {exp.shape[0]}")
        return 1
    bad = np.flatnonzero(np.any(got != exp, axis=1))
    first = int(bad[0]) if bad.size else -1
    print(f"ILA: {got.shape[0]} outputs, {bad.size} mismatches" + (f", first at {first}" if bad.size else ""))
    cmd = f"PYTHONPATH=. python scripts/ddc_board.py ila-check {csv_path}"
    src = (f"snippet seed {SEED}, {EBN0_DB} dB, carrier {CARRIER_HZ / 1e3:.0f} kHz (scripts/ddc_board.py), "
           "played from BRAM on the Arty A7-100T, DDC output captured by the ILA")
    write_result(
        "ddc_board_ila",
        ["outputs", "mismatches", "first_mismatch", "n_input_samples", "ila_depth", "clk_mhz"],
        [[got.shape[0], bad.size, first, n, got.shape[0], 100]],
        src,
        command=cmd,
    )
    k = np.arange(ILA_PLOT_SAMPLES)
    write_result(
        "ddc_board_ila_iq",
        ["sample", "t_us", "board_i", "board_q", "model_i", "model_q"],
        [[int(j), f"{j / (CFG.fs / 4) * 1e6:.3f}", *got[j].tolist(), *exp[j].tolist()] for j in k],
        src,
        command=cmd,
    )
    return 1 if bad.size else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["rom"]:
        write_rom(Path(argv[1]), int(argv[2]) if len(argv) > 2 else N_SAMPLES)
        return 0
    if argv[:1] == ["check"]:
        return check(argv[1] if len(argv) > 1 else "/dev/ttyUSB1", int(argv[2]) if len(argv) > 2 else N_SAMPLES)
    if argv[:1] == ["eth-check"]:
        rest = argv[1:]
        port = rest.pop(0) if rest and not rest[0].startswith("--") else "/dev/ttyUSB1"
        opts = dict(zip(rest[::2], rest[1::2], strict=False))
        if "--iface" not in opts:
            print("eth-check needs --iface <host IP on the cable to the Arty>", file=sys.stderr)
            return 2
        return eth_check(port, opts["--iface"], opts.get("--speed", "1").split(","), opts.get("--bit"))
    if argv[:1] == ["ila-check"]:
        return ila_check(Path(argv[1]), int(argv[2]) if len(argv) > 2 else N_SAMPLES)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
