#include "gs/cadu_diff.hpp"

#include <bit>
#include <map>

namespace gs {

namespace {

using Cadu = std::span<const std::uint8_t, kCaduBytes>;

Cadu cadu_at(std::span<const std::uint8_t> file, std::size_t k) {
    return Cadu(file.subspan(k * kCaduBytes, kCaduBytes));
}

std::string describe(const FrameKey& k) {
    return "VCID " + std::to_string(k.vcid) + " counter " + std::to_string(k.counter);
}

// (VCID, counter) -> frame index, or an error naming the file and the repeated key.
bool index_file(std::span<const std::uint8_t> file, const char* name, std::map<FrameKey, std::size_t>& idx,
                std::string& error) {
    if (file.size() % kCaduBytes != 0) {
        error = std::string(name) + ": " + std::to_string(file.size()) + " bytes is not a whole number of " +
                std::to_string(kCaduBytes) + "-byte CADUs";
        return false;
    }
    for (std::size_t k = 0; k < file.size() / kCaduBytes; ++k) {
        const FrameKey key = frame_key(cadu_at(file, k));
        if (!idx.emplace(key, k).second) {
            error = std::string(name) + ": frames " + std::to_string(idx.at(key)) + " and " +
                    std::to_string(k) + " both carry " + describe(key);
            return false;
        }
    }
    return true;
}

}  // namespace

FrameKey frame_key(std::span<const std::uint8_t, kCaduBytes> cadu) {
    return FrameKey{
        .vcid = static_cast<std::uint8_t>(cadu[5] & 0x3FU),
        .counter = (static_cast<std::uint32_t>(cadu[6]) << 16U) |
                   (static_cast<std::uint32_t>(cadu[7]) << 8U) | cadu[8],
    };
}

bool diff_cadus(std::span<const std::uint8_t> ours, std::span<const std::uint8_t> ref, CaduDiff& out,
                std::string& error) {
    out = CaduDiff{};
    std::map<FrameKey, std::size_t> ours_idx;
    std::map<FrameKey, std::size_t> ref_idx;
    if (!index_file(ours, "ours", ours_idx, error) || !index_file(ref, "satdump", ref_idx, error)) {
        return false;
    }
    out.ours = ours.size() / kCaduBytes;
    out.ref = ref.size() / kCaduBytes;

    for (std::size_t k = 0; k < out.ours; ++k) {
        const Cadu a = cadu_at(ours, k);
        const FrameKey key = frame_key(a);
        const auto it = ref_idx.find(key);
        if (it == ref_idx.end()) {
            out.only_ours.push_back(key);
            continue;
        }
        ++out.common;
        const Cadu b = cadu_at(ref, it->second);
        bool asm_differs = false;
        std::size_t data_bytes = 0;
        std::size_t parity_bytes = 0;
        for (std::size_t i = 0; i < kCaduBytes; ++i) {
            const auto x = static_cast<std::uint8_t>(a[i] ^ b[i]);
            if (x == 0) {
                continue;
            }
            if (i < kAsmEnd) {
                asm_differs = true;
            } else if (i < kRsDataEnd) {
                ++data_bytes;
                out.data_bits_differ += static_cast<std::size_t>(std::popcount(x));
                if (!out.first) {
                    out.first = Divergence{.key = key,
                                           .ours_frame = k,
                                           .ref_frame = it->second,
                                           .byte = i,
                                           .bit = std::countl_zero(x)};
                }
            } else {
                ++parity_bytes;
            }
        }
        out.asm_frames_differ += asm_differs ? 1 : 0;
        out.data_frames_differ += data_bytes != 0 ? 1 : 0;
        out.data_bytes_differ += data_bytes;
        out.parity_frames_differ += parity_bytes != 0 ? 1 : 0;
        out.parity_bytes_differ += parity_bytes;
    }
    for (std::size_t k = 0; k < out.ref; ++k) {
        const FrameKey key = frame_key(cadu_at(ref, k));
        if (!ours_idx.contains(key)) {
            out.only_ref.push_back(key);
        }
    }
    return true;
}

}  // namespace gs
