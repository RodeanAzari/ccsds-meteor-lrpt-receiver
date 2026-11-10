// Board -> host packet parsers (docs/protocol.md); rules mirror scripts/board_rx.py and
// scripts/board_stats.py.
#include "gs/board_packets.hpp"

#include <algorithm>

namespace gs {

namespace {

// Big-endian reads from byte offsets the caller has bounds-checked.
std::uint16_t be16(std::span<const std::uint8_t> b, std::size_t at) {
    return static_cast<std::uint16_t>((static_cast<unsigned>(b[at]) << 8U) | b[at + 1]);
}

std::uint32_t be32(std::span<const std::uint8_t> b, std::size_t at) {
    return (static_cast<std::uint32_t>(b[at]) << 24U) | (static_cast<std::uint32_t>(b[at + 1]) << 16U) |
           (static_cast<std::uint32_t>(b[at + 2]) << 8U) | static_cast<std::uint32_t>(b[at + 3]);
}

std::uint64_t be64(std::span<const std::uint8_t> b, std::size_t at) {
    return (static_cast<std::uint64_t>(be32(b, at)) << 32U) | be32(b, at + 4);
}

}  // namespace

std::string_view to_string(ParseError e) {
    switch (e) {
        case ParseError::kOk:
            return "ok";
        case ParseError::kShort:
            return "short packet";
        case ParseError::kType:
            return "wrong type";
        case ParseError::kVersion:
            return "unknown version";
        case ParseError::kLength:
            return "length disagrees with n";
        case ParseError::kReservedBits:
            return "reserved bits set";
        case ParseError::kOutOfRange:
            return "status out of range";
    }
    return "unknown error";
}

ParseError parse_header(std::span<const std::uint8_t> pkt, Header& out) {
    if (pkt.size() < kHeaderBytes) {
        return ParseError::kShort;
    }
    out.type = pkt[0];
    out.version = pkt[1];
    out.n = be16(pkt, 2);
    out.pkt_seq = be32(pkt, 4);
    out.uptime = be64(pkt, 8);
    return ParseError::kOk;
}

ParseError parse_cadu(std::span<const std::uint8_t> pkt, CaduPacket& out) {
    if (const ParseError e = parse_header(pkt, out.header); e != ParseError::kOk) {
        return e;
    }
    if (out.header.type != kTypeCadu) {
        return ParseError::kType;
    }
    if (out.header.version != kCaduVersion) {
        return ParseError::kVersion;
    }
    if (out.header.n != kCaduPayloadBytes || pkt.size() != kHeaderBytes + kCaduPayloadBytes) {
        return ParseError::kLength;
    }
    const auto st = pkt.subspan(kHeaderBytes, kCaduStatusBytes);
    const std::uint8_t flags = st[0];
    if ((flags & 0xF8U) != 0 || st[6] != 0 || st[7] != 0) {
        return ParseError::kReservedBits;
    }
    out.asm_errors = st[1];
    if (out.asm_errors > kMaxAsmErrors) {
        return ParseError::kOutOfRange;
    }
    const std::span<std::int8_t, kCodewords> corr(out.corrections);
    for (std::size_t b = 0; b < kCodewords; ++b) {
        const std::uint8_t r = st[2 + b];
        const bool fail = (r & 0x80U) != 0;
        const int count = r & 0x1F;
        if ((r & 0x60U) != 0) {
            return ParseError::kReservedBits;
        }
        if ((fail && count != 0) || count > kMaxCorrections) {
            return ParseError::kOutOfRange;
        }
        corr[b] = fail ? std::int8_t{-1} : static_cast<std::int8_t>(count);
    }
    out.alternate = (flags & 0x01U) != 0;
    out.swap = (flags & 0x02U) != 0;
    out.flywheel = (flags & 0x04U) != 0;
    out.cadu = pkt.subspan(kHeaderBytes + kCaduStatusBytes, kCaduBytes);
    return ParseError::kOk;
}

ParseError parse_stats(std::span<const std::uint8_t> pkt, StatsPacket& out) {
    if (const ParseError e = parse_header(pkt, out.header); e != ParseError::kOk) {
        return e;
    }
    if (out.header.type != kTypeStats) {
        return ParseError::kType;
    }
    if (out.header.version != kStatsVersion) {
        return ParseError::kVersion;
    }
    if (pkt.size() != kHeaderBytes + (4 * static_cast<std::size_t>(out.header.n))) {
        return ParseError::kLength;
    }
    out.known = std::min<std::size_t>(out.header.n, out.fields.size());
    out.fields = {};
    std::size_t at = kHeaderBytes;
    for (std::uint32_t& f : std::span(out.fields).first(out.known)) {
        f = be32(pkt, at);
        at += 4;
    }
    return ParseError::kOk;
}

}  // namespace gs
