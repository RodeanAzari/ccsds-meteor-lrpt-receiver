// gs-diff: our CADUs (gs-rx's cadus.bin) against SatDump's .cadu of the same recording (buildplan §4, §8.5).
//
//   gs-diff OURS SATDUMP [--list N]
//
// Matches frames by (VCID, VCDU counter) and compares them (gs/cadu_diff.hpp). Prints key=value lines: frame
// counts, frames only one side has (the first N of each, default 10), the data-byte differences (the
// acceptance test), ASM and parity differences (expected: SatDump writes them as received), and the first
// data divergence (frame, byte, bit). Exit 0: at least one common frame and every common frame's data bytes
// equal; 1: not so; 2: bad arguments or unreadable or malformed input.
#include <algorithm>
#include <charconv>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <span>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

#include "gs/cadu_diff.hpp"

namespace {

constexpr const char* kUsage = "usage: gs-diff OURS SATDUMP [--list N]\n";

bool read_file(const char* path, std::vector<std::uint8_t>& out) {
    std::ifstream f(path, std::ios::binary);
    if (!f) {
        return false;
    }
    out.assign(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
    return !f.bad();
}

std::string keys(const std::vector<gs::FrameKey>& v, std::size_t n) {
    std::string s;
    for (std::size_t k = 0; k < std::min(n, v.size()); ++k) {
        s += (k != 0 ? "," : "") + std::to_string(v[k].vcid) + "/" + std::to_string(v[k].counter);
    }
    return s.empty() ? "-" : s;
}

}  // namespace

int main(int argc, char** argv) {
    const std::span<char*> args(argv, static_cast<std::size_t>(argc));
    std::size_t list = 10;
    if (args.size() == 5 && std::string_view(args[3]) == "--list") {
        const std::string_view v = args[4];
        const auto* end = v.data() + v.size();
        // from_chars takes [first, last), not a NUL-terminated string.
        // NOLINTNEXTLINE(bugprone-suspicious-stringview-data-usage)
        const auto r = std::from_chars(v.data(), end, list);
        if (r.ec != std::errc{} || r.ptr != end) {
            (void)std::fprintf(stderr, "gs-diff: bad value for --list: %s\n%s", args[4], kUsage);
            return 2;
        }
    } else if (args.size() != 3) {
        (void)std::fputs(kUsage, stderr);
        return 2;
    }
    std::vector<std::uint8_t> ours;
    std::vector<std::uint8_t> ref;
    for (const auto& [path, data] : {std::pair{args[1], &ours}, std::pair{args[2], &ref}}) {
        if (!read_file(path, *data)) {
            (void)std::fprintf(stderr, "gs-diff: cannot read %s\n", path);
            return 2;
        }
    }
    gs::CaduDiff d;
    std::string err;
    if (!gs::diff_cadus(ours, ref, d, err)) {
        (void)std::fprintf(stderr, "gs-diff: %s\n", err.c_str());
        return 2;
    }
    std::string s;
    const auto kv = [&](const char* k, const std::string& v) { s += std::string(k) + "=" + v + "\n"; };
    kv("ours_frames", std::to_string(d.ours));
    kv("satdump_frames", std::to_string(d.ref));
    kv("common", std::to_string(d.common));
    kv("only_ours", std::to_string(d.only_ours.size()));
    kv("only_satdump", std::to_string(d.only_ref.size()));
    kv("only_ours_first", keys(d.only_ours, list));  // vcid/counter
    kv("only_satdump_first", keys(d.only_ref, list));
    kv("data_frames_differ", std::to_string(d.data_frames_differ));
    kv("data_bytes_differ", std::to_string(d.data_bytes_differ));
    kv("data_bits_differ", std::to_string(d.data_bits_differ));
    kv("asm_frames_differ", std::to_string(d.asm_frames_differ));
    kv("parity_frames_differ", std::to_string(d.parity_frames_differ));
    kv("parity_bytes_differ", std::to_string(d.parity_bytes_differ));
    if (d.first) {
        const gs::Divergence& f = *d.first;
        kv("first_divergence", std::to_string(f.key.vcid) + "/" + std::to_string(f.key.counter) +
                                   ",ours_frame:" + std::to_string(f.ours_frame) +
                                   ",satdump_frame:" + std::to_string(f.ref_frame) +
                                   ",byte:" + std::to_string(f.byte) + ",bit:" + std::to_string(f.bit));
    } else {
        kv("first_divergence", "-");
    }
    kv("result", d.passed() ? "PASS" : "FAIL");
    (void)std::fputs(s.c_str(), stdout);
    if (d.common == 0) {
        (void)std::fputs("gs-diff: no frame in common: nothing was compared\n", stderr);
    }
    return d.passed() ? 0 : 1;
}
