// libFuzzer target for the space packet demultiplexer (ADR 0015): any bytes, cut into 1,024-byte CADUs.
// Beyond ASan/UBSan findings it checks what callers rely on: every emitted packet is exactly as long as its
// own length field says (6 + field + 1); every CADU is counted once (VCID 5 or other); the packet counter
// equals the packets emitted; no packet is dropped without one being in progress (drops never exceed the
// CADUs that could hold them).
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <memory>
#include <span>

#include "gs/space_packets.hpp"

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    static auto demux = std::make_unique<gs::SpaceDemux>();
    demux = std::make_unique<gs::SpaceDemux>();  // fresh state per input
    const std::size_t n = size / gs::kCaduLen;
    std::uint64_t emitted = 0;
    for (std::size_t k = 0; k < n; ++k) {
        demux->work(std::span<const std::uint8_t, gs::kCaduLen>(data + (k * gs::kCaduLen), gs::kCaduLen),
                    [&](std::span<const std::uint8_t> p) {
                        if (p.size() < gs::kPacketHeader + 1 || p.size() > gs::kMaxPacket ||
                            p.size() != gs::kPacketHeader + ((std::size_t{p[4]} << 8U) | p[5]) + 1) {
                            std::abort();
                        }
                        ++emitted;
                    });
    }
    const gs::DemuxCounts& c = demux->counts();
    if (c.cadus + c.other_vcid != n || c.packets != emitted ||
        c.dropped_gap + c.dropped_length + c.dropped_pointer > c.cadus || c.dropped_gap > c.gaps ||
        c.dropped_pointer > c.bad_pointer) {
        std::abort();
    }
    return 0;
}
