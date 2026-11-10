// Board -> host packets (docs/protocol.md "Board → host packets": common header, stats type 1, CADU type 2).
// The reference parsers are scripts/board_stats.py parse_stats and scripts/board_rx.py parse_cadu; these
// accept and reject exactly what they do. Data path rules (CLAUDE.md §5.3): no allocation, no exceptions,
// explicit big-endian reads; a parsed CADU points into the caller's datagram (it lives as long as that
// buffer).
#ifndef GS_BOARD_PACKETS_HPP
#define GS_BOARD_PACKETS_HPP

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

namespace gs {

inline constexpr std::size_t kHeaderBytes = 16;
inline constexpr std::uint8_t kTypeStats = 1;
inline constexpr std::uint8_t kTypeCadu = 2;
inline constexpr std::uint8_t kStatsVersion = 2;  // docs/protocol.md: fields 2, 3 redefined (ADR 0013)
inline constexpr std::uint8_t kCaduVersion = 1;
inline constexpr std::size_t kCaduBytes = 1024;
inline constexpr std::size_t kCaduStatusBytes = 8;
inline constexpr std::size_t kCaduPayloadBytes = kCaduStatusBytes + kCaduBytes;  // header field n
inline constexpr std::size_t kCodewords = 4;
inline constexpr int kMaxCorrections = 16;  // RS(255,223): t = 16
inline constexpr int kMaxAsmErrors = 32;

// docs/protocol.md "Stats" field table, in order. The board may send more (newer tops append); they are
// ignored.
inline constexpr std::array<std::string_view, 29> kStatsFieldNames{
    "ingest_ok",       "ingest_bad",    "ingest_gap",   "ingest_lost",  "eth_ok",      "eth_crc_err",
    "eth_rx_err",      "eth_runt",      "eth_oversize", "eth_ovf_lost", "udp_ok",      "udp_filtered",
    "udp_ip_csum_err", "udp_malformed", "rx_fifo_hwm",  "ddc_out",      "tx_underrun", "mac_restarts",
    "cadus_sent",      "fs_locked",     "fs_dropped",   "fs_slips",     "fs_early",    "flag_ovf",
    "len_err",         "ingest_late",   "nco_word",     "ctrl_ok",      "ctrl_bad"};

enum class ParseError : std::uint8_t {
    kOk,
    kShort,         // fewer bytes than the common header
    kType,          // not the packet type asked for
    kVersion,       // a version this parser does not know
    kLength,        // datagram length disagrees with the header's n (or a CADU's n is not 1,032)
    kReservedBits,  // a reserved bit or byte is set
    kOutOfRange,    // asm_errors > 32, corrections > 16, or a failed codeword with a nonzero count
};

std::string_view to_string(ParseError e);

struct Header {
    std::uint8_t type = 0;
    std::uint8_t version = 0;
    std::uint16_t n = 0;
    std::uint32_t pkt_seq = 0;
    std::uint64_t uptime = 0;  // core clock cycles (100 MHz) since the MAC left reset
};

struct CaduPacket {
    Header header;
    bool alternate = false;  // flags bit 0: phase hypothesis
    bool swap = false;       // flags bit 1
    bool flywheel = false;   // flags bit 2: emitted under a missed ASM
    std::uint8_t asm_errors = 0;
    std::array<std::int8_t, kCodewords> corrections{};  // symbols corrected per codeword; -1 = uncorrectable
    std::span<const std::uint8_t> cadu;                 // 1,024 bytes inside the caller's datagram
};

struct StatsPacket {
    Header header;
    std::size_t known = 0;  // min(n, kStatsFieldNames.size()): fields filled below
    std::array<std::uint32_t, kStatsFieldNames.size()> fields{};
};

// Reads the common header only (no type or version check). kShort if fewer than 16 bytes.
ParseError parse_header(std::span<const std::uint8_t> pkt, Header& out);

// A whole datagram as type 2 / type 1. On any error `out` is unspecified.
ParseError parse_cadu(std::span<const std::uint8_t> pkt, CaduPacket& out);
ParseError parse_stats(std::span<const std::uint8_t> pkt, StatsPacket& out);

}  // namespace gs

#endif  // GS_BOARD_PACKETS_HPP
