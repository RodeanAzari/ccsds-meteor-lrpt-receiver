// gs-image: MSU-MR images from gs-rx's space packets (buildplan §4, optional image step).
//
//   gs-image PACKETS OUTDIR
//
// PACKETS is gs-rx's packets.bin (packets back to back, each 6 + length field + 1 bytes). Decodes the MSU-MR
// segments (gs/msumr.hpp: SatDump's placement rules, docs/signal-spec.md) and writes OUTDIR/MSU-MR-N.png, one
// 8-bit greyscale PNG per channel that has data, N = 1-6 as SatDump names them. Prints key=value lines:
// packets read, then per channel the segments placed and the image rows. Exit 0: at least one image written;
// 1: none (no MSU-MR data) or a write failed; 2: bad arguments, unreadable input or a partial packet at the
// end.
#include <zlib.h>

#include <array>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <span>
#include <string>
#include <system_error>
#include <vector>

#include "gs/msumr.hpp"

namespace {

void put_u32(std::vector<std::uint8_t>& out, std::uint32_t v) {  // PNG integers are big-endian
    for (int s = 24; s >= 0; s -= 8) {
        out.push_back(static_cast<std::uint8_t>(v >> static_cast<unsigned>(s)));
    }
}

void put_chunk(std::vector<std::uint8_t>& out, const char* type, std::span<const std::uint8_t> data) {
    put_u32(out, static_cast<std::uint32_t>(data.size()));
    const std::size_t start = out.size();
    out.insert(out.end(), type, type + 4);
    out.insert(out.end(), data.begin(), data.end());
    const std::span<const std::uint8_t> crc_over(out.data() + start, out.size() - start);  // type + data
    put_u32(out, static_cast<std::uint32_t>(crc32(0, crc_over.data(), static_cast<uInt>(crc_over.size()))));
}

// 8-bit greyscale PNG (PNG spec: colour type 0, filter 0 on every row, one zlib stream in one IDAT).
bool write_png(const std::filesystem::path& path, const gs::msumr::Image& img) {
    std::vector<std::uint8_t> raw;
    raw.reserve(img.rows * (gs::msumr::kWidth + 1));
    for (std::size_t r = 0; r < img.rows; ++r) {
        raw.push_back(0);
        const auto* row = img.pixels.data() + (r * gs::msumr::kWidth);
        raw.insert(raw.end(), row, row + gs::msumr::kWidth);
    }
    uLongf zlen = compressBound(static_cast<uLong>(raw.size()));
    std::vector<std::uint8_t> z(zlen);
    if (compress2(z.data(), &zlen, raw.data(), static_cast<uLong>(raw.size()), Z_BEST_COMPRESSION) != Z_OK) {
        return false;
    }
    z.resize(zlen);
    std::vector<std::uint8_t> png = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    std::vector<std::uint8_t> ihdr;
    put_u32(ihdr, static_cast<std::uint32_t>(gs::msumr::kWidth));
    put_u32(ihdr, static_cast<std::uint32_t>(img.rows));
    ihdr.insert(ihdr.end(), {8, 0, 0, 0, 0});  // bit depth 8, greyscale, deflate, filter 0, no interlace
    put_chunk(png, "IHDR", ihdr);
    put_chunk(png, "IDAT", z);
    put_chunk(png, "IEND", {});
    std::ofstream f(path, std::ios::binary);
    f.write(reinterpret_cast<const char*>(png.data()), static_cast<std::streamsize>(png.size()));
    return static_cast<bool>(f.flush());
}

}  // namespace

int main(int argc, char** argv) {
    const std::span<char*> args(argv, static_cast<std::size_t>(argc));
    if (args.size() != 3) {
        (void)std::fputs("usage: gs-image PACKETS OUTDIR\n", stderr);
        return 2;
    }
    std::ifstream in(args[1], std::ios::binary);
    if (!in) {
        (void)std::fprintf(stderr, "gs-image: cannot read %s\n", args[1]);
        return 2;
    }
    const std::vector<std::uint8_t> blob{std::istreambuf_iterator<char>(in),
                                         std::istreambuf_iterator<char>()};
    gs::msumr::Reader reader;
    std::size_t packets = 0;
    for (std::size_t pos = 0; pos < blob.size();) {
        const std::size_t n =
            blob.size() - pos >= 6 ? 6 + ((std::size_t{blob[pos + 4]} << 8U) | blob[pos + 5]) + 1 : 7;
        if (blob.size() - pos < n) {
            (void)std::fprintf(stderr, "gs-image: %s: a partial packet at byte %zu\n", args[1], pos);
            return 2;
        }
        reader.add(std::span<const std::uint8_t>(blob).subspan(pos, n));
        pos += n;
        ++packets;
    }
    std::error_code ec;
    const std::filesystem::path dir(args[2]);
    std::filesystem::create_directories(dir, ec);
    std::string s = "packets=" + std::to_string(packets) + "\n";
    int written = 0;
    bool failed = false;
    for (int ch = 0; ch < gs::msumr::kChannels; ++ch) {
        const auto img = reader.image(ch);
        const std::string name = "MSU-MR-" + std::to_string(ch + 1);
        s += "ch" + std::to_string(ch + 1) + "_segments=" + std::to_string(reader.segments(ch)) + "\n";
        if (!img) {
            (void)std::fprintf(stderr, "gs-image: channel %d spans more than %zu rows; not written\n", ch + 1,
                               gs::msumr::kMaxRows);
            failed = true;
            continue;
        }
        s += "ch" + std::to_string(ch + 1) + "_rows=" + std::to_string(img->rows) + "\n";
        if (img->rows == 0) {
            continue;
        }
        if (!write_png(dir / (name + ".png"), *img)) {
            (void)std::fprintf(stderr, "gs-image: cannot write %s\n", (dir / (name + ".png")).c_str());
            failed = true;
            continue;
        }
        ++written;
    }
    (void)std::fputs(s.c_str(), stdout);
    return written > 0 && !failed ? 0 : 1;
}
