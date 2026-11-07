"""Ethernet II / IPv4 / UDP frames as MII nibbles, built from the RFCs, for driving a top level's PHY pins.

Independent of fpga-eth-core's own test helpers on purpose: a misreading of the wire format on either side shows
up as a mismatch instead of cancelling out.
"""

from __future__ import annotations

import struct
import zlib
from typing import Any

from cocotb.triggers import FallingEdge

PREAMBLE_SFD = bytes([0x55] * 7 + [0xD5])


def ip_checksum(header: bytes) -> int:
    s = sum(struct.unpack(f">{len(header) // 2}H", header))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def multicast_mac(group_ip: int) -> bytes:
    """RFC 1112: 01:00:5e + the low 23 bits of the group address."""
    return bytes([0x01, 0x00, 0x5E, (group_ip >> 16) & 0x7F, (group_ip >> 8) & 0xFF, group_ip & 0xFF])


def udp_frame(payload: bytes, dst_ip: int, dst_port: int, src_port: int = 40000, src_ip: int = 0xC0A8_0164,
              src_mac: bytes = bytes.fromhex("02aabbccddee"), bad_fcs: bool = False) -> bytes:
    """Ethernet frame for one UDP datagram to a multicast group, FCS appended (UDP checksum 0 = not used)."""
    udp = struct.pack(">HHHH", src_port, dst_port, 8 + len(payload), 0) + payload
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 0, 0x4000, 64, 17, 0,
                     src_ip.to_bytes(4, "big"), dst_ip.to_bytes(4, "big"))
    ip = ip[:10] + struct.pack(">H", ip_checksum(ip)) + ip[12:]
    frame = multicast_mac(dst_ip) + src_mac + b"\x08\x00" + ip + udp
    frame += bytes(max(0, 60 - len(frame)))  # pad to the 64-byte minimum with the FCS
    fcs = zlib.crc32(frame) ^ (0xFFFFFFFF if bad_fcs else 0)
    return frame + struct.pack("<I", fcs)


async def send_mii(rx_clk: Any, rxd: Any, rx_dv: Any, frame: bytes, ifg_nibbles: int = 24) -> None:
    """Drive preamble, SFD and frame on the MII receive pins, low nibble first, changing on rx_clk's falling edge
    (the PHY's launch edge; the MAC samples on the rising edge). Then an inter-frame gap."""
    for b in PREAMBLE_SFD + frame:
        for nib in (b & 0xF, b >> 4):
            await FallingEdge(rx_clk)
            rxd.value = nib
            rx_dv.value = 1
    await FallingEdge(rx_clk)
    rx_dv.value = 0
    rxd.value = 0
    for _ in range(ifg_nibbles - 1):
        await FallingEdge(rx_clk)


async def collect_mii_tx(tx_clk: Any, txd: Any, tx_en: Any, frames: list[bytes]) -> None:
    """Forever: append each frame the DUT transmits (preamble and SFD included), sampled mid-cycle on tx_clk's
    falling edge (the MAC launches on the rising edge), nibbles low first."""
    nibbles: list[int] = []
    while True:
        await FallingEdge(tx_clk)
        if int(tx_en.value):
            nibbles.append(int(txd.value))
        elif nibbles:
            if len(nibbles) % 2:
                raise AssertionError(f"odd nibble count {len(nibbles)} in a transmitted frame")
            frames.append(bytes(nibbles[k] | (nibbles[k + 1] << 4) for k in range(0, len(nibbles), 2)))
            nibbles = []


def parse_udp_frame(wire: bytes) -> dict[str, Any]:
    """A transmitted frame (with preamble/SFD) -> its addresses and UDP payload. Raises on a bad preamble, FCS,
    IPv4 header checksum or length."""
    if wire[:8] != PREAMBLE_SFD:
        raise AssertionError(f"bad preamble/SFD {wire[:8].hex()}")
    frame = wire[8:]
    if len(frame) < 64:
        raise AssertionError(f"frame of {len(frame)} bytes is under the 64-byte minimum")
    if zlib.crc32(frame[:-4]) != struct.unpack("<I", frame[-4:])[0]:
        raise AssertionError("bad FCS")
    if frame[12:14] != b"\x08\x00":
        raise AssertionError(f"ethertype {frame[12:14].hex()}, not IPv4")
    ip = frame[14:34]
    if ip[0] != 0x45 or ip[9] != 17:
        raise AssertionError("not IPv4/UDP without options")
    if ip_checksum(ip) != 0:
        raise AssertionError("bad IPv4 header checksum")
    total = struct.unpack(">H", ip[2:4])[0]
    sport, dport, ulen = struct.unpack(">HHH", frame[34:40])
    if ulen != total - 20:
        raise AssertionError(f"UDP length {ulen} vs. IP total {total}")
    return {
        "dst_mac": frame[0:6], "src_mac": frame[6:12],
        "src_ip": int.from_bytes(ip[12:16], "big"), "dst_ip": int.from_bytes(ip[16:20], "big"),
        "sport": sport, "dport": dport, "payload": frame[42:42 + ulen - 8],
    }
