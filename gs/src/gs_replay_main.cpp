// gs-replay: packetizes a cu8 recording into UDP (docs/protocol.md §IQ replay) and paces it
// at real time, N x real time, or flat out. Logs the achieved rate on every run (CLAUDE.md §4).
#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <ctime>
#include <string>
#include <system_error>
#include <utility>

#include "gs/iq_replay.hpp"

namespace {

// Owns a file descriptor and closes it on every exit path.
class Fd {
  public:
    explicit Fd(int fd) : fd_(fd) {}
    ~Fd() {
        if (fd_ >= 0) {
            (void)close(fd_);  // read-only file or UDP socket: nothing is lost if close fails
        }
    }
    Fd(const Fd&) = delete;
    Fd& operator=(const Fd&) = delete;
    Fd(Fd&&) = delete;
    Fd& operator=(Fd&&) = delete;
    [[nodiscard]] int get() const { return fd_; }

  private:
    int fd_;
};

// Fills `buf` from `fd` unless end of file comes first; retries short reads and EINTR.
// Returns the bytes read (< size only at end of file), or -1 on a read error.
ssize_t read_full(int fd, std::uint8_t* buf, std::size_t size) {
    std::size_t got = 0;
    while (got < size) {
        const ssize_t n = read(fd, buf + got, size - got);
        if (n == 0) {
            break;
        }
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        got += static_cast<std::size_t>(n);
    }
    return static_cast<ssize_t>(got);
}

// Thread-safe errno text (std::strerror is not). Only used on error paths, which end the run.
std::string errno_text(int e) {
    return std::system_category().message(e);
}

std::int64_t now_ns() {
    timespec ts{};
    (void)clock_gettime(CLOCK_MONOTONIC, &ts);  // CLOCK_MONOTONIC with a valid pointer cannot fail
    return (static_cast<std::int64_t>(ts.tv_sec) * 1'000'000'000LL) + ts.tv_nsec;
}

void sleep_until_ns(std::int64_t t) {
    timespec ts{};
    ts.tv_sec = static_cast<time_t>(t / 1'000'000'000LL);
    ts.tv_nsec = static_cast<long>(t % 1'000'000'000LL);
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, nullptr) == EINTR) {
    }
}

int open_socket(const gs::ReplayOptions& o, sockaddr_in& dst) {
    dst = {};
    dst.sin_family = AF_INET;
    dst.sin_port = htons(o.dest_port);
    if (inet_pton(AF_INET, o.dest_ip.c_str(), &dst.sin_addr) != 1) {
        (void)std::fprintf(stderr, "gs-replay: bad destination address %s\n", o.dest_ip.c_str());
        return -1;
    }
    const int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        std::perror("gs-replay: socket");
        return -1;
    }
    const auto ttl = static_cast<unsigned char>(o.ttl);
    if (setsockopt(fd, IPPROTO_IP, IP_MULTICAST_TTL, &ttl, sizeof ttl) != 0) {
        std::perror("gs-replay: IP_MULTICAST_TTL");
        close(fd);
        return -1;
    }
    if (!o.iface_ip.empty()) {
        in_addr ifa{};
        if (inet_pton(AF_INET, o.iface_ip.c_str(), &ifa) != 1 ||
            setsockopt(fd, IPPROTO_IP, IP_MULTICAST_IF, &ifa, sizeof ifa) != 0) {
            (void)std::fprintf(stderr, "gs-replay: cannot use interface %s\n", o.iface_ip.c_str());
            close(fd);
            return -1;
        }
    }
    return fd;
}

}  // namespace

int main(int argc, char** argv) {
    std::string err;
    const auto opt = gs::parse_replay_args(argc, argv, err);
    if (!opt) {
        (void)std::fprintf(stderr, "gs-replay: %s\n%.*s", err.c_str(),
                           static_cast<int>(gs::replay_usage().size()), gs::replay_usage().data());
        return 2;
    }
    const gs::ReplayOptions& o = *opt;

    const Fd file(open(o.file.c_str(), O_RDONLY | O_CLOEXEC));
    if (file.get() < 0) {
        (void)std::fprintf(stderr, "gs-replay: cannot open %s: %s\n", o.file.c_str(),
                           errno_text(errno).c_str());
        return 1;
    }
    sockaddr_in dst{};
    const Fd sock(open_socket(o, dst));
    if (sock.get() < 0) {
        return 1;
    }

    // All buffers fixed-size; nothing is allocated in the send loop (CLAUDE.md §5.3).
    std::array<std::uint8_t, gs::kIqBytes> iq{};
    std::array<std::uint8_t, gs::kPacketBytes> pkt{};
    const std::int64_t period_ns = gs::deadline_ns(1, o.sample_rate, o.speed_milli != 0 ? o.speed_milli : 1);
    std::uint64_t seq = 0;
    std::uint64_t late = 0;
    std::size_t tail = 0;
    int rc = 0;

    const std::int64_t t0 = now_ns();
    while (o.max_packets == 0 || seq < o.max_packets) {
        const ssize_t got = read_full(file.get(), iq.data(), iq.size());
        if (got < 0) {
            const std::string why = errno_text(errno);
            (void)std::fprintf(stderr, "gs-replay: read error at packet %llu: %s\n",
                               static_cast<unsigned long long>(seq), why.c_str());
            rc = 1;
            break;
        }
        if (std::cmp_less(got, iq.size())) {
            tail = static_cast<std::size_t>(got);
            break;
        }
        if (o.speed_milli != 0) {
            const std::int64_t due = t0 + gs::deadline_ns(seq, o.sample_rate, o.speed_milli);
            const std::int64_t now = now_ns();
            if (now < due) {
                sleep_until_ns(due);
            } else if (now - due > period_ns) {
                ++late;
            }
        }
        gs::build_packet(seq, iq, pkt);
        const ssize_t n = sendto(sock.get(), pkt.data(), pkt.size(), 0,
                                 reinterpret_cast<const sockaddr*>(&dst), sizeof dst);
        if (std::cmp_not_equal(n, pkt.size())) {
            const std::string why = n < 0 ? errno_text(errno) : std::string("short");
            (void)std::fprintf(stderr, "gs-replay: sendto failed at packet %llu: %s\n",
                               static_cast<unsigned long long>(seq), why.c_str());
            rc = 1;
            break;
        }
        ++seq;
    }
    const std::int64_t elapsed = now_ns() - t0;

    const double secs = static_cast<double>(elapsed) * 1e-9;
    const auto samples = static_cast<double>(seq * gs::kSamplesPerPacket);
    const double sps = secs > 0 ? samples / secs : 0.0;
    const std::string target = o.speed_milli == 0
                                   ? std::string("flat-out")
                                   : std::to_string(o.speed_milli / 1000) + "." +
                                         std::to_string(1000 + (o.speed_milli % 1000)).substr(1) + "x";
    (void)std::printf(
        "gs-replay: %s -> %s:%u  packets=%llu samples=%.0f elapsed=%.3f s  "
        "rate=%.0f S/s (%.2fx real time, %.2f Mb/s payload)  target=%s  late=%llu\n",
        o.file.c_str(), o.dest_ip.c_str(), o.dest_port, static_cast<unsigned long long>(seq), samples, secs,
        sps, sps / static_cast<double>(o.sample_rate),
        secs > 0 ? static_cast<double>(seq * gs::kPacketBytes) * 8e-6 / secs : 0.0, target.c_str(),
        static_cast<unsigned long long>(late));
    if (tail != 0) {
        (void)std::fprintf(stderr,
                           "gs-replay: NOT SENT: final %zu bytes (%zu samples), less than one packet\n", tail,
                           tail / 2);
    }
    return rc;
}
