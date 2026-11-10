// libFuzzer target for the board -> host packet parsers (CLAUDE.md §5.3: the packet parser is fuzzed).
// Any bytes may arrive on UDP port 26401. Beyond ASan/UBSan findings, it checks the invariants callers rely
// on: an accepted CADU is exactly the protocol's size and its view lies inside the datagram at byte 24;
// corrections are -1..16; an accepted stats packet is 16 + 4n bytes with at most 29 known fields; and a
// packet is never both.
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <span>

#include "gs/board_packets.hpp"

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    const std::span<const std::uint8_t> pkt(data, size);
    gs::CaduPacket c;
    gs::StatsPacket s;
    gs::Header h;
    const bool is_cadu = gs::parse_cadu(pkt, c) == gs::ParseError::kOk;
    const bool is_stats = gs::parse_stats(pkt, s) == gs::ParseError::kOk;
    const bool has_header = gs::parse_header(pkt, h) == gs::ParseError::kOk;
    if (has_header != (size >= gs::kHeaderBytes) || (is_cadu && is_stats)) {
        std::abort();
    }
    if (is_cadu) {
        if (size != gs::kHeaderBytes + gs::kCaduPayloadBytes || c.cadu.data() != data + 24 ||
            c.cadu.size() != gs::kCaduBytes || c.asm_errors > gs::kMaxAsmErrors) {
            std::abort();
        }
        for (const std::int8_t r : c.corrections) {
            if (r < -1 || r > gs::kMaxCorrections) {
                std::abort();
            }
        }
    }
    if (is_stats && (size != gs::kHeaderBytes + (4 * static_cast<std::size_t>(s.header.n)) ||
                     s.known > s.fields.size() || s.known > s.header.n)) {
        std::abort();
    }
    return 0;
}
