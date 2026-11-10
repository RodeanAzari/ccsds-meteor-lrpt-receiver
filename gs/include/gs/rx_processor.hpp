// gs-rx's processing stage: board -> host datagrams in, good CADUs and space packets out (buildplan §4, ADR
// 0015). Per datagram: a CADU packet (type 2) with every codeword corrected goes to the CADU sink and the
// demultiplexer, as SatDump's rs_usecheck does; one with an uncorrectable codeword is dropped and counted; a
// stats packet (type 1) is kept as the board's latest counters; anything else is counted as malformed. A gap
// in the CADU packets' pkt_seq (lost between board and host) is counted. Nothing is allocated per datagram.
#ifndef GS_RX_PROCESSOR_HPP
#define GS_RX_PROCESSOR_HPP

#include <cstdint>
#include <memory>
#include <span>

#include "gs/board_packets.hpp"
#include "gs/space_packets.hpp"

namespace gs {

struct RxCounts {
    std::uint64_t datagrams = 0;
    std::uint64_t cadu_packets = 0;      // well-formed CADU packets
    std::uint64_t cadus_good = 0;        // every codeword corrected: written and demultiplexed
    std::uint64_t cadus_rs_failed = 0;   // an uncorrectable codeword: dropped (SatDump's rs_usecheck)
    std::uint64_t cadu_seq_missing = 0;  // CADU packets missing by pkt_seq (lost between board and host)
    std::uint64_t cadu_seq_late = 0;     // older than one already seen: reordered, already counted as missing
                                         // when skipped (net lost = cadu_seq_missing - cadu_seq_late)
    std::uint64_t stats_packets = 0;
    std::uint64_t malformed = 0;  // neither a valid CADU nor a valid stats packet
    bool operator==(const RxCounts&) const = default;
};

class RxProcessor {
  public:
    // CaduSink(std::span<const std::uint8_t, 1024>), PacketSink(std::span<const std::uint8_t>): called in
    // order, the spans valid only during the call.
    template <class CaduSink, class PacketSink>
    void handle(std::span<const std::uint8_t> datagram, const CaduSink& on_cadu,
                const PacketSink& on_packet) {
        ++counts_.datagrams;
        CaduPacket c;
        if (parse_cadu(datagram, c) == ParseError::kOk) {
            ++counts_.cadu_packets;
            const std::uint32_t ahead = c.header.pkt_seq - next_seq_;  // mod 2^32
            if (!have_seq_ || ahead < (1U << 31U)) {
                counts_.cadu_seq_missing += have_seq_ ? ahead : 0;
                have_seq_ = true;
                next_seq_ = c.header.pkt_seq + 1;
            } else {
                ++counts_
                      .cadu_seq_late;  // still decoded: the demultiplexer sees its VCDU counter out of order
            }
            bool rs_ok = true;
            for (const std::int8_t r : c.corrections) {
                rs_ok = rs_ok && r >= 0;
            }
            if (!rs_ok) {
                ++counts_.cadus_rs_failed;
                return;
            }
            ++counts_.cadus_good;
            const std::span<const std::uint8_t, kCaduLen> cadu(c.cadu.data(), kCaduLen);
            on_cadu(cadu);
            demux_->work(cadu, on_packet);
            return;
        }
        StatsPacket s;
        if (parse_stats(datagram, s) == ParseError::kOk) {
            ++counts_.stats_packets;
            have_stats_ = true;
            stats_ = s;
            return;
        }
        ++counts_.malformed;
    }

    [[nodiscard]] const RxCounts& counts() const { return counts_; }
    [[nodiscard]] const DemuxCounts& demux_counts() const { return demux_->counts(); }
    // The board's latest stats packet, if any arrived.
    [[nodiscard]] const StatsPacket* last_stats() const { return have_stats_ ? &stats_ : nullptr; }

  private:
    std::unique_ptr<SpaceDemux> demux_ =
        std::make_unique<SpaceDemux>();  // 64 KB: allocated once, at start-up
    RxCounts counts_;
    bool have_seq_ = false;
    std::uint32_t next_seq_ = 0;
    bool have_stats_ = false;
    StatsPacket stats_;
};

}  // namespace gs

#endif  // GS_RX_PROCESSOR_HPP
