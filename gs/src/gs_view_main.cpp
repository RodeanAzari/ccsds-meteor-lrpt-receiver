// gs-view: live terminal view of a gs-rx run (buildplan §4, ADR 0016).
//
//   gs-view DIR [--once]
//
// Reads DIR/status.txt (written by gs-rx every 0.5 s) and redraws the screen every 0.5 s until the run is
// final or Ctrl-C. --once prints one screen without control codes and exits: 0 if a status was read, 1 if
// not. Exit 2 on bad arguments.
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <thread>
#include <utility>

#include "gs/view.hpp"

namespace {

std::optional<gs::Status> read_status(const std::filesystem::path& p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) {
        return std::nullopt;
    }
    const std::string text{std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()};
    return gs::parse_status(text);
}

}  // namespace

int main(int argc, char** argv) {
    const std::span<char*> args(argv, static_cast<std::size_t>(argc));
    const bool once = args.size() == 3 && std::string_view(args[2]) == "--once";
    if (args.size() != 2 && !once) {
        (void)std::fputs("usage: gs-view DIR [--once]\n", stderr);
        return 2;
    }
    const std::filesystem::path path = std::filesystem::path(args[1]) / "status.txt";
    if (once) {
        const auto s = read_status(path);
        if (!s) {
            (void)std::fprintf(stderr, "gs-view: cannot read %s\n", path.c_str());
            return 1;
        }
        (void)std::fputs(gs::render(*s, nullptr).c_str(), stdout);
        return 0;
    }
    // last: the newest snapshot; prev: the one before it with another elapsed_ms (the poll and gs-rx's writes
    // share a period, so the same snapshot is often read twice; a rate needs two different ones).
    std::optional<gs::Status> last;
    std::optional<gs::Status> prev;
    while (true) {
        if (auto s = read_status(path)) {
            if (!last || gs::status_u64(*s, "elapsed_ms") != gs::status_u64(*last, "elapsed_ms")) {
                prev = std::move(last);
                last = std::move(s);
            }
        }
        std::string screen = "\x1b[H\x1b[2J";  // home, clear
        screen += last ? gs::render(*last, prev ? &*prev : nullptr)
                       : "gs-view  waiting for " + path.string() + "\n";
        (void)std::fputs(screen.c_str(), stdout);
        (void)std::fflush(stdout);
        if (last) {
            if (const auto st = last->find("state"); st != last->end() && st->second == "final") {
                return 0;
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
}
