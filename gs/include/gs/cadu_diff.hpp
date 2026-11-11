// gs-diff's comparison: our CADUs against SatDump's decode of the same recording (buildplan §4, §8.5).
// Frames are matched by (VCID, VCDU counter), not by position: either side may lack frames the other decoded
// (RS gate, sync at the pass edges, packets lost on the way). The acceptance test is bit-exact on the RS data
// bytes 4-895 of every frame both sides have; SatDump writes the ASM and the parity bytes as received
// (docs/signal-spec.md "What gs-diff can compare"), so differences there are counted apart and never fail.
// Offline tool: the inputs are read whole at start-up.
#ifndef GS_CADU_DIFF_HPP
#define GS_CADU_DIFF_HPP

#include <compare>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <vector>

#include "gs/board_packets.hpp"

namespace gs {

inline constexpr std::size_t kAsmEnd = 4;       // CADU bytes 0-3: ASM
inline constexpr std::size_t kRsDataEnd = 896;  // bytes 4-895: RS data (4 x 223); 896-1023: parity

struct FrameKey {
    std::uint8_t vcid = 0;      // byte 5 bits 5-0
    std::uint32_t counter = 0;  // bytes 6-8, big-endian (24 bits)
    auto operator<=>(const FrameKey&) const = default;
};

FrameKey frame_key(std::span<const std::uint8_t, kCaduBytes> cadu);

struct Divergence {
    FrameKey key;
    std::size_t ours_frame = 0;  // index in each file
    std::size_t ref_frame = 0;
    std::size_t byte = 0;  // CADU offset, 4-895
    int bit = 0;           // 0 = most significant (CCSDS numbering)
};

struct CaduDiff {
    std::size_t ours = 0;  // frames in each file
    std::size_t ref = 0;
    std::size_t common = 0;
    std::size_t data_frames_differ = 0;  // the acceptance test: must stay 0
    std::size_t data_bytes_differ = 0;
    std::size_t data_bits_differ = 0;
    std::size_t asm_frames_differ = 0;  // expected: SatDump keeps the ASM as received
    std::size_t parity_frames_differ = 0;
    std::size_t parity_bytes_differ = 0;
    std::vector<FrameKey> only_ours;  // file order
    std::vector<FrameKey> only_ref;
    std::optional<Divergence> first;  // the first common frame (in our file's order) whose data differ
    // Passes only if there is something to compare and every compared data byte is equal.
    [[nodiscard]] bool passed() const { return common > 0 && data_frames_differ == 0; }
};

// ours, ref: whole files of back-to-back 1,024-byte CADUs. Returns false with `error` set if a file is not a
// whole number of CADUs or holds one (VCID, counter) twice (it could not be matched unambiguously).
bool diff_cadus(std::span<const std::uint8_t> ours, std::span<const std::uint8_t> ref, CaduDiff& out,
                std::string& error);

}  // namespace gs

#endif  // GS_CADU_DIFF_HPP
