// gs-image's MSU-MR decoder (gs/msumr.hpp).
//
// Two kinds of check. The building blocks against ITU-T T.81 itself (zigzag order, Huffman codes through a
// hand-built bit stream, the quantization scaling, the IDCT against a floating-point reference), so a fault
// there is found without trusting the model. Then the whole decoder against the golden model (model/msumr.py)
// on every scenario in gs/tests/data/msumr (written by scripts/gen_msumr_vectors.py): real packets of the
// 2026-11-21 pass, and those packets wrapped, started late, duplicated onto another channel, damaged, swapped
// and stretched, and a synthetic scan of edge cases. The model equals SatDump's images pixel for pixel
// (data/results/msumr_model.csv), so equal pixels here mean gs-image draws the image SatDump draws.
#include "gs/msumr.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <iterator>
#include <numbers>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace {

using Bytes = std::vector<std::uint8_t>;
namespace m = gs::msumr;

std::filesystem::path vector_dir() {
    return std::filesystem::path(GS_TEST_DATA_DIR) / "msumr";
}

Bytes read_file(const std::filesystem::path& p) {
    std::ifstream f(p, std::ios::binary);
    return {std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()};
}

// '0'/'1' string, MSB first, padded with 1s to a whole byte (T.81 F.1.2.3).
Bytes from_bits(std::string bits) {
    bits.append((8 - (bits.size() % 8)) % 8, '1');
    Bytes out(bits.size() / 8, 0);
    for (std::size_t k = 0; k < bits.size(); ++k) {
        out[k / 8] = static_cast<std::uint8_t>(out[k / 8] | ((bits[k] == '1' ? 1U : 0U) << (7 - (k % 8))));
    }
    return out;
}

// T.81 Figure A.6, read off the figure: the first and last rows of the zigzag path.
TEST(Msumr, ZigzagIsT81FigureA6) {
    const std::array<int, 10> head = {0, 1, 8, 16, 9, 2, 3, 10, 17, 24};
    const std::array<int, 6> tail = {61, 54, 47, 55, 62, 63};
    for (std::size_t k = 0; k < head.size(); ++k) {
        EXPECT_EQ(m::kZigzag[k], head[k]) << k;
    }
    for (std::size_t k = 0; k < tail.size(); ++k) {
        EXPECT_EQ(m::kZigzag[58 + k], tail[k]) << k;
    }
    EXPECT_EQ(std::set<int>(m::kZigzag.begin(), m::kZigzag.end()).size(), 64U);
}

// Quality-factor scaling (signal-spec.md): 50 gives T.81 Table K.1 itself; above 50 the table shrinks, 21-49
// it grows as 5000 / QF; nothing goes below 1. The QF 36 and 48 entries are ones where float32 and float64
// round differently, so a double-precision port fails them.
TEST(Msumr, QuantTableScaling) {
    const auto q50 = m::quant_table(50);
    EXPECT_EQ(q50[0], 16);
    EXPECT_EQ(q50[1], 11);
    EXPECT_EQ(q50[63], 99);
    EXPECT_EQ(m::quant_table(80)[0], 6);   // 16 * 0.4 + 0.5 -> 6
    EXPECT_EQ(m::quant_table(0)[0], 32);   // f = 200
    EXPECT_EQ(m::quant_table(20)[0], 26);  // 20 is not in 21-49: 200 - 40 = 160 -> 16 * 1.6 + 0.5
    EXPECT_EQ(m::quant_table(21)[0], 38);  // 5000 / 21 = 238.1 -> 16 * 2.381 + 0.5
    EXPECT_EQ(m::quant_table(36)[44], 112);
    EXPECT_EQ(m::quant_table(48)[14], 62);
    for (const std::uint8_t qf : std::initializer_list<std::uint8_t>{100, 101, 255}) {
        const auto q = m::quant_table(qf);
        EXPECT_TRUE(std::ranges::all_of(q, [](std::int32_t v) { return v == 1; })) << int{qf};
    }
}

// The T.81 baseline codes: DC category 0 is '00', category 1 '010'; AC EOB is '1010', (0,1) is '00'.
TEST(Msumr, DecodesHandBuiltStream) {
    // MCU 0: DC cat 1, bit '1' (+1); AC (0,1) bit '0' (-1); EOB. MCUs 1-13: DC cat 0 (DC stays 1); EOB.
    std::string bits =
        "010"
        "1"
        "00"
        "0"
        "1010";
    for (int k = 1; k < 14; ++k) {
        bits +=
            "00"
            "1010";
    }
    std::array<std::array<std::int32_t, 64>, m::kMcus> coef{};
    EXPECT_EQ(m::decode_coefficients(from_bits(bits), coef), m::kMcus);
    EXPECT_EQ(coef[0][0], 1);
    EXPECT_EQ(coef[0][1], -1);
    for (std::size_t k = 1; k < m::kMcus; ++k) {
        EXPECT_EQ(coef[k][0], 1) << k;  // DC is coded as a difference from the previous block
        EXPECT_TRUE(std::all_of(coef[k].begin() + 1, coef[k].end(), [](std::int32_t v) { return v == 0; }));
    }
}

// A stream that ends mid-segment: the MCUs before the end count, the rest stay 0; none at all is invalid.
TEST(Msumr, CutStreamKeepsWholeMcus) {
    std::string bits;
    for (int k = 0; k < 5; ++k) {
        bits +=
            "010"
            "1"
            "1010";  // DC +1 each time
    }
    std::array<std::array<std::int32_t, 64>, m::kMcus> coef{};
    EXPECT_EQ(m::decode_coefficients(from_bits(bits), coef), 5U);  // the padding cannot complete a sixth
    EXPECT_EQ(coef[4][0], 5);
    EXPECT_EQ(coef[5][0], 0);
    EXPECT_EQ(m::decode_coefficients({}, coef), 0U);
}

// A DC-only block is flat: (D * 2048 + 8192) >> 14 = D / 8 rounded half up.
TEST(Msumr, IdctDcOnlyIsExact) {
    for (const std::int64_t d : {0, 8, 80, -80, 4, -4, 1016, -1024, 8000}) {
        std::array<std::int64_t, 64> c{};
        c[0] = d;
        const auto out = m::idct(c);
        const auto want = static_cast<std::int64_t>(std::floor((static_cast<double>(d) / 8.0) + 0.5));
        EXPECT_TRUE(std::ranges::all_of(out, [&](std::int64_t v) { return v == want; })) << d;
    }
}

// Against the T.81 A.3.3 IDCT in double precision: the fixed-point version is within 1 everywhere.
TEST(Msumr, IdctMatchesFloatReference) {
    std::mt19937 rng(5);  // NOLINT(cert-msc32-c,cert-msc51-cpp): a fixed seed, so a failure reproduces
    std::uniform_int_distribution<int> val(-300, 300);
    std::uniform_int_distribution<int> pick(0, 4);
    for (int trial = 0; trial < 200; ++trial) {
        std::array<std::int64_t, 64> c{};
        for (auto& v : c) {
            v = pick(rng) == 0 ? val(rng) : 0;  // sparse, like real blocks; every row's AC sometimes all 0
        }
        c[0] = std::int64_t{val(rng)} * 8;
        const auto out = m::idct(c);
        for (int y = 0; y < 8; ++y) {
            for (int x = 0; x < 8; ++x) {
                double s = 0;
                for (int v = 0; v < 8; ++v) {
                    for (int u = 0; u < 8; ++u) {
                        const double cu = u == 0 ? std::numbers::sqrt2 / 2 : 1.0;
                        const double cv = v == 0 ? std::numbers::sqrt2 / 2 : 1.0;
                        s += cu * cv *
                             static_cast<double>(
                                 c[(static_cast<std::size_t>(v) * 8) + static_cast<std::size_t>(u)]) *
                             std::cos((2 * x + 1) * u * std::numbers::pi / 16) *
                             std::cos((2 * y + 1) * v * std::numbers::pi / 16);
                    }
                }
                const auto got =
                    static_cast<double>(out[(static_cast<std::size_t>(y) * 8) + static_cast<std::size_t>(x)]);
                ASSERT_LE(std::abs(got - (s / 4)), 1.0) << "trial " << trial << " (" << y << "," << x << ")";
            }
        }
    }
}

// The header fields SatDump checks (signal-spec.md segment header): each one wrong drops the segment.
TEST(Msumr, HeaderChecks) {
    Bytes ok(14, 0);
    ok[8] = 28;  // MCUN
    ok[11] = 0xFF;
    ok[12] = 0xF0;
    ok[13] = 50;
    std::string bits;
    for (int k = 0; k < 14; ++k) {
        bits +=
            "00"
            "1010";  // DC 0, EOB: a flat block of 128
    }
    const Bytes s = from_bits(bits);
    ok.insert(ok.end(), s.begin(), s.end());
    const auto seg = m::decode_segment(ok);
    ASSERT_TRUE(seg.has_value());
    EXPECT_EQ(seg->mcun, 28);
    EXPECT_TRUE(std::all_of(seg->pixels.begin(), seg->pixels.end(), [](std::uint8_t p) { return p == 128; }));
    for (const auto& [at, value] : std::vector<std::pair<std::size_t, std::uint8_t>>{
             {9, 1}, {10, 0x01}, {10, 0x08}, {11, 0xFE}, {12, 0xF1}}) {
        Bytes bad = ok;
        bad[at] = value;
        EXPECT_FALSE(m::decode_segment(bad).has_value()) << "byte " << at;
    }
    Bytes high = ok;
    high[10] = 0xF0;  // only the low nibble is checked
    EXPECT_TRUE(m::decode_segment(high).has_value());
    EXPECT_FALSE(m::decode_segment(std::span(ok).first(14)).has_value());  // header only
}

// --- golden-model vectors ---

std::vector<std::span<const std::uint8_t>> split_packets(const Bytes& b) {
    std::vector<std::span<const std::uint8_t>> out;
    std::size_t at = 0;
    while (at + 6 <= b.size()) {
        const std::size_t n = 6 + ((std::size_t{b[at + 4]} << 8U) | b[at + 5]) + 1;
        out.emplace_back(b.data() + at, n);
        at += n;
    }
    EXPECT_EQ(at, b.size()) << "packets file does not split into whole packets";
    return out;
}

class MsumrScenario : public ::testing::TestWithParam<std::string> {};

TEST_P(MsumrScenario, MatchesGoldenModel) {
    const std::string& name = GetParam();
    const Bytes packets = read_file(vector_dir() / (name + ".packets"));
    ASSERT_FALSE(packets.empty()) << name << ".packets missing or empty";
    m::Reader reader;
    for (const auto p : split_packets(packets)) {
        reader.add(p);
    }
    std::ifstream summary(vector_dir() / (name + ".summary"));
    ASSERT_TRUE(summary) << name << ".summary missing";
    int lines = 0;
    for (int ch = 0, number = 0; summary >> number; ++ch, ++lines) {
        std::uint32_t first = 0;
        std::uint32_t end = 0;
        std::size_t segments = 0;
        summary >> first >> end >> segments;
        ASSERT_EQ(number, ch + 1);
        EXPECT_EQ(reader.extent(ch), std::make_pair(first, end)) << name << " channel " << number;
        EXPECT_EQ(reader.segments(ch), segments) << name << " channel " << number;
    }
    EXPECT_EQ(lines, m::kChannels);

    const Bytes want = read_file(vector_dir() / (name + ".image"));
    if (want.empty()) {
        return;  // too large to commit (span); its extents and segment counts are checked above
    }
    std::size_t at = 0;
    for (int ch = 0; ch < m::kChannels; ++ch) {
        ASSERT_LE(at + 4, want.size());
        std::uint32_t rows = 0;
        for (int k = 3; k >= 0; --k) {
            rows = (rows << 8U) | want[at + static_cast<std::size_t>(k)];  // little-endian
        }
        at += 4;
        const auto img = reader.image(ch);
        ASSERT_TRUE(img.has_value());
        ASSERT_EQ(img->rows, rows) << name << " channel " << ch + 1;
        const std::size_t n = std::size_t{rows} * m::kWidth;
        ASSERT_LE(at + n, want.size());
        const auto diff = std::mismatch(img->pixels.begin(), img->pixels.end(),
                                        want.begin() + static_cast<std::ptrdiff_t>(at));
        EXPECT_TRUE(diff.first == img->pixels.end())
            << name << " channel " << ch + 1 << ": first different pixel at "
            << (diff.first - img->pixels.begin()) / static_cast<std::ptrdiff_t>(m::kWidth) << ","
            << (diff.first - img->pixels.begin()) % static_cast<std::ptrdiff_t>(m::kWidth);
        at += n;
    }
    EXPECT_EQ(at, want.size());
}

INSTANTIATE_TEST_SUITE_P(GoldenModel, MsumrScenario,
                         ::testing::Values("real", "edges", "wrap", "late_start", "tie", "corrupt", "swapped",
                                           "span"));

// Every scenario file on disk is in the list above (a new one must not go untested).
TEST(MsumrScenario, AllVectorFilesListed) {
    int n = 0;
    for (const auto& e : std::filesystem::directory_iterator(vector_dir())) {
        n += e.path().extension() == ".summary" ? 1 : 0;
    }
    EXPECT_EQ(n, 8);
}

// Packets that are not MSU-MR segments change nothing: other APIDs, and ones too short for a header.
TEST(Msumr, ReaderIgnoresOtherPackets) {
    m::Reader reader;
    const Bytes tiny = {0x00, 0x40, 0xC0, 0x00};                         // APID 64, but no length field
    const Bytes telemetry = {0x00, 0x46, 0xC0, 0x01, 0x00, 0x00, 0x00};  // APID 70
    reader.add(tiny);
    reader.add(telemetry);
    reader.add({});
    for (int ch = 0; ch < m::kChannels; ++ch) {
        EXPECT_EQ(reader.segments(ch), 0U);
        const auto img = reader.image(ch);
        ASSERT_TRUE(img.has_value());
        EXPECT_EQ(img->rows, 0U);
    }
}

}  // namespace
