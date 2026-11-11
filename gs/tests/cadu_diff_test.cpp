// gs-diff's comparison (gs/cadu_diff.hpp) on hand-built CADU files.
//
// Why it matters: gs-diff is Phase F's and the real pass's acceptance test (buildplan §8.5). It must fail on
// any data-byte difference in a frame both sides decoded, and only there: SatDump writes the ASM and the RS
// parity bytes as received (docs/signal-spec.md "What gs-diff can compare"), so a test that failed on those
// would fail every real pass. Frames are matched by (VCID, VCDU counter) from the signal-spec byte map (VCID
// = byte 5 bits 5-0, counter = bytes 6-8), because either side can lack frames the other has.
#include "gs/cadu_diff.hpp"

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <vector>

namespace {

using Bytes = std::vector<std::uint8_t>;

// A CADU per the signal-spec byte map; the fill depends on the key so that frames differ from each other.
Bytes cadu(std::uint8_t byte5, std::uint32_t counter) {
    Bytes c(gs::kCaduBytes);
    for (std::size_t i = 0; i < c.size(); ++i) {
        c[i] = static_cast<std::uint8_t>((i * 7U) + (std::size_t{counter} * 13U) + byte5);
    }
    c[0] = 0x1A;
    c[1] = 0xCF;
    c[2] = 0xFC;
    c[3] = 0x1D;
    c[4] = 0x40;
    c[5] = byte5;
    c[6] = static_cast<std::uint8_t>(counter >> 16U);
    c[7] = static_cast<std::uint8_t>(counter >> 8U);
    c[8] = static_cast<std::uint8_t>(counter);
    return c;
}

Bytes cat(const std::vector<Bytes>& frames) {
    Bytes out;
    for (const Bytes& f : frames) {
        out.insert(out.end(), f.begin(), f.end());
    }
    return out;
}

gs::CaduDiff run(const Bytes& ours, const Bytes& ref) {
    gs::CaduDiff d;
    std::string err;
    EXPECT_TRUE(gs::diff_cadus(ours, ref, d, err)) << err;
    return d;
}

std::vector<gs::FrameKey> k(std::initializer_list<std::pair<int, int>> v) {
    std::vector<gs::FrameKey> out;
    for (const auto& [vc, n] : v) {
        out.push_back({static_cast<std::uint8_t>(vc), static_cast<std::uint32_t>(n)});
    }
    return out;
}

TEST(CaduDiff, IdenticalStreamsPass) {
    const Bytes f = cat({cadu(5, 100), cadu(5, 101), cadu(37, 7), cadu(5, 102)});
    const gs::CaduDiff d = run(f, f);
    EXPECT_TRUE(d.passed());
    EXPECT_EQ(d.ours, 4U);
    EXPECT_EQ(d.ref, 4U);
    EXPECT_EQ(d.common, 4U);
    EXPECT_EQ(d.data_frames_differ + d.asm_frames_differ + d.parity_frames_differ, 0U);
    EXPECT_FALSE(d.first.has_value());
}

// SatDump's .cadu keeps channel errors in the ASM and in the parity bytes: counted, never a failure.
TEST(CaduDiff, AsmAndParityDifferencesAreCountedButPass) {
    Bytes a = cadu(5, 1);
    Bytes b = cadu(5, 2);
    const Bytes ours = cat({a, b});
    a[3] ^= 0x01U;     // last ASM byte
    b[896] ^= 0x80U;   // first parity byte
    b[1023] ^= 0x0FU;  // last parity byte
    const gs::CaduDiff d = run(ours, cat({a, b}));
    EXPECT_TRUE(d.passed());
    EXPECT_EQ(d.asm_frames_differ, 1U);
    EXPECT_EQ(d.parity_frames_differ, 1U);
    EXPECT_EQ(d.parity_bytes_differ, 2U);
    EXPECT_EQ(d.data_frames_differ, 0U);
}

// The data bytes are 4-895, both ends included; the first divergence names the byte and the bit (0 = MSB).
TEST(CaduDiff, DataByteAtEitherEndFailsAndIsLocated) {
    for (const auto& [byte, mask, bit] :
         {std::tuple{4U, 0x80U, 0}, std::tuple{895U, 0x01U, 7}, std::tuple{200U, 0x14U, 3}}) {
        const Bytes ours = cat({cadu(5, 10), cadu(5, 11)});
        Bytes b = cadu(5, 11);
        b[byte] ^= static_cast<std::uint8_t>(mask);
        const gs::CaduDiff d = run(ours, cat({cadu(5, 10), b}));
        EXPECT_FALSE(d.passed()) << byte;
        EXPECT_EQ(d.data_frames_differ, 1U);
        EXPECT_EQ(d.data_bytes_differ, 1U);
        EXPECT_EQ(d.data_bits_differ, static_cast<std::size_t>(__builtin_popcount(mask)));
        ASSERT_TRUE(d.first.has_value());
        EXPECT_EQ(d.first->key, (gs::FrameKey{5, 11}));
        EXPECT_EQ(d.first->ours_frame, 1U);
        EXPECT_EQ(d.first->ref_frame, 1U);
        EXPECT_EQ(d.first->byte, byte);
        EXPECT_EQ(d.first->bit, bit);
    }
}

// Either side may lack frames, and SatDump's file need not be in our order: frames are matched by key, and
// the ones only one side has are listed in that side's file order without failing the test.
TEST(CaduDiff, MissingAndReorderedFramesAreMatchedByKey) {
    const Bytes ours = cat({cadu(5, 1), cadu(5, 2), cadu(5, 4), cadu(5, 5), cadu(5, 9)});
    const Bytes ref = cat({cadu(5, 3), cadu(5, 5), cadu(5, 4), cadu(5, 1), cadu(5, 8)});
    const gs::CaduDiff d = run(ours, ref);
    EXPECT_TRUE(d.passed());
    EXPECT_EQ(d.common, 3U);
    EXPECT_EQ(d.only_ours, k({{5, 2}, {5, 9}}));
    EXPECT_EQ(d.only_ref, k({{5, 3}, {5, 8}}));
}

// The first divergence is the first in our file's order, with each file's own index.
TEST(CaduDiff, FirstDivergenceFollowsOurOrder) {
    Bytes a = cadu(5, 1);
    Bytes b = cadu(5, 2);
    const Bytes ours = cat({b, a});
    a[10] ^= 1U;
    b[500] ^= 1U;
    const gs::CaduDiff d = run(ours, cat({a, b}));
    EXPECT_EQ(d.data_frames_differ, 2U);
    ASSERT_TRUE(d.first.has_value());
    EXPECT_EQ(d.first->key, (gs::FrameKey{5, 2}));
    EXPECT_EQ(d.first->ours_frame, 0U);
    EXPECT_EQ(d.first->ref_frame, 1U);
    EXPECT_EQ(d.first->byte, 500U);
}

// VCID is the low 6 bits of byte 5 (the top two are spacecraft ID); the counter is all 24 bits of 6-8.
TEST(CaduDiff, KeyUsesSixBitVcidAndTwentyFourBitCounter) {
    // Same counter, VCIDs 5 and 37 (differ in bit 5): two frames. Spacecraft ID bits differ: same frame.
    EXPECT_EQ(gs::frame_key(std::span<const std::uint8_t, 1024>(cadu(0xC5, 3))), (gs::FrameKey{5, 3}));
    const gs::CaduDiff v = run(cat({cadu(5, 3), cadu(37, 3)}), cat({cadu(37, 3)}));
    EXPECT_EQ(v.only_ours, k({{5, 3}}));
    // Counters 0x000001 and 0x010001 differ only in byte 6: two frames.
    const gs::CaduDiff c = run(cat({cadu(5, 0x000001), cadu(5, 0x010001)}), cat({cadu(5, 0x010001)}));
    EXPECT_EQ(c.only_ours, k({{5, 1}}));
    EXPECT_EQ(c.common, 1U);
}

TEST(CaduDiff, NothingInCommonDoesNotPass) {
    EXPECT_FALSE(run(cat({cadu(5, 1)}), cat({cadu(5, 2)})).passed());
    EXPECT_FALSE(run({}, {}).passed());
}

TEST(CaduDiff, MalformedInputIsAnError) {
    gs::CaduDiff d;
    std::string err;
    Bytes partial = cat({cadu(5, 1)});
    partial.pop_back();
    EXPECT_FALSE(gs::diff_cadus(cat({cadu(5, 1)}), partial, d, err));
    EXPECT_NE(err.find("satdump"), std::string::npos) << err;
    // One key twice: which frame to compare would be a guess.
    err.clear();
    EXPECT_FALSE(gs::diff_cadus(cat({cadu(5, 1), cadu(5, 2), cadu(5, 1)}), cat({cadu(5, 1)}), d, err));
    EXPECT_NE(err.find("frames 0 and 2"), std::string::npos) << err;
}

}  // namespace
