// gs-rx: receives the board's packets (docs/protocol.md types 1, 2) on UDP, writes the good CADUs and the
// space packets demultiplexed from them (buildplan §4, ADR 0015).
//
//   gs-rx --out DIR [--port 26401] [--idle S] [--seconds S]
//
// Network thread -> lock-free SPSC ring -> processing thread (this one). DIR/cadus.bin: every CADU whose
// codewords all corrected, 1,024 bytes each, in arrival order (SatDump's .cadu layout); DIR/packets.bin: the
// space packets, back to back (each self-delimiting). Stops on SIGINT/SIGTERM, after --idle seconds without a
// datagram (default 5, counted from start), or after --seconds. The summary (every counter, and the board's
// last stats packet) goes to stdout and DIR/gs-rx.txt. Every 0.5 s while running, the same lines plus state
// and elapsed_ms go to DIR/status.txt (written to status.txt.tmp, then renamed), which gs-view draws (ADR
// 0016); at the end, state=final. Nothing is dropped silently: a full ring is counted (ring_full), a failed
// status write too (status_write_errors).
#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <array>
#include <atomic>
#include <cerrno>
#include <charconv>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <system_error>
#include <thread>

#include "gs/board_packets.hpp"
#include "gs/rx_processor.hpp"
#include "gs/spsc_ring.hpp"
#include "gs/status.hpp"

namespace {

constexpr std::size_t kSlotBytes = 2048;  // > the largest board packet (CADU: 1,048 bytes)
constexpr std::size_t kSlots = 4096;      // ~2 s of CADUs at the board's fastest replay rate
using Ring = gs::SpscRing<kSlotBytes, kSlots>;

// A signal handler can only talk to the program through a volatile sig_atomic_t at namespace scope.
// NOLINTNEXTLINE(cppcoreguidelines-avoid-non-const-global-variables)
volatile std::sig_atomic_t g_stop = 0;

extern "C" void on_signal(int /*sig*/) {
    g_stop = 1;
}

struct Options {
    std::string out;
    std::uint16_t port = 26401;  // docs/protocol.md: board -> host destination port
    double idle_s = 5.0;
    double max_s = 0.0;  // 0 = no limit
};

template <class T>
bool parse_num(std::string_view v, T& out) {
    const auto* end = v.data() + v.size();
    // from_chars takes [first, last), not a NUL-terminated string.
    // NOLINTNEXTLINE(bugprone-suspicious-stringview-data-usage)
    const auto r = std::from_chars(v.data(), end, out);
    return r.ec == std::errc{} && r.ptr == end;
}

std::optional<Options> parse_args(int argc, char** argv, std::string& error) {
    Options o;
    const std::span<char*> args(argv, static_cast<std::size_t>(argc));
    for (std::size_t i = 1; i < args.size(); ++i) {
        const std::string_view a = args[i];
        if (i + 1 >= args.size()) {
            error = "missing value for " + std::string(a);
            return std::nullopt;
        }
        const std::string_view v = args[++i];
        bool ok = true;
        if (a == "--out") {
            o.out = std::string(v);
        } else if (a == "--port") {
            ok = parse_num(v, o.port);
        } else if (a == "--idle") {
            ok = parse_num(v, o.idle_s) && o.idle_s > 0;
        } else if (a == "--seconds") {
            ok = parse_num(v, o.max_s) && o.max_s >= 0;
        } else {
            error = "unexpected argument: " + std::string(a);
            return std::nullopt;
        }
        if (!ok) {
            error = "bad value for " + std::string(a) + ": " + std::string(v);
            return std::nullopt;
        }
    }
    if (o.out.empty()) {
        error = "--out DIR is required";
        return std::nullopt;
    }
    return o;
}

std::int64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

// Owns a FILE* opened for binary writing with a large buffer; reports the first write error.
class Out {
  public:
    explicit Out(const std::filesystem::path& p) : f_(std::fopen(p.c_str(), "wb")) {
        if (f_ != nullptr) {
            (void)std::setvbuf(f_, nullptr, _IOFBF, 1U << 20U);  // a failed setvbuf only costs speed
        }
    }
    ~Out() {
        if (f_ != nullptr) {
            // Out is the RAII owner of this FILE* (no gsl::owner in this codebase).
            // NOLINTNEXTLINE(cppcoreguidelines-owning-memory)
            (void)std::fclose(f_);  // close() reports errors; this is the error path
        }
    }
    Out(const Out&) = delete;
    Out& operator=(const Out&) = delete;
    Out(Out&&) = delete;
    Out& operator=(Out&&) = delete;
    [[nodiscard]] bool open() const { return f_ != nullptr; }
    void write(std::span<const std::uint8_t> b) {
        ok_ = ok_ && f_ != nullptr && std::fwrite(b.data(), 1, b.size(), f_) == b.size();
    }
    bool close() {
        if (f_ == nullptr) {
            return false;
        }
        // Out is the RAII owner of this FILE* (no gsl::owner in this codebase).
        // NOLINTNEXTLINE(cppcoreguidelines-owning-memory)
        const bool closed = std::fclose(f_) == 0;
        f_ = nullptr;
        return ok_ && closed;
    }

  private:
    std::FILE* f_;
    bool ok_ = true;
};

// text -> tmp, then renamed over path: a reader sees the old file or the new one, never a partial one. POSIX
// calls only: nothing allocated on the processing thread.
bool write_atomic(const char* tmp, const char* path, std::string_view text) {
    const int fd = ::open(tmp, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC,
                          0644);  // NOLINT(cppcoreguidelines-pro-type-vararg)
    if (fd < 0) {
        return false;
    }
    std::size_t done = 0;
    while (done < text.size()) {
        const ssize_t n = ::write(fd, text.data() + done, text.size() - done);
        if (n <= 0) {
            (void)::close(fd);
            return false;
        }
        done += static_cast<std::size_t>(n);
    }
    return ::close(fd) == 0 && std::rename(tmp, path) == 0;
}

}  // namespace

int main(int argc, char** argv) {
    std::string err;
    const auto opt = parse_args(argc, argv, err);
    if (!opt) {
        (void)std::fprintf(stderr, "gs-rx: %s\nusage: gs-rx --out DIR [--port N] [--idle S] [--seconds S]\n",
                           err.c_str());
        return 2;
    }
    const Options& o = *opt;
    std::error_code ec;
    std::filesystem::create_directories(o.out, ec);
    const std::filesystem::path dir(o.out);
    Out cadus(dir / "cadus.bin");
    Out packets(dir / "packets.bin");
    if (!cadus.open() || !packets.open()) {
        (void)std::fprintf(stderr, "gs-rx: cannot write into %s\n", o.out.c_str());
        return 1;
    }

    const int sock = socket(AF_INET, SOCK_DGRAM, 0);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(o.port);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    const int rcvbuf = 8 << 20;
    const timeval tick{.tv_sec = 0, .tv_usec = 100'000};  // recv wakes every 100 ms to see the stop flag
    if (sock < 0 || setsockopt(sock, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof rcvbuf) != 0 ||
        setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tick, sizeof tick) != 0 ||
        bind(sock, reinterpret_cast<const sockaddr*>(&addr), sizeof addr) != 0) {
        std::perror("gs-rx: socket");
        if (sock >= 0) {
            (void)close(sock);
        }
        return 1;
    }
    (void)std::signal(SIGINT, on_signal);
    (void)std::signal(SIGTERM, on_signal);

    // Allocated once, before the data path starts (CLAUDE.md §5.3).
    auto ring = std::make_unique<Ring>();
    auto scratch = std::make_unique<std::array<std::uint8_t, kSlotBytes>>();
    gs::RxProcessor proc;
    std::atomic<bool> stop{false};
    std::atomic<std::uint64_t> ring_full{0};
    const std::int64_t t0_ns = now_ns();
    std::atomic<std::int64_t> last_rx{t0_ns};
    std::atomic<int> net_errno{0};
    const std::string status_path = (dir / "status.txt").string();
    const std::string status_tmp = (dir / "status.txt.tmp").string();
    auto status = std::make_unique<gs::StatusText>();
    std::uint64_t status_write_errors = 0;
    const auto snapshot = [&](std::string_view state, std::int64_t now) {
        status->clear();
        status->add("state", state);
        status->add("elapsed_ms", static_cast<std::uint64_t>((now - t0_ns) / 1'000'000));
        gs::add_counts(*status, proc.counts(), ring_full.load(), proc.demux_counts(), proc.last_stats());
        status->add("status_write_errors", status_write_errors);
        if (status->overflowed() || !write_atomic(status_tmp.c_str(), status_path.c_str(), status->view())) {
            ++status_write_errors;
        }
    };

    std::thread net([&] {
        while (!stop.load(std::memory_order_relaxed)) {
            Ring::Slot* slot = ring->try_acquire();
            std::uint8_t* buf = slot != nullptr ? slot->data.data() : scratch->data();
            const ssize_t n = recv(sock, buf, kSlotBytes, 0);
            if (n < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
                    continue;
                }
                net_errno = errno;
                stop = true;
                break;
            }
            last_rx.store(now_ns(), std::memory_order_relaxed);
            if (slot == nullptr) {
                ring_full.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
            slot->len = static_cast<std::size_t>(n);
            ring->publish();
        }
    });

    const auto on_cadu = [&](std::span<const std::uint8_t, gs::kCaduLen> c) { cadus.write(c); };
    const auto on_packet = [&](std::span<const std::uint8_t> p) { packets.write(p); };
    const std::int64_t t0 = t0_ns;
    constexpr std::int64_t kStatusPeriodNs = 500'000'000;  // ADR 0016
    std::int64_t next_status = t0;
    const auto idle_ns = static_cast<std::int64_t>(o.idle_s * 1e9);
    const auto max_ns = static_cast<std::int64_t>(o.max_s * 1e9);
    while (true) {
        if (const std::int64_t now = now_ns(); now >= next_status) {
            snapshot("running", now);
            next_status = now + kStatusPeriodNs;
        }
        if (const Ring::Slot* s = ring->front(); s != nullptr) {
            proc.handle(std::span<const std::uint8_t>(s->data.data(), s->len), on_cadu, on_packet);
            ring->release();
            continue;
        }
        const std::int64_t now = now_ns();
        if (g_stop != 0 || stop.load() || now - last_rx.load(std::memory_order_relaxed) > idle_ns ||
            (max_ns > 0 && now - t0 > max_ns)) {
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    stop = true;
    net.join();
    while (const Ring::Slot* s = ring->front()) {  // what arrived while stopping
        proc.handle(std::span<const std::uint8_t>(s->data.data(), s->len), on_cadu, on_packet);
        ring->release();
    }
    (void)close(sock);
    const bool written = cadus.close() && packets.close();

    snapshot("final", now_ns());
    auto summary = std::make_unique<gs::StatusText>();  // after the data path: allocation is fine here
    gs::add_counts(*summary, proc.counts(), ring_full.load(), proc.demux_counts(), proc.last_stats());
    summary->add("status_write_errors", status_write_errors);
    const std::string_view text = summary->view();
    (void)std::fwrite(text.data(), 1, text.size(), stdout);
    Out report(dir / "gs-rx.txt");
    report.write(
        std::span<const std::uint8_t>(reinterpret_cast<const std::uint8_t*>(text.data()), text.size()));
    const bool reported = report.open() && report.close();
    if (net_errno != 0) {
        const std::string why = std::system_category().message(net_errno);
        (void)std::fprintf(stderr, "gs-rx: recv failed: %s\n", why.c_str());
        return 1;
    }
    if (!written || !reported || summary->overflowed() || status_write_errors != 0) {
        (void)std::fprintf(stderr, "gs-rx: write error in %s\n", o.out.c_str());
        return 1;
    }
    return 0;
}
