// IQ replay packet format and pacing (docs/protocol.md §IQ replay, ADR 0009).
#ifndef GS_IQ_REPLAY_HPP
#define GS_IQ_REPLAY_HPP

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <string_view>

namespace gs {

// docs/protocol.md §IQ replay: 8-byte big-endian sequence, then 512 cu8 samples (I, Q).
inline constexpr std::size_t kSeqBytes = 8;
inline constexpr std::size_t kSamplesPerPacket = 512;
inline constexpr std::size_t kIqBytes = 2 * kSamplesPerPacket;
inline constexpr std::size_t kPacketBytes = kSeqBytes + kIqBytes;

// Writes `seq` big-endian into the first 8 bytes of `out`, then copies `iq` unchanged.
void build_packet(std::uint64_t seq, std::span<const std::uint8_t, kIqBytes> iq,
                  std::span<std::uint8_t, kPacketBytes> out);

// Monotonic-clock offset (ns from the start of the replay) at which packet `k` is due:
// k * kSamplesPerPacket / (sample_rate * speed). Exact integer math, no drift over a pass.
std::int64_t deadline_ns(std::uint64_t k, std::uint64_t sample_rate, std::uint64_t speed_milli);

struct ReplayOptions {
    std::string file;
    std::string dest_ip = "239.1.1.1";  // default group of fpga-eth-core examples/rx_stats
    std::uint16_t dest_port = 26400;
    std::string iface_ip;                   // multicast egress interface; empty = kernel default
    std::uint64_t sample_rate = 1'024'000;  // CLAUDE.md §2.3 capture rate
    std::uint64_t speed_milli = 1000;       // 1000 = real time; 0 = flat out
    std::uint64_t max_packets = 0;          // 0 = whole file
    int ttl = 1;
};

// Parses argv into options. On failure returns nullopt and sets `error`.
std::optional<ReplayOptions> parse_replay_args(int argc, const char* const* argv, std::string& error);

std::string_view replay_usage();

}  // namespace gs

#endif  // GS_IQ_REPLAY_HPP
