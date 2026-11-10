// Board -> host packet parsers against packets built by hand from docs/protocol.md, and against packets the
// RTL sent in simulation (gs/tests/data, written by tb/cocotb/test_arty_rx_eth_top_full.py with CAPTURE_DIR
// set).
//
// Why it matters: every CADU and counter of a hardware run reaches the ground station through these parsers.
// A status bit or the body one byte off passes garbage as decoded or blames RS for a parsing error; accepting
// a malformed packet hides a fault on the board (the 2026-11-08 regression sent a 163-byte CADU-typed
// packet). The rules are docs/protocol.md's, and the reference parsers (scripts/board_rx.py,
// scripts/board_stats.py) reject the same cases.
#include "gs/board_packets.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <sstream>
#include <string>
#include <vector>

namespace {

using Bytes = std::vector<std::uint8_t>;

// Appends the low N bytes of v, most significant first.
template <int N>
void put_be(Bytes& b, std::uint64_t v) {
    for (int k = N - 1; k >= 0; --k) {
        b.push_back(static_cast<std::uint8_t>(v >> (8U * static_cast<unsigned>(k))));
    }
}

struct HeaderSpec {
    std::uint8_t type = 0;
    std::uint8_t version = 0;
    std::uint16_t n = 0;
    std::uint32_t seq = 0;
    std::uint64_t uptime = 0;
};

Bytes header(const HeaderSpec& h) {
    Bytes b{h.type, h.version};
    put_be<2>(b, h.n);
    put_be<4>(b, h.seq);
    put_be<8>(b, h.uptime);
    return b;
}

struct CaduSpec {
    std::uint8_t flags = 0b101;
    std::uint8_t asm_errors = 3;
    std::array<std::uint8_t, 4> rs{0, 16, 0x80, 7};
    std::array<std::uint8_t, 2> reserved{0, 0};
    std::uint8_t type = 2;
    std::uint8_t version = 1;
    std::uint16_t n = 1032;
};

// scripts/tests/test_board_rx.py packet(): same defaults, so both suites test the same bytes.
Bytes cadu_packet(const CaduSpec& s = {}) {
    Bytes b = header({.type = s.type, .version = s.version, .n = s.n, .seq = 9, .uptime = 55});
    b.push_back(s.flags);
    b.push_back(s.asm_errors);
    b.insert(b.end(), s.rs.begin(), s.rs.end());
    b.insert(b.end(), s.reserved.begin(), s.reserved.end());
    for (int k = 0; k < 1024; ++k) {
        b.push_back(static_cast<std::uint8_t>(k));
    }
    return b;
}

Bytes stats_packet(std::uint16_t n, std::uint8_t version = 2) {
    Bytes b = header({.type = 1, .version = version, .n = n, .seq = 7, .uptime = 123456789});
    for (std::uint32_t k = 0; k < n; ++k) {
        put_be<4>(b, 0x01020304U + k);
    }
    return b;
}

TEST(ParseCadu, FieldsInProtocolOrder) {
    const Bytes p = cadu_packet();
    ASSERT_EQ(p.size(), 1048U);
    gs::CaduPacket c;
    ASSERT_EQ(gs::parse_cadu(p, c), gs::ParseError::kOk);
    EXPECT_EQ(c.header.pkt_seq, 9U);
    EXPECT_EQ(c.header.uptime, 55U);
    EXPECT_TRUE(c.alternate);  // flags bit 0
    EXPECT_FALSE(c.swap);      // bit 1
    EXPECT_TRUE(c.flywheel);   // bit 2
    EXPECT_EQ(c.asm_errors, 3);
    EXPECT_EQ(c.corrections, (std::array<std::int8_t, 4>{0, 16, -1, 7}));  // codeword 2 failed (bit 7)
    ASSERT_EQ(c.cadu.size(), 1024U);
    for (std::size_t k = 0; k < c.cadu.size(); ++k) {
        ASSERT_EQ(c.cadu[k], static_cast<std::uint8_t>(k)) << "CADU byte " << k;
    }
}

// Zero-copy: the CADU is a view of the datagram at byte 24, not a copy (nothing is allocated per packet).
TEST(ParseCadu, CaduPointsIntoTheDatagram) {
    const Bytes p = cadu_packet();
    gs::CaduPacket c;
    ASSERT_EQ(gs::parse_cadu(p, c), gs::ParseError::kOk);
    EXPECT_EQ(c.cadu.data(), p.data() + 24);
}

struct BadCadu {
    const char* name;
    Bytes pkt;
    gs::ParseError want;
};

class ParseCaduRejects : public ::testing::TestWithParam<BadCadu> {};

TEST_P(ParseCaduRejects, Malformed) {
    gs::CaduPacket c;
    EXPECT_EQ(gs::parse_cadu(GetParam().pkt, c), GetParam().want) << GetParam().name;
}

Bytes truncated(Bytes b, std::size_t n) {
    b.resize(b.size() - n);
    return b;
}

Bytes extended(Bytes b) {
    b.push_back(0);
    return b;
}

INSTANTIATE_TEST_SUITE_P(
    Protocol, ParseCaduRejects,
    ::testing::Values(
        BadCadu{"stats type", cadu_packet({.type = 1}), gs::ParseError::kType},
        BadCadu{"version 2", cadu_packet({.version = 2}), gs::ParseError::kVersion},
        BadCadu{"n 1031", cadu_packet({.n = 1031}), gs::ParseError::kLength},
        BadCadu{"one byte short", truncated(cadu_packet(), 1), gs::ParseError::kLength},
        BadCadu{"one byte long", extended(cadu_packet()), gs::ParseError::kLength},
        BadCadu{"163 bytes, CADU-typed (2026-11-08)", truncated(cadu_packet(), 1048 - 163),
                gs::ParseError::kLength},
        BadCadu{"flags bit 3", cadu_packet({.flags = 0b1000}), gs::ParseError::kReservedBits},
        BadCadu{"asm 33", cadu_packet({.asm_errors = 33}), gs::ParseError::kOutOfRange},
        BadCadu{"rs bit 5", cadu_packet({.rs = {0x20, 0, 0, 0}}), gs::ParseError::kReservedBits},
        BadCadu{"rs bit 6, codeword 3", cadu_packet({.rs = {0, 0, 0, 0x40}}), gs::ParseError::kReservedBits},
        BadCadu{"fail with a count", cadu_packet({.rs = {0x81, 0, 0, 0}}), gs::ParseError::kOutOfRange},
        BadCadu{"17 corrections", cadu_packet({.rs = {17, 0, 0, 0}}), gs::ParseError::kOutOfRange},
        BadCadu{"reserved byte 7", cadu_packet({.reserved = {0, 1}}), gs::ParseError::kReservedBits},
        BadCadu{"reserved byte 6", cadu_packet({.reserved = {1, 0}}), gs::ParseError::kReservedBits},
        BadCadu{"two bytes", Bytes{2, 1}, gs::ParseError::kShort},
        BadCadu{"empty", Bytes{}, gs::ParseError::kShort}));

TEST(ParseCadu, LimitsAccepted) {
    gs::CaduPacket c;
    EXPECT_EQ(gs::parse_cadu(cadu_packet({.flags = 0b111, .asm_errors = 32, .rs = {16, 0, 0x80, 0}}), c),
              gs::ParseError::kOk);
    EXPECT_EQ(c.corrections, (std::array<std::int8_t, 4>{16, 0, -1, 0}));
}

TEST(ParseStats, FieldsInProtocolOrder) {
    const Bytes p = stats_packet(29);
    ASSERT_EQ(p.size(), 132U);  // docs/protocol.md packet size
    gs::StatsPacket s;
    ASSERT_EQ(gs::parse_stats(p, s), gs::ParseError::kOk);
    EXPECT_EQ(s.header.pkt_seq, 7U);
    EXPECT_EQ(s.header.uptime, 123456789U);
    ASSERT_EQ(s.known, 29U);
    for (std::size_t k = 0; k < 29; ++k) {
        EXPECT_EQ(s.fields[k], 0x01020304U + k) << gs::kStatsFieldNames[k];
    }
    EXPECT_EQ(gs::kStatsFieldNames[17], "mac_restarts");
    EXPECT_EQ(gs::kStatsFieldNames[26], "nco_word");  // ADR 0014
}

// arty_ddc_eth_top sends n = 18; a newer top may append fields: known ones are read, the rest ignored.
TEST(ParseStats, ShorterAndLongerBoardsAccepted) {
    gs::StatsPacket s;
    ASSERT_EQ(gs::parse_stats(stats_packet(18), s), gs::ParseError::kOk);
    EXPECT_EQ(s.known, 18U);
    EXPECT_EQ(s.fields[17], 0x01020304U + 17);
    EXPECT_EQ(s.fields[18], 0U);
    ASSERT_EQ(gs::parse_stats(stats_packet(40), s), gs::ParseError::kOk);
    EXPECT_EQ(s.known, 29U);
    EXPECT_EQ(s.fields[28], 0x01020304U + 28);
}

TEST(ParseStats, Rejects) {
    gs::StatsPacket s;
    EXPECT_EQ(gs::parse_stats(stats_packet(29, 1), s), gs::ParseError::kVersion);
    EXPECT_EQ(gs::parse_stats(truncated(stats_packet(29), 1), s), gs::ParseError::kLength);
    EXPECT_EQ(gs::parse_stats(extended(stats_packet(29)), s), gs::ParseError::kLength);
    EXPECT_EQ(gs::parse_stats(cadu_packet(), s), gs::ParseError::kType);
    EXPECT_EQ(gs::parse_stats(Bytes(15, 1), s), gs::ParseError::kShort);
}

// Packets the RTL sent (simulation), with the values the Python reference parsers read from them.
// expected.txt, one line per packet:  <file> cadu <seq> <uptime> <flags> <asm> <rs0> <rs1> <rs2> <rs3>
//                                     <file> stats <seq> <uptime> <n> <field 0> ... <field n-1>
TEST(Captured, RtlPacketsParseAsTheReferenceReadsThem) {
    const std::filesystem::path dir = GS_TEST_DATA_DIR;
    std::ifstream idx(dir / "expected.txt");
    ASSERT_TRUE(idx) << (dir / "expected.txt") << " missing";  // fail, never skip
    std::string line;
    int cadus = 0;
    int stats = 0;
    while (std::getline(idx, line)) {
        std::istringstream in(line);
        std::string file;
        std::string kind;
        std::uint64_t seq = 0;
        std::uint64_t uptime = 0;
        in >> file >> kind >> seq >> uptime;
        std::ifstream f(dir / file, std::ios::binary);
        ASSERT_TRUE(f) << file;
        const Bytes pkt((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
        if (kind == "cadu") {
            int flags = 0;
            int asm_errors = 0;
            std::array<int, 4> rs{};
            in >> flags >> asm_errors >> rs[0] >> rs[1] >> rs[2] >> rs[3];
            gs::CaduPacket c;
            ASSERT_EQ(gs::parse_cadu(pkt, c), gs::ParseError::kOk) << file;
            EXPECT_EQ(c.header.pkt_seq, seq) << file;
            EXPECT_EQ(c.header.uptime, uptime) << file;
            EXPECT_EQ(int(c.alternate) | (int(c.swap) << 1) | (int(c.flywheel) << 2), flags) << file;
            EXPECT_EQ(c.asm_errors, asm_errors) << file;
            for (std::size_t b = 0; b < 4; ++b) {
                EXPECT_EQ(c.corrections[b], rs[b]) << file << " codeword " << b;
            }
            EXPECT_TRUE(std::equal(c.cadu.begin(), c.cadu.end(), pkt.begin() + 24)) << file;
            // The ASM as received (docs/protocol.md: bytes 0-3 of the CADU): intact when no ASM bit was in
            // error.
            if (asm_errors == 0) {
                EXPECT_EQ((std::uint32_t{c.cadu[0]} << 24U | std::uint32_t{c.cadu[1]} << 16U |
                           std::uint32_t{c.cadu[2]} << 8U | c.cadu[3]),
                          0x1ACFFC1DU)
                    << file;
            }
            ++cadus;
        } else {
            std::size_t n = 0;
            in >> n;
            gs::StatsPacket s;
            ASSERT_EQ(gs::parse_stats(pkt, s), gs::ParseError::kOk) << file;
            EXPECT_EQ(s.header.pkt_seq, seq) << file;
            EXPECT_EQ(s.header.uptime, uptime) << file;
            ASSERT_EQ(s.known, n) << file;
            for (std::size_t k = 0; k < n; ++k) {
                std::uint64_t v = 0;
                in >> v;
                EXPECT_EQ(s.fields[k], v) << file << " " << gs::kStatsFieldNames[k];
            }
            ++stats;
        }
    }
    EXPECT_GE(cadus, 2);
    EXPECT_GE(stats, 2);
}

}  // namespace
