// gs-rx's report as key=value lines, one per line: its final summary (stdout, gs-rx.txt) and its live
// snapshot for gs-view (status.txt, ADR 0016). Formatted into a fixed buffer: no allocation, so the
// processing thread can write a snapshot mid-pass (CLAUDE.md §5.3).
#ifndef GS_STATUS_HPP
#define GS_STATUS_HPP

#include <array>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <string_view>

#include "gs/board_packets.hpp"
#include "gs/rx_processor.hpp"
#include "gs/space_packets.hpp"

namespace gs {

class StatusText {
  public:
    static constexpr std::size_t kCapacity =
        8192;  // ~50 lines of < 40 bytes; overflow is reported, never cut

    void add(std::string_view key, std::string_view value) {
        if (n_ + key.size() + 1 + value.size() + 1 > buf_.size()) {
            overflowed_ = true;
            return;
        }
        put(key);
        put("=");
        put(value);
        put("\n");
    }
    void add(std::string_view key, std::uint64_t value) {
        std::array<char, 24> digits{};
        const auto r = std::to_chars(digits.data(), digits.data() + digits.size(), value);
        add(key, std::string_view(digits.data(), static_cast<std::size_t>(r.ptr - digits.data())));
    }
    void clear() {
        n_ = 0;
        overflowed_ = false;
    }
    [[nodiscard]] std::string_view view() const { return {buf_.data(), n_}; }
    [[nodiscard]] bool overflowed() const { return overflowed_; }

  private:
    void put(std::string_view s) {
        for (const char ch : s) {
            buf_.at(n_++) = ch;
        }
    }
    std::array<char, kCapacity> buf_{};
    std::size_t n_ = 0;
    bool overflowed_ = false;
};

// Every counter gs-rx keeps, then the board's latest stats packet as board.<field> (if one arrived).
inline void add_counts(StatusText& t, const RxCounts& c, std::uint64_t ring_full, const DemuxCounts& d,
                       const StatsPacket* board) {
    t.add("datagrams", c.datagrams);
    t.add("ring_full", ring_full);
    t.add("cadu_packets", c.cadu_packets);
    t.add("cadus_good", c.cadus_good);
    t.add("cadus_rs_failed", c.cadus_rs_failed);
    t.add("cadu_seq_missing", c.cadu_seq_missing);
    t.add("cadu_seq_late", c.cadu_seq_late);
    t.add("rs_symbols_corrected", c.rs_symbols_corrected);
    t.add("asm_bit_errors", c.asm_bit_errors);
    t.add("stats_packets", c.stats_packets);
    t.add("malformed", c.malformed);
    t.add("demux_cadus", d.cadus);
    t.add("demux_other_vcid", d.other_vcid);
    t.add("demux_gaps", d.gaps);
    t.add("packets", d.packets);
    t.add("dropped_gap", d.dropped_gap);
    t.add("dropped_length", d.dropped_length);
    t.add("bad_pointer", d.bad_pointer);
    t.add("dropped_pointer", d.dropped_pointer);
    if (board != nullptr) {
        for (std::size_t k = 0; k < board->known; ++k) {
            std::array<char, 40> key{};
            const std::string_view name = kStatsFieldNames.at(k);
            const std::string_view prefix = "board.";
            std::size_t n = 0;
            for (const char ch : prefix) {
                key.at(n++) = ch;
            }
            for (const char ch : name) {
                key.at(n++) = ch;
            }
            t.add(std::string_view(key.data(), n), board->fields.at(k));
        }
    }
}

}  // namespace gs

#endif  // GS_STATUS_HPP
