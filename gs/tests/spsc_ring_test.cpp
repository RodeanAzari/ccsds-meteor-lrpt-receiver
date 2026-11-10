// SpscRing: gs-rx's network thread -> processing thread queue.
//
// Why it matters: every board packet of a pass goes through this ring. A lost, duplicated or reordered slot
// is a CADU missing from the decode with nothing on the board to explain it; a slot read before the producer
// finished it is a corrupt CADU. The threaded test checks order and content under contention; run under
// ThreadSanitizer (build/gs-tsan, make gs-test) it also checks the memory ordering, which a value check alone
// can miss.
#include "gs/spsc_ring.hpp"

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <memory>
#include <thread>

namespace {

using Ring = gs::SpscRing<64, 8>;

void put(Ring& r, std::uint32_t v) {
    Ring::Slot* s = r.try_acquire();
    ASSERT_NE(s, nullptr);
    std::memcpy(s->data.data(), &v, sizeof v);
    s->len = sizeof v;
    r.publish();
}

std::uint32_t get(Ring& r) {
    const Ring::Slot* s = r.front();
    EXPECT_NE(s, nullptr);
    std::uint32_t v = 0;
    std::memcpy(&v, s->data.data(), sizeof v);
    r.release();
    return v;
}

TEST(SpscRing, EmptyFullAndFifoAcrossWraps) {
    auto r = std::make_unique<Ring>();
    EXPECT_EQ(r->front(), nullptr);
    std::uint32_t next_in = 0;
    std::uint32_t next_out = 0;
    for (int round = 0; round < 50; ++round) {  // many wraps of an 8-slot ring, at varying fill levels
        const int n = 1 + (round % 8);
        for (int k = 0; k < n; ++k) {
            put(*r, next_in++);
        }
        for (int k = 0; k < n; ++k) {
            ASSERT_EQ(get(*r), next_out++);
        }
        EXPECT_EQ(r->front(), nullptr);
    }
    for (int k = 0; k < 8; ++k) {
        put(*r, next_in++);
    }
    EXPECT_EQ(r->try_acquire(), nullptr) << "a full ring (8 of 8) must refuse";
    EXPECT_EQ(get(*r), next_out++);
    EXPECT_NE(r->try_acquire(), nullptr) << "one slot freed: one may be taken";
}

// Producer and consumer threads: every value arrives once, in order, with its slot content intact. The
// producer spins on a full ring (gs-rx drops and counts instead), so contention on both ends is exercised.
TEST(SpscRing, TwoThreadsInOrderAndIntact) {
    constexpr std::uint32_t kItems = 2'000'000;
    auto r = std::make_unique<gs::SpscRing<32, 16>>();
    std::uint64_t full = 0;
    // A ring that stops moving (a slot never freed or never published) fails here instead of hanging.
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(120);
    std::atomic<bool> stuck{false};
    std::thread producer([&] {
        for (std::uint32_t v = 0; v < kItems && !stuck; ++v) {
            gs::SpscRing<32, 16>::Slot* s = nullptr;
            while ((s = r->try_acquire()) == nullptr) {
                ++full;
                if ((full & 0xFFFFU) == 0 && std::chrono::steady_clock::now() > deadline) {
                    stuck = true;
                    return;
                }
            }
            for (std::size_t b = 0; b < s->data.size(); ++b) {
                s->data[b] = static_cast<std::uint8_t>(v + b);  // every byte depends on v: a torn slot shows
            }
            s->len = 1 + (v % 32);
            r->publish();
        }
    });
    std::uint32_t bad = 0;
    std::uint32_t v = 0;
    for (std::uint64_t spins = 0; v < kItems && !stuck;) {
        const auto* s = r->front();
        if (s == nullptr) {
            if ((++spins & 0xFFFFU) == 0 && std::chrono::steady_clock::now() > deadline) {
                stuck = true;
            }
            continue;
        }
        bool ok = s->len == 1 + (v % 32);
        for (std::size_t b = 0; b < s->data.size(); ++b) {
            ok = ok && s->data[b] == static_cast<std::uint8_t>(v + b);
        }
        bad += ok ? 0 : 1;
        r->release();
        ++v;
    }
    producer.join();
    ASSERT_FALSE(stuck) << "ring stopped moving after " << v << " of " << kItems << " items";
    EXPECT_EQ(bad, 0U);
    EXPECT_EQ(r->front(), nullptr);
    RecordProperty("producer_full_spins", std::to_string(full));
}

}  // namespace
