// gs-rx's report formatter (gs/status.hpp): the final summary and the live snapshot gs-view reads (ADR 0016).
//
// Why it matters: gs-view, scripts and the loopback test parse these lines by key; a line cut short would be
// read as a wrong number, so a full buffer must be reported (overflowed) with no partial line written. The
// board's fields must carry their docs/protocol.md names (kStatsFieldNames), and only when a stats packet
// arrived.
#include "gs/status.hpp"

#include <gtest/gtest.h>

#include <string>

namespace {

TEST(StatusText, KeyValueLines) {
    gs::StatusText t;
    t.add("state", "running");
    t.add("zero", std::uint64_t{0});
    t.add("max", UINT64_MAX);
    EXPECT_EQ(t.view(), "state=running\nzero=0\nmax=18446744073709551615\n");
    EXPECT_FALSE(t.overflowed());
    t.clear();
    EXPECT_EQ(t.view(), "");
}

TEST(StatusText, FullBufferIsReportedAndNoLineIsCut) {
    gs::StatusText t;
    const std::string key(100, 'k');
    std::size_t lines = 0;
    while (!t.overflowed()) {
        t.add(key, std::uint64_t{1234567});
        ++lines;
    }
    const std::string_view v = t.view();
    ASSERT_FALSE(v.empty());
    EXPECT_EQ(v.back(), '\n');
    EXPECT_EQ(v.size(), (lines - 1) * (key.size() + 9));  // every line written whole; the last add refused
    EXPECT_LE(v.size(), gs::StatusText::kCapacity);
    // An exact fit is accepted.
    gs::StatusText exact;
    exact.add(std::string(gs::StatusText::kCapacity - 3, 'x'), "y");
    EXPECT_FALSE(exact.overflowed());
    EXPECT_EQ(exact.view().size(), gs::StatusText::kCapacity);
}

TEST(StatusText, BoardFieldsOnlyWithAStatsPacketAndByProtocolName) {
    gs::RxCounts c;
    c.cadu_packets = 7;
    c.rs_symbols_corrected = 12;
    gs::DemuxCounts d;
    d.packets = 3;
    gs::StatusText t;
    gs::add_counts(t, c, 5, d, nullptr);
    std::string v(t.view());
    EXPECT_NE(v.find("cadu_packets=7\n"), std::string::npos);
    EXPECT_NE(v.find("rs_symbols_corrected=12\n"), std::string::npos);
    EXPECT_NE(v.find("ring_full=5\n"), std::string::npos);
    EXPECT_NE(v.find("packets=3\n"), std::string::npos);
    EXPECT_EQ(v.find("board."), std::string::npos);

    gs::StatsPacket s;
    s.known = gs::kStatsFieldNames.size();
    for (std::size_t k = 0; k < s.known; ++k) {
        s.fields.at(k) = static_cast<std::uint32_t>(100 + k);
    }
    t.clear();
    gs::add_counts(t, c, 5, d, &s);
    v = std::string(t.view());
    EXPECT_NE(v.find("\nboard.ingest_ok=100\n"), std::string::npos);  // field 0
    EXPECT_NE(v.find("\nboard.fs_locked=119\n"), std::string::npos);  // field 19
    EXPECT_NE(v.find("\nboard.ctrl_bad=128\n"), std::string::npos);   // field 28, the last
    EXPECT_FALSE(t.overflowed());
    // A board that sent fewer fields: only those.
    s.known = 2;
    t.clear();
    gs::add_counts(t, c, 5, d, &s);
    v = std::string(t.view());
    EXPECT_NE(v.find("board.ingest_bad=101\n"), std::string::npos);
    EXPECT_EQ(v.find("board.ingest_gap"), std::string::npos);
}

}  // namespace
