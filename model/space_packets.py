"""CADUs -> CCSDS space packets (docs/signal-spec.md "Frame layers above the CADU"; ADR 0015).

Three pieces:

- `mux`: the inverse, packing space packets into the M_PDU packet zones of VCID-5 CADUs, for test streams.
- `satdump_demux`: SatDump 1.2.2's demultiplexer (`src-core/common/ccsds/ccsds_aos/demuxer.cpp`), ported statement
  for statement, quirks included. The reference that "matches SatDump" is measured against.
- `demux`: the receiver's rule (ADR 0015), the golden model for gs-rx: the same packets as SatDump on an unbroken
  stream; a packet that crosses a VCDU counter gap, disagrees with the first header pointer, or meets an invalid
  pointer is dropped and counted, never emitted damaged.

All three take whole 1,024-byte CADUs (ASM included, derandomized, RS-corrected) and look only at VCID 5. Dropping
CADUs with an uncorrectable codeword (SatDump's `rs_usecheck`) is the caller's job.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

CADU_BYTES = 1024
VCID_MSUMR = 5  # signal-spec.md: SatDump demultiplexes VCID 5 only
ZONE_START = 14  # M_PDU packet zone: CADU bytes 14..895 (signal-spec.md byte map)
ZONE_BYTES = 882  # MPDU_DATA_SIZE
NO_HEADER = 2047  # first header pointer: no packet starts in this M_PDU
HDR = 6  # space packet primary header
COUNTER_MOD = 1 << 24  # VCDU counter, 24 bits


def vcid(cadu: bytes) -> int:
    return cadu[5] & 0x3F


def vcdu_counter(cadu: bytes) -> int:
    return int.from_bytes(cadu[6:9], "big")


def first_header_pointer(cadu: bytes) -> int:
    return ((cadu[12] & 0x07) << 8) | cadu[13]


def zone(cadu: bytes) -> bytes:
    return cadu[ZONE_START: ZONE_START + ZONE_BYTES]


def packet_length(header: bytes) -> int:
    """Total bytes of a space packet from its 6-byte primary header: header + packet length field + 1."""
    return HDR + int.from_bytes(header[4:6], "big") + 1


def space_packet(apid: int, seq: int, data: bytes) -> bytes:
    """A version-0 telemetry packet, unsegmented (sequence flags 3), no secondary header."""
    if not data or len(data) > 1 << 16:
        raise ValueError(f"data length {len(data)} outside 1..65536")
    return bytes([(apid >> 8) & 0x07, apid & 0xFF, 0xC0 | ((seq >> 8) & 0x3F), seq & 0xFF]) + (
        len(data) - 1).to_bytes(2, "big") + data


APID_IDLE = 2047


def idle_fill(used: int) -> list[bytes]:
    """Idle packets that bring a stream of `used` bytes to a whole number of zones (none if it already is). A tail
    shorter than a minimal packet (7 bytes) takes one more zone."""
    rest = -used % ZONE_BYTES
    if rest == 0:
        return []
    if rest < HDR + 1:
        rest += ZONE_BYTES
    return [space_packet(APID_IDLE, 0, bytes(rest - HDR))]


def mux(packets: Iterable[bytes], *, scid: int = 0, first_counter: int = 0, vc: int = VCID_MSUMR) -> list[bytes]:
    """Pack packets back to back into M_PDU zones, then idle packets to fill the last zone (`idle_fill`), as a
    satellite does. The first header pointer is the first packet start in each zone, or NO_HEADER."""
    stream = bytearray()
    starts: list[int] = []
    pkts = list(packets)
    used = sum(len(p) for p in pkts)
    for p in [*pkts, *idle_fill(used)]:
        starts.append(len(stream))
        stream += p
    n_cadus = -(-len(stream) // ZONE_BYTES)
    out = []
    k = 0
    for i in range(n_cadus):
        lo, hi = i * ZONE_BYTES, (i + 1) * ZONE_BYTES
        while k < len(starts) and starts[k] < lo:
            k += 1
        fhp = starts[k] - lo if k < len(starts) and starts[k] < hi else NO_HEADER
        counter = (first_counter + i) % COUNTER_MOD
        hdr = bytes([0x40 | (scid >> 2) & 0x3F, ((scid & 0x03) << 6) | vc]) + counter.to_bytes(3, "big") + b"\0"
        body = bytes(stream[lo:hi])
        cadu = bytes.fromhex("1ACFFC1D") + hdr + b"\0\0" + bytes([fhp >> 8, fhp & 0xFF]) + body
        out.append(cadu.ljust(CADU_BYTES, b"\0"))
    return out


def satdump_demux(cadus: Iterable[bytes]) -> list[bytes]:
    """SatDump 1.2.2 `ccsds_aos::Demuxer(882, true)::work` over the VCID-5 CADUs, every packet as header + payload.
    Line numbers are demuxer.cpp's."""
    out: list[bytes] = []
    cur_hdr = b""
    payload = bytearray()
    cur_len = remaining = total = 0  # currentPacketPayloadLength, remainingPacketLength, totalPacketLength
    working = in_header = False
    header_buf = bytearray(HDR)
    in_header_buf = 0

    def read_packet(h: bytes) -> None:  # :27-34
        nonlocal working, cur_hdr, cur_len, total, remaining
        working = True
        cur_hdr = bytes(h[:HDR])
        cur_len = int.from_bytes(h[4:6], "big") + 1
        total = cur_len + HDR
        remaining = cur_len

    def push_packet() -> None:  # :37-45
        nonlocal cur_len, remaining, working
        out.append(cur_hdr + bytes(payload))
        payload.clear()
        cur_len = remaining = 0
        working = False

    def push_payload(data: bytes | bytearray, at: int, length: int) -> None:  # :48-54
        nonlocal remaining
        payload.extend(data[at: at + length])  # length <= 0 appends nothing (the C++ loop does not run)
        remaining -= length

    def abort_packet() -> None:  # :57-64
        nonlocal working, cur_len, remaining
        working = False
        payload.clear()
        cur_len = remaining = 0

    for cadu in cadus:
        if vcid(cadu) != VCID_MSUMR:
            continue
        fhp = first_header_pointer(cadu)
        data = zone(cadu)
        if NO_HEADER > fhp >= ZONE_BYTES:  # :73
            continue
        offset = 0
        if in_header:  # :83-94
            in_header = False
            take = HDR - in_header_buf
            header_buf[in_header_buf:HDR] = data[:take]
            offset = take
            in_header_buf += take
            read_packet(bytes(header_buf))
        if remaining > 0 and working:  # :97-113
            if fhp < NO_HEADER:
                to_write = (fhp + 1) - offset if (remaining + offset) > fhp + 1 else remaining
                push_payload(data, offset, to_write)
                remaining = 0
            else:
                to_write = ZONE_BYTES - offset if (remaining + offset) > ZONE_BYTES - offset else remaining
                push_payload(data, offset, to_write)
        if remaining == 0 and working:  # :116-119
            push_packet()
        if fhp < NO_HEADER:  # :122-199
            if fhp + HDR < ZONE_BYTES:
                read_packet(data[fhp: fhp + HDR])
                if ZONE_BYTES > fhp + total:
                    if fhp + total < ZONE_BYTES:
                        push_payload(data, fhp + HDR, cur_len)
                        push_packet()
                    else:
                        abort_packet()
                    nxt = fhp + total
                    while nxt < ZONE_BYTES:
                        if nxt + HDR < ZONE_BYTES:
                            read_packet(data[nxt: nxt + HDR])
                            to_write = min(remaining, ZONE_BYTES - (nxt + HDR))
                            push_payload(data, nxt + HDR, to_write)
                        elif nxt < ZONE_BYTES:
                            in_header = True
                            in_header_buf = 0
                            header_buf[0: ZONE_BYTES - nxt] = data[nxt:ZONE_BYTES]
                            in_header_buf += ZONE_BYTES - nxt
                            break
                        if remaining == 0 and working:
                            push_packet()
                        nxt = nxt + total
                elif working:
                    to_write = min(remaining, ZONE_BYTES - (fhp + HDR))
                    push_payload(data, fhp + HDR, to_write)
            elif fhp < ZONE_BYTES:
                in_header = True
                in_header_buf = 0
                header_buf[0: ZONE_BYTES - fhp] = data[fhp:ZONE_BYTES]
                in_header_buf += ZONE_BYTES - fhp
    return out


@dataclass
class DemuxCounts:
    """ADR 0015. Every VCID-5 CADU and every packet byte ends up in exactly one of these outcomes."""

    cadus: int = 0          # VCID-5 CADUs taken
    other_vcid: int = 0     # CADUs on other virtual channels, ignored
    gaps: int = 0           # VCDU counter discontinuities between consecutive VCID-5 CADUs
    packets: int = 0        # packets emitted
    dropped_gap: int = 0    # packets in progress lost to a counter gap
    dropped_length: int = 0  # packets whose length disagreed with the first header pointer
    bad_pointer: int = 0    # M_PDUs with a first header pointer from 882 to 2046 (zone skipped)
    dropped_pointer: int = 0  # packets in progress lost to such an M_PDU


@dataclass
class Demux:
    """The receiver's demultiplexer (ADR 0015), fed one CADU at a time like gs-rx."""

    counts: DemuxCounts = field(default_factory=DemuxCounts)
    _pkt: bytearray = field(default_factory=bytearray)  # bytes of the packet in progress, header included
    _synced: bool = False  # the zone's next byte belongs to _pkt (or starts a packet, if _pkt is empty)
    _last: int | None = None  # previous VCID-5 VCDU counter

    def _drop(self) -> bool:
        """Lose the packet in progress (if any) and wait for the next first header pointer."""
        had = bool(self._pkt)
        self._pkt.clear()
        self._synced = False
        return had

    def _need(self) -> int | None:
        """Total length of the packet in progress, once its header is complete."""
        return packet_length(bytes(self._pkt[:HDR])) if len(self._pkt) >= HDR else None

    def _take(self, data: bytes, pos: int, end: int, out: list[bytes]) -> int:
        """Append from data[pos:end] up to the packet's end; emit it if complete. Returns the new position."""
        while True:
            need = self._need()
            want = (need if need is not None else HDR) - len(self._pkt)
            take = min(want, end - pos)
            self._pkt += data[pos: pos + take]
            pos += take
            if need is None and len(self._pkt) >= HDR:
                continue  # header just completed: now the length is known
            if need is not None and len(self._pkt) == need:
                out.append(bytes(self._pkt))
                self.counts.packets += 1
                self._pkt.clear()
            return pos

    def work(self, cadu: bytes) -> list[bytes]:
        out: list[bytes] = []
        if vcid(cadu) != VCID_MSUMR:
            self.counts.other_vcid += 1
            return out
        c = self.counts
        c.cadus += 1
        ctr = vcdu_counter(cadu)
        if self._last is not None and ctr != (self._last + 1) % COUNTER_MOD:
            c.gaps += 1
            c.dropped_gap += self._drop()
        self._last = ctr
        fhp = first_header_pointer(cadu)
        if NO_HEADER > fhp >= ZONE_BYTES:
            c.bad_pointer += 1
            c.dropped_pointer += self._drop()
            return out
        data = zone(cadu)
        end = ZONE_BYTES if fhp == NO_HEADER else fhp
        if self._synced and self._pkt:
            # Continuation: the packet must end exactly where the next header starts (or, with no header in this
            # zone, it must not end inside it: it may only end exactly at the zone's end).
            pos = self._take(data, 0, end, out)
            if self._pkt and fhp != NO_HEADER:  # not finished by the next header
                c.dropped_length += self._drop()
            elif not self._pkt and pos != end:
                # Ended before the next header (or inside a zone with none): length and pointer disagree, so the
                # packet just completed is not trusted either.
                c.dropped_length += 1
                out.pop()
                c.packets -= 1
                self._synced = False
        if fhp == NO_HEADER:
            return out
        pos = fhp
        self._pkt.clear()
        self._synced = True
        while pos < ZONE_BYTES:
            pos = self._take(data, pos, ZONE_BYTES, out)
        return out


def demux(cadus: Iterable[bytes]) -> tuple[list[bytes], DemuxCounts]:
    d = Demux()
    out: list[bytes] = []
    for cadu in cadus:
        out += d.work(cadu)
    return out, d.counts


def flatten(groups: Sequence[Sequence[bytes]]) -> list[bytes]:
    return [p for g in groups for p in g]
