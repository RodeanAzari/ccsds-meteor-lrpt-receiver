"""Board -> host stats packets (docs/protocol.md "Board → host packets", "Stats", type 1).

    PYTHONPATH=. python scripts/board_stats.py [seconds]    # print every stats packet received on UDP port 26401

`parse_stats` is the reference parser for the format; `StatsListener` collects packets in the background while
something else (a replay) runs.
"""

from __future__ import annotations

import socket
import struct
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

HDR = struct.Struct(">BBHIQ")  # type, version, n, pkt_seq, uptime
TYPE_STATS = 1
VERSION = 2  # docs/protocol.md: ingest_gap/ingest_lost redefined with the reorder buffer (ADR 0013)
PORT = 26401
# Field order (docs/protocol.md "Stats"); later tops append, never reorder.
FIELDS = (
    "ingest_ok", "ingest_bad", "ingest_gap", "ingest_lost",
    "eth_ok", "eth_crc_err", "eth_rx_err", "eth_runt", "eth_oversize", "eth_ovf_lost",
    "udp_ok", "udp_filtered", "udp_ip_csum_err", "udp_malformed",
    "rx_fifo_hwm", "ddc_out", "tx_underrun", "mac_restarts",
    # arty_rx_eth_top only (n = 29)
    "cadus_sent", "fs_locked", "fs_dropped", "fs_slips", "fs_early", "flag_ovf", "len_err", "ingest_late",
    "nco_word", "ctrl_ok", "ctrl_bad",
)


@dataclass(frozen=True)
class Stats:
    pkt_seq: int
    uptime: int  # core clock cycles since the MAC left reset
    fields: dict[str, int] = field(default_factory=dict)


def parse_stats(data: bytes) -> Stats:
    """Raises ValueError on anything that is not a well-formed version-2 stats packet."""
    if len(data) < HDR.size:
        raise ValueError(f"short packet: {len(data)} bytes")
    ptype, version, n, pkt_seq, uptime = HDR.unpack_from(data)
    if ptype != TYPE_STATS:
        raise ValueError(f"type {ptype}, not stats")
    if version != VERSION:
        raise ValueError(f"version {version}, expected {VERSION}")
    if len(data) != HDR.size + 4 * n:
        raise ValueError(f"{len(data)} bytes for n = {n} (expected {HDR.size + 4 * n})")
    values = struct.unpack_from(f">{n}I", data, HDR.size)
    return Stats(pkt_seq, uptime, dict(zip(FIELDS, values, strict=False)))  # unknown trailing fields ignored


class StatsListener:
    """Receives stats packets on PORT in a background thread; `latest` is the newest one parsed. Packets of other
    types (CADUs, docs/protocol.md type 2, on the same port) go to `other` if given, else count as errors."""

    def __init__(self, port: int = PORT, other: Callable[[bytes], None] | None = None) -> None:
        self.other = other
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", port))
        self.sock.settimeout(0.2)
        self.latest: Stats | None = None
        self.count = 0
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data = self.sock.recv(2048)
            except TimeoutError:
                continue
            if self.other is not None and data[:1] != bytes([TYPE_STATS]):
                self.other(data)
                continue
            try:
                self.latest = parse_stats(data)
                self.count += 1
            except ValueError as e:
                self.errors.append(str(e))

    def wait_newer(self, than_seq: int, timeout_s: float) -> Stats | None:
        """The first packet with pkt_seq > than_seq, or None after timeout_s."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            s = self.latest
            if s is not None and s.pkt_seq > than_seq:
                return s
            time.sleep(0.02)
        return None

    def close(self) -> None:
        self._stop.set()
        self._thread.join()
        self.sock.close()


def main(argv: list[str]) -> int:
    seconds = float(argv[0]) if argv else 5.0
    lst = StatsListener()
    last = -1
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            s = lst.wait_newer(last, end - time.monotonic())
            if s is None:
                break
            last = s.pkt_seq
            print(f"#{s.pkt_seq} t={s.uptime / 1e8:.3f} s " + " ".join(f"{k}={v}" for k, v in s.fields.items()),
                  flush=True)
    finally:
        lst.close()
    for e in lst.errors:
        print(f"bad packet: {e}", file=sys.stderr)
    print(f"{lst.count} packets, {len(lst.errors)} malformed", file=sys.stderr)
    return 0 if lst.count else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
