#include "gs/msumr.hpp"

#include <algorithm>

// A codec indexes fixed tables (Huffman lookup, zigzag, 8 x 8 blocks) by computed positions throughout; every
// index is bounded by construction, and ASan/UBSan (Debug, gs-test) and the fuzzer (msumr_fuzz) check it at
// run time. NOLINTBEGIN(cppcoreguidelines-pro-bounds-constant-array-index)

namespace gs::msumr {

namespace {

// T.81 Table K.1, luminance quantization, natural order.
constexpr std::array<float, 64> kK1 = {16, 11, 10, 16, 24,  40,  51,  61,  12, 12, 14, 19, 26,  58,  60,  55,
                                       14, 13, 16, 24, 40,  57,  69,  56,  14, 17, 22, 29, 51,  87,  80,  62,
                                       18, 22, 37, 56, 68,  109, 103, 77,  24, 35, 55, 64, 81,  104, 113, 92,
                                       49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99};

// T.81 Tables K.3 and K.5: luminance DC and AC codes as BITS (codes per length 1..16) and HUFFVAL.
constexpr std::array<std::uint8_t, 16> kDcBits = {0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0};
constexpr std::array<std::uint8_t, 12> kDcVals = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};
constexpr std::array<std::uint8_t, 16> kAcBits = {0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D};
constexpr std::array<std::uint8_t, 162> kAcVals = {
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07, 0x22,
    0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08, 0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33,
    0x62, 0x72, 0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x34,
    0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55,
    0x56, 0x57, 0x58, 0x59, 0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75, 0x76,
    0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x92, 0x93, 0x94, 0x95, 0x96,
    0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5,
    0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xD2, 0xD3, 0xD4,
    0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1,
    0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA};

constexpr unsigned kPeek = 16;  // longest code

// 16-bit peek -> symbol and code length; length 0 where no code is a prefix of the peek.
struct Lut {
    std::array<std::uint8_t, 1U << kPeek> sym{};
    std::array<std::uint8_t, 1U << kPeek> len{};
};

// T.81 Annex C: codes assigned in canonical order.
template <std::size_t N>
Lut make_lut(const std::array<std::uint8_t, 16>& bits, const std::array<std::uint8_t, N>& vals) {
    Lut lut;
    std::uint32_t code = 0;
    std::size_t k = 0;
    for (unsigned length = 1; length <= kPeek; ++length) {
        for (unsigned n = 0; n < bits[length - 1]; ++n) {
            const std::uint32_t lo = code << (kPeek - length);
            const std::uint32_t hi = lo + (1U << (kPeek - length));
            std::fill(lut.sym.begin() + lo, lut.sym.begin() + hi, vals[k]);
            std::fill(lut.len.begin() + lo, lut.len.begin() + hi, static_cast<std::uint8_t>(length));
            ++code;
            ++k;
        }
        code <<= 1U;
    }
    return lut;
}

const Lut& dc_lut() {
    static const Lut lut = make_lut(kDcBits, kDcVals);
    return lut;
}

const Lut& ac_lut() {
    static const Lut lut = make_lut(kAcBits, kAcVals);
    return lut;
}

// MSB-first bit reader with SatDump's end rule: a code or its magnitude bits must fit in what is left.
class Bits {
  public:
    explicit Bits(std::span<const std::uint8_t> data) : data_(data), n_(data.size() * 8) {}

    // The next 16 bits, zeros past the end.
    [[nodiscard]] std::uint32_t peek16() const {
        std::uint32_t v = 0;
        const std::size_t byte = pos_ / 8;
        for (std::size_t k = 0; k < 3; ++k) {
            v = (v << 8U) | (byte + k < data_.size() ? data_[byte + k] : 0U);
        }
        return (v >> (8U - (pos_ % 8))) & 0xFFFFU;
    }

    bool symbol(const Lut& lut, std::uint8_t& out) {
        const std::uint32_t p = peek16();
        const std::size_t length = lut.len[p];
        if (length == 0 || length > n_ - pos_) {
            return false;
        }
        pos_ += length;
        out = lut.sym[p];
        return true;
    }

    // T.81 F.12 EXTEND: size bits, a leading 0 means negative. False if fewer bits are left.
    bool magnitude(unsigned size, std::int32_t& out) {
        if (size > n_ - pos_) {
            return false;
        }
        if (size == 0) {
            out = 0;
            return true;
        }
        const auto v = static_cast<std::int32_t>(peek16() >> (kPeek - size));
        pos_ += size;
        out = (v >> (size - 1)) != 0 ? v : v - ((1 << size) - 1);
        return true;
    }

  private:
    std::span<const std::uint8_t> data_;
    std::size_t n_;
    std::size_t pos_ = 0;
};

// 2048 * sqrt(2) * cos(k * pi / 16); 256 / sqrt(2).
constexpr std::int64_t kW1 = 2841, kW2 = 2676, kW3 = 2408, kW5 = 1609, kW6 = 1108, kW7 = 565, kR2 = 181;

// One 1-D pass of the fixed-point IDCT. pass 0 = rows, 1 = columns (different prescale and rounding).
std::array<std::int64_t, 8> idct_1d(const std::array<std::int64_t, 8>& x, int pass) {
    const bool rows = pass == 0;
    const std::int64_t r = rows ? 0 : 4;
    const int s = rows ? 0 : 3;
    std::int64_t a0 = rows ? (x[0] << 11) + 128 : (x[0] << 8) + 8192;
    std::int64_t a1 = rows ? x[4] << 11 : x[4] << 8;
    std::int64_t a2 = x[6];
    std::int64_t a3 = x[2];
    std::int64_t a4 = x[1];
    std::int64_t a5 = x[7];
    std::int64_t a6 = x[5];
    std::int64_t a7 = x[3];
    std::int64_t t = (kW7 * (a4 + a5)) + r;
    const std::int64_t b4 = (t + ((kW1 - kW7) * a4)) >> s;
    a5 = (t - ((kW1 + kW7) * a5)) >> s;
    a4 = b4;
    t = (kW3 * (a6 + a7)) + r;
    const std::int64_t b6 = (t - ((kW3 - kW5) * a6)) >> s;
    a7 = (t - ((kW3 + kW5) * a7)) >> s;
    a6 = b6;
    t = a0 + a1;
    a0 -= a1;
    a1 = (kW6 * (a3 + a2)) + r;
    const std::int64_t b2 = (a1 - ((kW2 + kW6) * a2)) >> s;
    a3 = (a1 + ((kW2 - kW6) * a3)) >> s;
    a2 = b2;
    a1 = a4 + a6;
    a4 -= a6;
    a6 = a5 + a7;
    a5 -= a7;
    a7 = t + a3;
    t -= a3;
    a3 = a0 + a2;
    a0 -= a2;
    a2 = ((kR2 * (a4 + a5)) + 128) >> 8;
    a4 = ((kR2 * (a4 - a5)) + 128) >> 8;
    const int sh = rows ? 8 : 14;
    return {(a7 + a1) >> sh, (a3 + a2) >> sh, (a0 + a4) >> sh, (t + a6) >> sh,
            (t - a6) >> sh,  (a0 - a4) >> sh, (a3 - a2) >> sh, (a7 - a1) >> sh};
}

constexpr auto kMcusU32 = static_cast<std::uint32_t>(kMcus);  // for the id arithmetic, which is 32-bit

constexpr std::uint32_t floor14(std::uint32_t x) {
    return x - (x % kMcusU32);
}

}  // namespace

std::array<std::int32_t, 64> quant_table(std::uint8_t qf) {
    // Each step rounds to float32, in this order, as SatDump does (signal-spec.md). Built with
    // -ffp-contract=off so no step is fused; checked over all 256 QFs, fusing would change no entry, so this
    // is only a guard.
    auto f = static_cast<float>(qf);
    f = (qf > 20 && qf < 50) ? 5000.0F / f : 200.0F - (2.0F * f);
    std::array<std::int32_t, 64> q{};
    for (std::size_t k = 0; k < 64; ++k) {
        const float scaled = f / 100.0F;
        const float v = (scaled * kK1[k]) + 0.5F;
        q[k] = std::max(static_cast<std::int32_t>(v), 1);  // truncates toward zero, like C
    }
    return q;
}

std::size_t decode_coefficients(std::span<const std::uint8_t> data,
                                std::array<std::array<std::int32_t, 64>, kMcus>& coef) {
    for (auto& c : coef) {
        c.fill(0);
    }
    Bits bits(data);
    std::int32_t dc = 0;
    for (std::size_t m = 0; m < kMcus; ++m) {
        std::uint8_t cat = 0;
        std::int32_t diff = 0;
        if (!bits.symbol(dc_lut(), cat) || !bits.magnitude(cat, diff)) {
            return m;
        }
        dc += diff;
        std::array<std::int32_t, 64> zz{};  // zigzag order
        zz[0] = dc;
        unsigned index = 1;
        unsigned counted = 0;
        while (counted < 63) {
            std::uint8_t rs = 0;
            if (!bits.symbol(ac_lut(), rs)) {
                return m;
            }
            const unsigned run = rs >> 4U;
            const unsigned size = rs & 0x0FU;
            if (rs == 0x00) {  // EOB
                break;
            }
            std::int32_t value = 0;  // ZRL (0xF0): 16 zeros, no magnitude bits
            if (rs != 0xF0 && !bits.magnitude(size, value)) {
                return m;
            }
            counted += run + 1;
            if (index + run + 1 >=
                64) {  // would reach index 64: the block ends (coefficient 63 is never set)
                break;
            }
            zz[index + run] = value;
            index += run + 1;
        }
        for (std::size_t k = 0; k < 64; ++k) {
            coef[m][kZigzag[k]] = zz[k];
        }
    }
    return kMcus;
}

std::array<std::int64_t, 64> idct(const std::array<std::int64_t, 64>& coef) {
    std::array<std::int64_t, 64> h{};
    for (std::size_t r = 0; r < 8; ++r) {
        std::array<std::int64_t, 8> x{};
        std::copy_n(coef.begin() + static_cast<std::ptrdiff_t>(r * 8), 8, x.begin());
        const bool flat = std::all_of(x.begin() + 1, x.end(), [](std::int64_t v) { return v == 0; });
        const std::array<std::int64_t, 8> y = flat ? std::array<std::int64_t, 8>{} : idct_1d(x, 0);
        for (std::size_t c = 0; c < 8; ++c) {
            h[(r * 8) + c] = flat ? x[0] << 3 : y[c];  // row shortcut: all AC zero -> DC << 3 across the row
        }
    }
    std::array<std::int64_t, 64> out{};
    for (std::size_t c = 0; c < 8; ++c) {
        std::array<std::int64_t, 8> x{};
        for (std::size_t r = 0; r < 8; ++r) {
            x[r] = h[(r * 8) + c];
        }
        const std::array<std::int64_t, 8> y = idct_1d(x, 1);
        for (std::size_t r = 0; r < 8; ++r) {
            out[(r * 8) + c] = y[r];
        }
    }
    return out;
}

std::optional<Segment> decode_segment(std::span<const std::uint8_t> data) {
    if (data.size() <= 14 || data[9] != 0 || (data[10] & 0x0FU) != 0 || data[11] != 0xFF ||
        data[12] != 0xF0) {
        return std::nullopt;
    }
    std::array<std::array<std::int32_t, 64>, kMcus> coef{};
    const std::size_t done = decode_coefficients(data.subspan(14), coef);
    if (done == 0) {
        return std::nullopt;
    }
    const std::array<std::int32_t, 64> q = quant_table(data[13]);
    Segment seg{.mcun = data[8], .pixels = {}};
    for (std::size_t m = 0; m < kMcus; ++m) {
        std::array<std::int64_t, 64> deq{};
        for (std::size_t k = 0; k < 64; ++k) {
            deq[k] = std::int64_t{coef[m][k]} * q[k];
        }
        const std::array<std::int64_t, 64> block = idct(deq);
        for (std::size_t r = 0; r < 8; ++r) {
            for (std::size_t c = 0; c < 8; ++c) {
                // MCUs after a decode failure stay 0.
                const std::int64_t v = m < done ? block[(r * 8) + c] + 128 : 0;
                seg.pixels[(r * kSegWidth) + (m * 8) + c] =
                    static_cast<std::uint8_t>(std::clamp<std::int64_t>(v, 0, 255));
            }
        }
    }
    return seg;
}

void Reader::add(std::span<const std::uint8_t> packet) {
    if (packet.size() < 6) {
        return;
    }
    const unsigned apid = ((packet[0] & 0x07U) << 8U) | packet[1];
    if (apid < kFirstApid || apid >= kFirstApid + kChannels) {
        return;
    }
    const std::optional<Segment> seg = decode_segment(packet.subspan(6));
    if (!seg) {
        return;
    }
    Channel& c = ch_[apid - kFirstApid];
    const std::uint32_t seq = ((packet[2] & 0x3FU) << 8U) | packet[3];
    const std::uint32_t mcu_count = seg->mcun / kMcusU32;
    if (c.last_seq > seq && c.last_seq > 13926 && seq < 2458) {
        c.rollover += kSeqMod;
    }
    if (c.offset == kUnset) {
        const std::uint32_t mcu_seq = seq + (mcu_count > seq ? kSeqMod : 0) - mcu_count;
        c.offset = (mcu_seq + c.rollover) % kPacketsPerScan;
    }
    const std::uint32_t id = ((seq + c.rollover - c.offset) / kPacketsPerScan * kMcusU32) + mcu_count;
    const std::uint32_t first = std::min(c.first, id);
    const std::uint32_t last = std::max(c.last, id);
    if (last - first > kMaxSpan) {
        return;
    }
    c.first = first;
    c.last = last;
    c.last_seq = seq;
    c.segments.insert_or_assign(id, *seg);
}

std::pair<std::uint32_t, std::uint32_t> Reader::extent(int channel) const {
    // The channel with the smallest offset, lowest-numbered on a tie.
    std::size_t low = kChannels;
    for (std::size_t i = 0; i < ch_.size(); ++i) {
        if (ch_[i].offset < (low == kChannels ? kPacketsPerScan : ch_[low].offset)) {
            low = i;
        }
    }
    std::uint32_t f = kUnset;  // all channels
    std::uint32_t e = 0;
    std::uint32_t fb = kUnset;  // channels below the lowest-offset one
    std::uint32_t eb = 0;
    std::uint32_t fa = kUnset;  // it and the channels above
    std::uint32_t ea = 0;
    for (std::size_t i = 0; i < ch_.size(); ++i) {
        const Channel& c = ch_[i];
        if (c.offset == kUnset) {
            continue;
        }
        f = std::min(f, c.first);
        e = std::max(e, c.last);
        if (i < low) {
            fb = std::min(fb, c.first);
            eb = std::max(eb, c.last);
        } else {
            fa = std::min(fa, c.first);
            ea = std::max(ea, c.last);
        }
    }
    if (low != 0) {  // SatDump's "lowest transmitted" is always channel 0, data or not
        const bool a = floor14(fb) >= floor14(fa);
        const bool b = floor14(eb) < floor14(ea);
        const auto ch = static_cast<std::size_t>(channel);
        if (ch < low) {
            f = a ? f - kMcusU32 : f;
            e = b ? e - kMcusU32 : e;
        } else {
            f = a ? f : f + kMcusU32;
            e = b ? e : e + kMcusU32;
        }
    }
    e += kMcusU32;
    const Channel& c = ch_.at(static_cast<std::size_t>(channel));
    if (c.first == kUnset) {
        f = 0;
    }
    if (c.last == 0) {
        e = 0;
    }
    return {floor14(f), floor14(e)};
}

std::optional<Image> Reader::image(int channel) const {
    const auto [first, end] = extent(channel);
    const std::size_t scans = (end - first) / kMcus;
    if (scans * 8 > kMaxRows) {
        return std::nullopt;
    }
    Image img{.rows = scans * 8, .pixels = std::vector<std::uint8_t>(scans * 8 * kWidth, 0)};
    const auto& segs = ch_.at(static_cast<std::size_t>(channel)).segments;
    for (std::size_t s = 0; s < scans; ++s) {
        for (std::size_t j = 0; j < kMcus; ++j) {
            const auto it = segs.find(static_cast<std::uint32_t>(first + (s * kMcus) + j));
            if (it == segs.end()) {
                continue;
            }
            for (std::size_t r = 0; r < 8; ++r) {
                std::copy_n(it->second.pixels.begin() + static_cast<std::ptrdiff_t>(r * kSegWidth), kSegWidth,
                            img.pixels.begin() +
                                static_cast<std::ptrdiff_t>(((s * 8 + r) * kWidth) + (j * kSegWidth)));
            }
        }
    }
    return img;
}

std::size_t Reader::segments(int channel) const {
    return ch_.at(static_cast<std::size_t>(channel)).segments.size();
}

}  // namespace gs::msumr
// NOLINTEND(cppcoreguidelines-pro-bounds-constant-array-index)
