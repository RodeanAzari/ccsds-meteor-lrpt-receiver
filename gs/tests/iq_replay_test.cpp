#include "gs/iq_replay.hpp"

#include <gtest/gtest.h>

#include <array>
#include <cstdint>
#include <vector>

namespace {

// fpga-eth-core's rx_stats harness (and our RTL ingest) read payload bytes 0-7 as a
// big-endian sequence; a little-endian host write would show as a sequence error on
// every packet.
TEST(BuildPacket, SequenceIsBigEndianInFirstEightBytes) {
    std::array<std::uint8_t, gs::kIqBytes> iq{};
    std::array<std::uint8_t, gs::kPacketBytes> pkt{};
    gs::build_packet(0x0102030405060708ULL, iq, pkt);
    const std::array<std::uint8_t, 8> want{1, 2, 3, 4, 5, 6, 7, 8};
    for (std::size_t i = 0; i < 8; ++i) EXPECT_EQ(pkt[i], want[i]) << "byte " << i;
}

// The RTL ingest subtracts 127.5 from raw cu8 and pairs bytes as (I, Q); any conversion
// or reordering on the host would break bit-exactness against the model.
TEST(BuildPacket, IqBytesCopiedUnchangedAndInOrder) {
    std::array<std::uint8_t, gs::kIqBytes> iq{};
    for (std::size_t i = 0; i < iq.size(); ++i) iq[i] = static_cast<std::uint8_t>(i * 7 + 3);
    std::array<std::uint8_t, gs::kPacketBytes> pkt{};
    gs::build_packet(0, iq, pkt);
    for (std::size_t i = 0; i < iq.size(); ++i) ASSERT_EQ(pkt[gs::kSeqBytes + i], iq[i]) << "byte " << i;
}

// One datagram must fit an untagged Ethernet frame's 1472-byte UDP payload, or the IP
// layer fragments it and fpga-eth-core's udp_rx drops fragments.
TEST(BuildPacket, FitsOneEthernetFrame) { EXPECT_LE(gs::kPacketBytes, 1472U); }

// Real time at 1.024 MS/s is exactly 500 us per 512-sample packet.
TEST(Deadline, RealTimePeriodIs500us) {
    EXPECT_EQ(gs::deadline_ns(0, 1'024'000, 1000), 0);
    EXPECT_EQ(gs::deadline_ns(1, 1'024'000, 1000), 500'000);
    EXPECT_EQ(gs::deadline_ns(4, 1'024'000, 4000), 500'000);  // 4x: four packets per 500 us
}

// Deadlines are computed from the packet index, not accumulated, so a 15-minute pass
// ends exactly on time (no per-packet rounding drift).
TEST(Deadline, NoDriftOverAFullPass) {
    const std::uint64_t packets = 15ULL * 60 * 2000;  // 15 min at 2000 packets/s
    EXPECT_EQ(gs::deadline_ns(packets, 1'024'000, 1000), 900LL * 1'000'000'000LL);
    // A rate where one period is not a whole number of ns: 512/3e6 s = 170666.67 ns.
    EXPECT_EQ(gs::deadline_ns(3'000'000, 3'000'000, 1000), 512LL * 1'000'000'000LL);
}

std::optional<gs::ReplayOptions> parse(std::vector<const char*> args, std::string& err) {
    args.insert(args.begin(), "gs-replay");
    return gs::parse_replay_args(static_cast<int>(args.size()), args.data(), err);
}

TEST(Args, DefaultsAreRealTimeToTheRxStatsGroup) {
    std::string err;
    const auto o = parse({"pass.cu8"}, err);
    ASSERT_TRUE(o) << err;
    EXPECT_EQ(o->file, "pass.cu8");
    EXPECT_EQ(o->dest_ip, "239.1.1.1");
    EXPECT_EQ(o->dest_port, 26400);
    EXPECT_EQ(o->sample_rate, 1'024'000U);
    EXPECT_EQ(o->speed_milli, 1000U);
}

TEST(Args, ParsesEveryOption) {
    std::string err;
    const auto o = parse({"--dest", "127.0.0.1:5000", "--speed", "2.5", "--rate", "256000", "--count",
                          "10", "--ttl", "4", "--iface", "10.0.0.2", "f.cu8"},
                         err);
    ASSERT_TRUE(o) << err;
    EXPECT_EQ(o->dest_ip, "127.0.0.1");
    EXPECT_EQ(o->dest_port, 5000);
    EXPECT_EQ(o->speed_milli, 2500U);
    EXPECT_EQ(o->sample_rate, 256'000U);
    EXPECT_EQ(o->max_packets, 10U);
    EXPECT_EQ(o->ttl, 4);
    EXPECT_EQ(o->iface_ip, "10.0.0.2");
    const auto fo = parse({"--flat-out", "f.cu8"}, err);
    ASSERT_TRUE(fo) << err;
    EXPECT_EQ(fo->speed_milli, 0U);
}

// A typo must stop the run, not silently replay at the wrong rate or to the wrong place.
TEST(Args, RejectsBadInput) {
    std::string err;
    EXPECT_FALSE(parse({}, err));
    EXPECT_FALSE(parse({"a.cu8", "b.cu8"}, err));
    EXPECT_FALSE(parse({"--speed", "0", "f.cu8"}, err));
    EXPECT_FALSE(parse({"--speed", "1.2345", "f.cu8"}, err));
    EXPECT_FALSE(parse({"--speed", "x", "f.cu8"}, err));
    EXPECT_FALSE(parse({"--dest", "127.0.0.1", "f.cu8"}, err));
    EXPECT_FALSE(parse({"--dest", "127.0.0.1:0", "f.cu8"}, err));
    EXPECT_FALSE(parse({"--rate", "1e6", "f.cu8"}, err));
    EXPECT_FALSE(parse({"--ttl", "0", "f.cu8"}, err));
    EXPECT_FALSE(parse({"--bogus", "f.cu8"}, err));
    EXPECT_FALSE(parse({"f.cu8", "--count"}, err));
}

}  // namespace
