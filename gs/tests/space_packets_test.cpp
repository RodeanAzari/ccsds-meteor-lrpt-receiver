// SpaceDemux against the golden model (model/space_packets.py `demux`, ADR 0015): every scenario in
// gs/tests/data/demux (written by scripts/gen_gs_vectors.py) must give the model's packets, byte for byte and
// in order, and the model's counters.
//
// Why it matters: these packets are what Phase F's definition of done compares with SatDump. On an unbroken
// stream the model equals SatDump's demultiplexer; on a damaged one it drops exactly the damaged packet. A
// C++ port that drifts from it either loses good packets or passes damaged ones, and the counters are how a
// pass report says so.
#include "gs/space_packets.hpp"

#include <gtest/gtest.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace {

using Bytes = std::vector<std::uint8_t>;
std::filesystem::path vector_dir() {
    return std::filesystem::path(GS_TEST_DATA_DIR) / "demux";
}

Bytes read_file(const std::filesystem::path& p) {
    std::ifstream f(p, std::ios::binary);
    return {std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()};
}

std::map<std::string, std::uint64_t> read_counts(const std::filesystem::path& p) {
    std::ifstream f(p);
    std::map<std::string, std::uint64_t> m;
    std::string k;
    std::uint64_t v = 0;
    while (f >> k >> v) {
        m[k] = v;
    }
    return m;
}

// Space packets are self-delimiting: 6-byte header, then length field + 1 bytes.
std::vector<Bytes> split_packets(const Bytes& b) {
    std::vector<Bytes> out;
    std::size_t at = 0;
    while (at + 6 <= b.size()) {
        const std::size_t n = 6 + ((std::size_t{b[at + 4]} << 8U) | b[at + 5]) + 1;
        out.emplace_back(b.begin() + static_cast<std::ptrdiff_t>(at),
                         b.begin() + static_cast<std::ptrdiff_t>(at + n));
        at += n;
    }
    EXPECT_EQ(at, b.size()) << "packets file does not split into whole packets";
    return out;
}

class Scenario : public ::testing::TestWithParam<std::string> {};

TEST_P(Scenario, MatchesGoldenModel) {
    const std::string& name = GetParam();
    const Bytes cadus = read_file(vector_dir() / (name + ".cadu"));
    ASSERT_FALSE(cadus.empty()) << name << ".cadu missing or empty";
    ASSERT_EQ(cadus.size() % gs::kCaduLen, 0U);
    const std::vector<Bytes> want = split_packets(read_file(vector_dir() / (name + ".packets")));
    auto counts = read_counts(vector_dir() / (name + ".counts"));
    ASSERT_EQ(counts.size(), 8U) << name << ".counts";

    auto demux = std::make_unique<gs::SpaceDemux>();  // 64 KB packet buffer: not on the stack
    std::vector<Bytes> got;
    for (std::size_t at = 0; at < cadus.size(); at += gs::kCaduLen) {
        demux->work(std::span<const std::uint8_t, gs::kCaduLen>(cadus.data() + at, gs::kCaduLen),
                    [&](std::span<const std::uint8_t> p) { got.emplace_back(p.begin(), p.end()); });
    }
    ASSERT_EQ(got.size(), want.size()) << name;
    for (std::size_t k = 0; k < got.size(); ++k) {
        ASSERT_EQ(got[k], want[k]) << name << ": packet " << k;
    }
    const gs::DemuxCounts& c = demux->counts();
    EXPECT_EQ(c.cadus, counts["cadus"]);
    EXPECT_EQ(c.other_vcid, counts["other_vcid"]);
    EXPECT_EQ(c.gaps, counts["gaps"]);
    EXPECT_EQ(c.packets, counts["packets"]);
    EXPECT_EQ(c.dropped_gap, counts["dropped_gap"]);
    EXPECT_EQ(c.dropped_length, counts["dropped_length"]);
    EXPECT_EQ(c.bad_pointer, counts["bad_pointer"]);
    EXPECT_EQ(c.dropped_pointer, counts["dropped_pointer"]);
}

INSTANTIATE_TEST_SUITE_P(GoldenModel, Scenario,
                         ::testing::Values("clean_small", "clean_large", "lost_cadu", "length_plus1",
                                           "length_minus1", "bad_pointer", "mixed_vcid", "split_headers",
                                           "wrap"));

// Every scenario file on disk is in the list above (a new one must not go untested).
TEST(Scenario, AllVectorFilesListed) {
    int n = 0;
    for (const auto& e : std::filesystem::directory_iterator(vector_dir())) {
        n += e.path().extension() == ".counts" ? 1 : 0;
    }
    EXPECT_EQ(n, 9);
}

}  // namespace
