#include "gs/view.hpp"

#include <array>
#include <charconv>
#include <cstdio>
#include <system_error>

namespace gs {

Status parse_status(std::string_view text) {
    Status s;
    while (!text.empty()) {
        const std::size_t eol = text.find('\n');
        const std::string_view line = text.substr(0, eol);
        text = eol == std::string_view::npos ? std::string_view{} : text.substr(eol + 1);
        if (const std::size_t eq = line.find('='); eq != std::string_view::npos) {
            s.insert_or_assign(std::string(line.substr(0, eq)), std::string(line.substr(eq + 1)));
        }
    }
    return s;
}

std::optional<std::uint64_t> status_u64(const Status& s, std::string_view key) {
    const auto it = s.find(key);
    if (it == s.end()) {
        return std::nullopt;
    }
    std::uint64_t v = 0;
    const std::string& t = it->second;
    const auto r = std::from_chars(t.data(), t.data() + t.size(), v);
    return r.ec == std::errc{} && r.ptr == t.data() + t.size() ? std::optional(v) : std::nullopt;
}

namespace {

std::string num(const Status& s, std::string_view key) {
    const auto v = status_u64(s, key);
    return v ? std::to_string(*v) : "-";
}

std::string fixed(double v, int decimals) {
    std::array<char, 32> b{};
    const int n =
        std::snprintf(b.data(), b.size(), "%.*f", decimals, v);  // NOLINT(cppcoreguidelines-pro-type-vararg)
    return {b.data(), static_cast<std::size_t>(n)};
}

std::string board_line(const Status& s) {
    const auto locked = status_u64(s, "board.fs_locked");
    if (!locked) {
        return "Board    no stats packet yet\n";
    }
    std::string nco = "-";
    if (const auto w = status_u64(s, "board.nco_word")) {
        std::array<char, 16> b{};
        const int n =
            std::snprintf(b.data(), b.size(), "0x%08llX",  // NOLINT(cppcoreguidelines-pro-type-vararg)
                          static_cast<unsigned long long>(*w));
        nco.assign(b.data(), static_cast<std::size_t>(n));
    }
    return "Board    sync " + std::string(*locked != 0 ? "LOCKED" : "searching") + "   CADUs sent " +
           num(s, "board.cadus_sent") + "   slips " + num(s, "board.fs_slips") + "   dropped peaks " +
           num(s, "board.fs_dropped") + "   NCO " + nco + "   MAC restarts " + num(s, "board.mac_restarts") +
           "\n";
}

}  // namespace

std::string render(const Status& now, const Status* prev) {
    const auto state = now.find("state");
    if (state == now.end()) {
        return "gs-view  no status from gs-rx\n";
    }
    std::string out;
    const auto ms = status_u64(now, "elapsed_ms");
    out += "gs-view  [" + state->second + "]  elapsed " +
           (ms ? fixed(static_cast<double>(*ms) / 1e3, 1) : "-") + " s\n";
    out += board_line(now);
    out += "Ingest   datagrams " + num(now, "datagrams") + "   gaps " + num(now, "board.ingest_gap") +
           "   lost " + num(now, "board.ingest_lost") + "   late " + num(now, "board.ingest_late") +
           "   ring full " + num(now, "ring_full") + "   malformed " + num(now, "malformed") + "\n";

    const auto packets = status_u64(now, "cadu_packets");
    const auto failed = status_u64(now, "cadus_rs_failed");
    std::string fer = "-";
    if (packets && failed && *packets > 0) {
        fer = fixed(100.0 * static_cast<double>(*failed) / static_cast<double>(*packets), 3) + " %";
    }
    std::string rate = "-";
    if (prev != nullptr) {
        const auto p0 = status_u64(*prev, "cadu_packets");
        const auto t0 = status_u64(*prev, "elapsed_ms");
        if (packets && p0 && ms && t0 && *ms > *t0 && *packets >= *p0) {
            rate =
                fixed(static_cast<double>(*packets - *p0) * 1e3 / static_cast<double>(*ms - *t0), 1) + " /s";
        }
    }
    out += "CADUs    received " + num(now, "cadu_packets") + "   good " + num(now, "cadus_good") +
           "   RS-failed " + num(now, "cadus_rs_failed") + "   missing " + num(now, "cadu_seq_missing") +
           "   FER " + fer + "   rate " + rate + "\n";

    std::string per = "-";
    const auto corrected = status_u64(now, "rs_symbols_corrected");
    if (corrected && packets && *packets > 0) {
        per = fixed(static_cast<double>(*corrected) / static_cast<double>(*packets), 2);
    }
    out += "FEC      RS symbols corrected " + num(now, "rs_symbols_corrected") + " (" + per +
           " per CADU)   ASM bit errors " + num(now, "asm_bit_errors") + "\n";
    out += "Packets  CADUs (VCID 5) " + num(now, "demux_cadus") + "   other VCID " +
           num(now, "demux_other_vcid") + "   packets " + num(now, "packets") + "   dropped gap " +
           num(now, "dropped_gap") + " / length " + num(now, "dropped_length") + " / pointer " +
           num(now, "dropped_pointer") + "   bad pointers " + num(now, "bad_pointer") + "\n";
    out +=
        "Not shown: constellation (needs the RTL debug tap), Viterbi corrections (not reported by the "
        "board)\n";
    return out;
}

}  // namespace gs
