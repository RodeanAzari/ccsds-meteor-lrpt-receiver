#include "gs/iq_replay.hpp"

#include <charconv>
#include <cstring>
#include <limits>

namespace gs {

void build_packet(std::uint64_t seq, std::span<const std::uint8_t, kIqBytes> iq,
                  std::span<std::uint8_t, kPacketBytes> out) {
    for (std::size_t i = 0; i < kSeqBytes; ++i) {
        out[i] = static_cast<std::uint8_t>(seq >> (8 * (kSeqBytes - 1 - i)));
    }
    std::memcpy(out.data() + kSeqBytes, iq.data(), kIqBytes);
}

std::int64_t deadline_ns(std::uint64_t k, std::uint64_t sample_rate, std::uint64_t speed_milli) {
    // samples * 1e9 * 1000 / (rate * speed_milli); 128-bit so a 15-min pass at any speed fits.
    const unsigned __int128 num =
        static_cast<unsigned __int128>(k) * kSamplesPerPacket * 1'000'000'000ULL * 1000ULL;
    const unsigned __int128 den = static_cast<unsigned __int128>(sample_rate) * speed_milli;
    return static_cast<std::int64_t>(num / den);
}

namespace {

template <typename T>
bool parse_uint(std::string_view s, T& out) {
    const auto* end = s.data() + s.size();
    auto [p, ec] = std::from_chars(s.data(), end, out);
    return ec == std::errc{} && p == end;
}

// "4" -> 4000, "0.5" -> 500, "1.25" -> 1250; at most 3 decimals.
bool parse_speed(std::string_view s, std::uint64_t& milli) {
    const auto dot = s.find('.');
    std::uint64_t whole = 0;
    if (!parse_uint(s.substr(0, dot), whole) || whole > std::numeric_limits<std::uint32_t>::max()) {
        return false;
    }
    std::uint64_t frac = 0;
    if (dot != std::string_view::npos) {
        std::string_view f = s.substr(dot + 1);
        if (f.empty() || f.size() > 3 || !parse_uint(f, frac)) return false;
        for (std::size_t i = f.size(); i < 3; ++i) frac *= 10;
    }
    milli = whole * 1000 + frac;
    return milli > 0;
}

bool split_dest(std::string_view s, std::string& ip, std::uint16_t& port) {
    const auto colon = s.rfind(':');
    if (colon == std::string_view::npos) return false;
    ip = std::string(s.substr(0, colon));
    return !ip.empty() && parse_uint(s.substr(colon + 1), port) && port != 0;
}

}  // namespace

std::string_view replay_usage() {
    return "usage: gs-replay FILE.cu8 [--dest IP:PORT] [--iface IP] [--ttl N]\n"
           "                 [--rate SPS] [--speed X | --flat-out] [--count PACKETS]\n"
           "  --dest      destination (default 239.1.1.1:26400)\n"
           "  --iface     multicast egress interface address\n"
           "  --rate      file sample rate in S/s (default 1024000)\n"
           "  --speed     pace at X times real time, up to 3 decimals (default 1)\n"
           "  --flat-out  send as fast as the socket allows\n"
           "  --count     stop after this many packets\n";
}

std::optional<ReplayOptions> parse_replay_args(int argc, const char* const* argv,
                                               std::string& error) {
    ReplayOptions o;
    bool have_file = false;
    for (int i = 1; i < argc; ++i) {
        const std::string_view a = argv[i];
        const bool has_value = i + 1 < argc;
        const std::string_view v = has_value ? std::string_view(argv[i + 1]) : std::string_view{};
        bool ok = true;
        if (a == "--flat-out") {
            o.speed_milli = 0;
            continue;
        }
        if (a == "--dest" || a == "--iface" || a == "--ttl" || a == "--rate" || a == "--speed" ||
            a == "--count") {
            if (!has_value) {
                error = std::string(a) + " needs a value";
                return std::nullopt;
            }
            ++i;
            if (a == "--dest") ok = split_dest(v, o.dest_ip, o.dest_port);
            else if (a == "--iface") o.iface_ip = std::string(v);
            else if (a == "--ttl") ok = parse_uint(v, o.ttl) && o.ttl >= 1 && o.ttl <= 255;
            else if (a == "--rate") ok = parse_uint(v, o.sample_rate) && o.sample_rate > 0;
            else if (a == "--speed") ok = parse_speed(v, o.speed_milli);
            else ok = parse_uint(v, o.max_packets) && o.max_packets > 0;
            if (!ok) {
                error = "bad value for " + std::string(a) + ": " + std::string(v);
                return std::nullopt;
            }
            continue;
        }
        if (a.starts_with("-") || have_file) {
            error = "unexpected argument: " + std::string(a);
            return std::nullopt;
        }
        o.file = std::string(a);
        have_file = true;
    }
    if (!have_file) {
        error = "no input file";
        return std::nullopt;
    }
    return o;
}

}  // namespace gs
