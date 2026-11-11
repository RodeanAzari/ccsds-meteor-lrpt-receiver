// gs-view's screen (gs/view.hpp) from hand-written snapshots.
//
// Why it matters: an operator watching a pass reads lock state, FER and rates off this screen. Each figure
// must be the one ADR 0016 defines (FER = RS-failed / CADU packets; rate over two distinct snapshots), a
// missing or garbled value must show as "-" rather than a made-up 0, and no board stats must say so, not show
// "searching".
#include "gs/view.hpp"

#include <gtest/gtest.h>

#include <string>

namespace {

bool has(const std::string& screen, const std::string& text) {
    return screen.find(text) != std::string::npos;
}

TEST(View, ParseKeepsKeyValueLinesOnly) {
    const gs::Status s = gs::parse_status("a=1\nnoise\nb=x=y\n\nc=\n");
    EXPECT_EQ(s.size(), 3U);
    EXPECT_EQ(s.at("b"), "x=y");
    EXPECT_EQ(s.at("c"), "");
    EXPECT_EQ(gs::status_u64(s, "a"), 1U);
    EXPECT_FALSE(gs::status_u64(s, "b").has_value());
    EXPECT_FALSE(gs::status_u64(s, "c").has_value());
    EXPECT_FALSE(gs::status_u64(s, "missing").has_value());
}

TEST(View, NoStateMeansNoStatus) {
    EXPECT_TRUE(has(gs::render(gs::parse_status("datagrams=4\n"), nullptr), "no status from gs-rx"));
}

TEST(View, BoardLine) {
    const std::string none = gs::render(gs::parse_status("state=running\n"), nullptr);
    EXPECT_TRUE(has(none, "no stats packet yet"));
    EXPECT_FALSE(has(none, "searching"));
    const std::string locked =
        gs::render(gs::parse_status(
                       "state=running\nboard.fs_locked=1\nboard.nco_word=633410048\nboard.mac_restarts=14\n"),
                   nullptr);
    EXPECT_TRUE(has(locked, "sync LOCKED"));
    EXPECT_TRUE(has(locked, "NCO 0x25C11200"));
    EXPECT_TRUE(has(locked, "MAC restarts 14"));
    EXPECT_TRUE(
        has(gs::render(gs::parse_status("state=running\nboard.fs_locked=0\n"), nullptr), "sync searching"));
}

TEST(View, FerIsRsFailedOverCaduPackets) {
    const auto s =
        gs::parse_status("state=running\ncadu_packets=300\ncadus_rs_failed=3\nrs_symbols_corrected=150\n");
    const std::string screen = gs::render(s, nullptr);
    EXPECT_TRUE(has(screen, "FER 1.000 %"));
    EXPECT_TRUE(has(screen, "(0.50 per CADU)"));
    // Nothing received yet: no FER, not 0 %.
    EXPECT_TRUE(
        has(gs::render(gs::parse_status("state=running\ncadu_packets=0\ncadus_rs_failed=0\n"), nullptr),
            "FER -   rate"));
}

TEST(View, RateFromTwoSnapshots) {
    const auto a = gs::parse_status("state=running\nelapsed_ms=1000\ncadu_packets=10\n");
    const auto b = gs::parse_status("state=running\nelapsed_ms=3000\ncadu_packets=28\n");
    EXPECT_TRUE(has(gs::render(b, &a), "rate 9.0 /s"));
    EXPECT_TRUE(has(gs::render(b, nullptr), "rate -\n"));
    EXPECT_TRUE(has(gs::render(b, &b), "rate -\n"));  // same snapshot: no time between them
    EXPECT_TRUE(has(gs::render(a, &b), "rate -\n"));  // backwards (a restarted gs-rx): no rate
}

TEST(View, GarbledValuesShowAsDash) {
    const std::string screen =
        gs::render(gs::parse_status("state=final\nelapsed_ms=2500\ndatagrams=12x\ncadu_packets=\n"), nullptr);
    EXPECT_TRUE(has(screen, "[final]  elapsed 2.5 s"));
    EXPECT_TRUE(has(screen, "datagrams -"));
    EXPECT_TRUE(has(screen, "received -"));
}

}  // namespace
