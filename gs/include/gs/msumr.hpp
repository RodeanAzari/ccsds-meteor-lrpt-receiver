// MSU-MR images from space packets (buildplan §4, optional image step): gs-image's decoder.
// docs/signal-spec.md "MSU-MR image packets" is the spec (the installed SatDump build, b79af48, quirks
// included); the golden model is model/msumr.py, and gs/tests/msumr_test.cpp replays its vectors. Written
// from that spec and ITU-T T.81, not from SatDump's code (GPL-3; this repository is MIT). Offline tool:
// segments are kept per channel until the images are built, so the reader allocates as it goes.
#ifndef GS_MSUMR_HPP
#define GS_MSUMR_HPP

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <span>
#include <utility>
#include <vector>

namespace gs::msumr {

inline constexpr int kChannels = 6;
inline constexpr std::uint16_t kFirstApid = 64;  // APIDs 64-69: channels 1-6
inline constexpr std::size_t kMcus = 14;         // MCUs (8 x 8 blocks) per segment
inline constexpr std::size_t kSegWidth = kMcus * 8;
inline constexpr std::size_t kWidth = kMcus * kSegWidth;  // 1,568 pixels: 14 segments per scan
inline constexpr std::uint32_t kPacketsPerScan = 43;      // 14 segments x 3 channels + 1 telemetry
inline constexpr std::uint32_t kSeqMod = 1U << 14U;
inline constexpr std::uint32_t kMaxSpan =
    20000;  // a segment whose id would stretch a channel further is dropped
inline constexpr std::uint32_t kUnset = 0xFFFFFFFFU;
// image() refuses more rows (not a SatDump rule): the most one channel's span allows (kMaxSpan ids, plus the
// extent's rounding and shift). A real pass is about 4,500.
inline constexpr std::size_t kMaxRows = ((kMaxSpan / kMcus) + 3) * 8;

// T.81 Table K.1 scaled by the quality factor, in 32-bit float as SatDump computes it; natural order.
std::array<std::int32_t, 64> quant_table(std::uint8_t qf);

namespace detail {
// NOLINTBEGIN(cppcoreguidelines-pro-bounds-constant-array-index)
constexpr std::array<std::uint8_t, 64> make_zigzag() {
    std::array<std::uint8_t, 64> out{};
    std::size_t k = 0;
    for (int d = 0; d < 15; ++d) {  // anti-diagonals r + c = d, alternating direction
        for (int i = 0; i <= d; ++i) {
            const int r = (d % 2) != 0 ? i : d - i;
            const int c = d - r;
            if (r < 8 && c < 8) {
                out[k++] = static_cast<std::uint8_t>((r * 8) + c);
            }
        }
    }
    return out;
}
// NOLINTEND(cppcoreguidelines-pro-bounds-constant-array-index)
}  // namespace detail

// T.81 Figure A.6: natural (row-major) position of the k-th coefficient in zigzag order.
inline constexpr std::array<std::uint8_t, 64> kZigzag = detail::make_zigzag();

// Entropy-coded data -> quantized coefficients per MCU (natural order). Returns how many MCUs decoded: 0
// means the segment is invalid, fewer than 14 that decoding stopped there and the rest stay 0.
std::size_t decode_coefficients(std::span<const std::uint8_t> data,
                                std::array<std::array<std::int32_t, 64>, kMcus>& coef);

// The fixed-point IDCT (Wang 1984, as in Go's image/jpeg): dequantized coefficients, natural order -> samples
// before the +128 level shift.
std::array<std::int64_t, 64> idct(const std::array<std::int64_t, 64>& coef);

struct Segment {
    std::uint8_t mcun = 0;                           // first MCU's number: 0, 14, ..., 182
    std::array<std::uint8_t, 8 * kSegWidth> pixels;  // 8 rows x 112, row-major
};

// A packet's data field (after the 6-byte primary header) -> its segment, or nothing if SatDump drops it.
std::optional<Segment> decode_segment(std::span<const std::uint8_t> data);

struct Image {
    std::size_t rows = 0;
    std::vector<std::uint8_t> pixels;  // rows x kWidth, row-major
};

// Places each channel's segments by sequence count, then builds all channels on one shared extent
// (signal-spec.md "Placing segments", "Image extent").
class Reader {
  public:
    // One space packet, primary header included. Packets of other APIDs, too short or not decodable are
    // ignored, as SatDump ignores them.
    void add(std::span<const std::uint8_t> packet);
    // (first id, end id) of the channel's image (0-5), multiples of 14: scans from first up to end.
    [[nodiscard]] std::pair<std::uint32_t, std::uint32_t> extent(int channel) const;
    // 0 rows when the channel had no segment; nothing if the extent is over kMaxRows rows (only crafted
    // input gets there: SatDump caps each channel's span at kMaxSpan ids, but not the gap between channels).
    [[nodiscard]] std::optional<Image> image(int channel) const;
    [[nodiscard]] std::size_t segments(int channel) const;

  private:
    struct Channel {
        std::map<std::uint32_t, Segment> segments;
        std::uint32_t first = kUnset;
        std::uint32_t last = 0;
        std::uint32_t rollover = 0;
        std::uint32_t last_seq = 0;
        std::uint32_t offset = kUnset;  // unset: no valid segment yet
    };
    std::array<Channel, kChannels> ch_;
};

}  // namespace gs::msumr

#endif  // GS_MSUMR_HPP
