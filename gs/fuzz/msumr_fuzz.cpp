// libFuzzer target for gs-image's MSU-MR decoder (gs/msumr.hpp): any bytes, read as packets back to back as
// in packets.bin (6 + length field + 1 each; a partial packet at the end is fed as it is). Beyond ASan/UBSan
// findings it checks what gs-image relies on: a segment decodes to at most 14 MCUs; a channel never holds
// more segments than packets were fed; every extent is whole scans (multiples of 14); image() returns 8 rows
// of 1,568 pixels per scan of the extent.
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <span>

#include "gs/msumr.hpp"

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    namespace m = gs::msumr;
    const std::span<const std::uint8_t> in(data, size);
    // The segment parser alone, on the whole input as one data field.
    std::array<std::array<std::int32_t, 64>, m::kMcus> coef{};
    if (m::decode_coefficients(in, coef) > m::kMcus) {
        std::abort();
    }
    (void)m::decode_segment(in);

    m::Reader reader;
    std::size_t packets = 0;
    for (std::size_t pos = 0; pos < size; ++packets) {
        const std::size_t n = size - pos >= 6 ? 6 + ((std::size_t{in[pos + 4]} << 8U) | in[pos + 5]) + 1 : 7;
        const std::size_t take = n < size - pos ? n : size - pos;
        reader.add(in.subspan(pos, take));
        pos += take;
    }
    for (int ch = 0; ch < m::kChannels; ++ch) {
        if (reader.segments(ch) > packets) {
            std::abort();
        }
        const auto [first, end] = reader.extent(ch);
        if (first % m::kMcus != 0 || end % m::kMcus != 0) {
            std::abort();
        }
        // Images are built only up to 1,024 rows: larger ones (up to 18 MB under ASan) slow the run a
        // hundredfold, and their code path is the same.
        const std::size_t rows = std::size_t{static_cast<std::uint32_t>(end - first)} / m::kMcus * 8;
        if (rows > 1024) {
            continue;
        }
        const auto img = reader.image(ch);
        if (!img || img->rows != rows || img->pixels.size() != rows * m::kWidth) {
            std::abort();
        }
    }
    return 0;
}
