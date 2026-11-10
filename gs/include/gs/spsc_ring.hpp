// Lock-free single-producer single-consumer ring of fixed-size datagram slots, gs-rx's network thread to its
// processing thread (buildplan §4). The producer writes straight into a slot (no copy), then publishes it;
// the consumer reads the slot in place, then releases it. One thread each, no locks, no allocation after
// construction.
//
// Memory ordering: the producer's slot write happens-before its release store of head_; the consumer's
// acquire load of head_ sees it. Symmetrically for tail_ and slot reuse. A full ring is the caller's to count
// (try_acquire fails).
#ifndef GS_SPSC_RING_HPP
#define GS_SPSC_RING_HPP

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <span>

namespace gs {

template <std::size_t SlotBytes, std::size_t Slots>
class SpscRing {
    static_assert(Slots >= 2 && (Slots & (Slots - 1)) == 0, "Slots must be a power of two");

  public:
    struct Slot {
        std::array<std::uint8_t, SlotBytes> data{};
        std::size_t len = 0;
    };

    // Producer: the next free slot, or nullptr if the ring is full. Fill it, then publish().
    Slot* try_acquire() {
        const std::size_t h = head_.load(std::memory_order_relaxed);
        if (h - tail_.load(std::memory_order_acquire) == Slots) {
            return nullptr;
        }
        return &std::span(slots_)[h & (Slots - 1)];
    }

    // Producer: makes the slot from the last successful try_acquire() visible to the consumer.
    void publish() { head_.store(head_.load(std::memory_order_relaxed) + 1, std::memory_order_release); }

    // Consumer: the oldest published slot, or nullptr if empty. Read it, then release().
    [[nodiscard]] const Slot* front() const {
        const std::size_t t = tail_.load(std::memory_order_relaxed);
        if (head_.load(std::memory_order_acquire) == t) {
            return nullptr;
        }
        return &std::span(slots_)[t & (Slots - 1)];
    }

    // Consumer: frees the slot from the last successful front() for reuse.
    void release() { tail_.store(tail_.load(std::memory_order_relaxed) + 1, std::memory_order_release); }

  private:
    std::array<Slot, Slots> slots_{};
    alignas(64) std::atomic<std::size_t> head_{0};  // written by the producer only
    alignas(64) std::atomic<std::size_t> tail_{0};  // written by the consumer only
};

}  // namespace gs

#endif  // GS_SPSC_RING_HPP
