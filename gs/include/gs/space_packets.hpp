// VCID-5 CADUs -> CCSDS space packets (docs/signal-spec.md "Frame layers above the CADU", ADR 0015).
// The golden model is model/space_packets.py `Demux`; gs/tests/space_packets_test.cpp replays its vectors.
// Data path rules (CLAUDE.md §5.3): no allocation after construction, no exceptions; the packet in progress
// lives in a fixed buffer sized for the largest legal packet.
#ifndef GS_SPACE_PACKETS_HPP
#define GS_SPACE_PACKETS_HPP

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>

namespace gs {

inline constexpr std::size_t kCaduLen = 1024;
inline constexpr std::uint8_t kVcidMsumr = 5;     // signal-spec.md: SatDump demultiplexes VCID 5 only
inline constexpr std::size_t kZoneStart = 14;     // M_PDU packet zone: CADU bytes 14..895
inline constexpr std::size_t kZoneBytes = 882;    // MPDU_DATA_SIZE
inline constexpr std::uint16_t kNoHeader = 2047;  // first header pointer: no packet starts here
inline constexpr std::size_t kPacketHeader = 6;   // space packet primary header
inline constexpr std::size_t kMaxPacket = kPacketHeader + 65536;
inline constexpr std::uint32_t kCounterMask = 0xFFFFFF;  // VCDU counter, 24 bits

// ADR 0015: every VCID-5 CADU and every packet ends up in exactly one of these.
struct DemuxCounts {
    std::uint64_t cadus = 0;            // VCID-5 CADUs taken
    std::uint64_t other_vcid = 0;       // CADUs on other virtual channels, ignored
    std::uint64_t gaps = 0;             // VCDU counter discontinuities
    std::uint64_t packets = 0;          // packets emitted
    std::uint64_t dropped_gap = 0;      // packets in progress lost to a counter gap
    std::uint64_t dropped_length = 0;   // packets whose length disagreed with the first header pointer
    std::uint64_t bad_pointer = 0;      // M_PDUs with a first header pointer from 882 to 2046 (skipped)
    std::uint64_t dropped_pointer = 0;  // packets in progress lost to such an M_PDU
    bool operator==(const DemuxCounts&) const = default;
};

class SpaceDemux {
  public:
    // Feeds one CADU (ASM included, derandomized, RS-corrected; the caller drops RS-failed ones). Calls
    // emit(std::span<const std::uint8_t>) once per complete packet, in order; the span is valid during the
    // call.
    template <class Emit>
    void work(std::span<const std::uint8_t, kCaduLen> cadu, const Emit& emit) {
        if ((cadu[5] & 0x3FU) != kVcidMsumr) {
            ++counts_.other_vcid;
            return;
        }
        ++counts_.cadus;
        const std::uint32_t ctr = (std::uint32_t{cadu[6]} << 16U) | (std::uint32_t{cadu[7]} << 8U) | cadu[8];
        if (have_last_ && ctr != ((last_ + 1) & kCounterMask)) {
            ++counts_.gaps;
            counts_.dropped_gap += drop();
        }
        last_ = ctr;
        have_last_ = true;
        const auto fhp = static_cast<std::uint16_t>(((cadu[12] & 0x07U) << 8U) | cadu[13]);
        if (fhp >= kZoneBytes && fhp < kNoHeader) {
            ++counts_.bad_pointer;
            counts_.dropped_pointer += drop();
            return;
        }
        const auto zone = cadu.subspan<kZoneStart, kZoneBytes>();
        const std::size_t end = fhp == kNoHeader ? kZoneBytes : fhp;
        if (synced_ && len_ > 0) {
            // The packet in progress must end exactly at the next header, or not inside a zone without one.
            const std::size_t pos = fill(zone, 0, end);
            if (complete()) {
                if (pos == end) {
                    emit_packet(emit);
                } else {
                    counts_.dropped_length += drop();
                }
            } else if (fhp != kNoHeader) {
                counts_.dropped_length += drop();
            }
        }
        if (fhp == kNoHeader) {
            return;
        }
        len_ = 0;
        synced_ = true;
        std::size_t pos = fhp;
        while (pos < kZoneBytes) {
            pos = fill(zone, pos, kZoneBytes);
            if (complete()) {
                emit_packet(emit);
            }
        }
    }

    [[nodiscard]] const DemuxCounts& counts() const { return counts_; }

  private:
    [[nodiscard]] std::size_t need() const {
        if (len_ < kPacketHeader) {
            return kPacketHeader;
        }
        return kPacketHeader + ((std::size_t{pkt_[4]} << 8U) | pkt_[5]) + 1;
    }

    [[nodiscard]] bool complete() const { return len_ >= kPacketHeader && len_ == need(); }

    // Appends zone[pos, end) up to the packet's end (header first, then the length it gives). Returns the new
    // pos.
    std::size_t fill(std::span<const std::uint8_t, kZoneBytes> zone, std::size_t pos, std::size_t end) {
        while (true) {
            const bool had_header = len_ >= kPacketHeader;
            const std::size_t take = std::min(need() - len_, end - pos);
            std::copy_n(zone.begin() + static_cast<std::ptrdiff_t>(pos), take,
                        pkt_.begin() + static_cast<std::ptrdiff_t>(len_));
            len_ += take;
            pos += take;
            if (!had_header && len_ >= kPacketHeader) {
                continue;  // header just completed: the length is known now
            }
            return pos;
        }
    }

    template <class Emit>
    void emit_packet(const Emit& emit) {
        ++counts_.packets;
        emit(std::span<const std::uint8_t>(pkt_.data(), len_));
        len_ = 0;
    }

    // Loses the packet in progress (returns 1 if there was one) and waits for the next first header pointer.
    std::uint64_t drop() {
        const std::uint64_t had = len_ > 0 ? 1 : 0;
        len_ = 0;
        synced_ = false;
        return had;
    }

    std::array<std::uint8_t, kMaxPacket> pkt_{};
    std::size_t len_ = 0;
    bool synced_ = false;
    bool have_last_ = false;
    std::uint32_t last_ = 0;
    DemuxCounts counts_;
};

}  // namespace gs

#endif  // GS_SPACE_PACKETS_HPP
