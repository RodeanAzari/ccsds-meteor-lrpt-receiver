#!/usr/bin/env python3
"""Check derived constants in docs/signal-spec.md. Standard library only.

Why this exists: the spec's claims about NRZ-M and the encoded ASM decide how the
RTL correlator is built. A wrong pattern means a receiver that never finds sync, so
each claim is computed here and checked against constants in SatDump 1.2.2.
"""

ASM = 0x1ACFFC1D
ASM_BITS = [(ASM >> (31 - i)) & 1 for i in range(32)]

# SatDump bit masks: LSB is the newest bit (src-core/common/codings/viterbi/viterbi_1_2.cpp).
POLY_G1 = 79  # 0b1001111, taps D^0,1,2,3,6 = CCSDS 171 octal
POLY_G2 = 109  # 0b1101101, taps D^0,2,3,5,6 = CCSDS 133 octal

# SatDump's pre-Viterbi sync words (plugins/meteor_support/meteor/module_meteor_lrpt_decoder.cpp).
SATDUMP_SYNC_NRZM = 0xFC4EF4FD0CC2DF89
SATDUMP_SYNC_PLAIN = 0xFCA2B63DB00D9794


def parity(x: int) -> int:
    return bin(x).count("1") & 1


def conv_encode(bits: list[int], state: int = 0) -> list[int]:
    out: list[int] = []
    for b in bits:
        state = ((state << 1) | b) & 0x7F
        out += [parity(state & POLY_G1), parity(state & POLY_G2)]
    return out


def nrzm_encode(bits: list[int], last: int = 0) -> list[int]:
    out: list[int] = []
    for b in bits:
        last ^= b
        out.append(last)
    return out


def nrzm_decode(bits: list[int], last: int = 0) -> list[int]:
    out: list[int] = []
    for b in bits:
        out.append(b ^ last)
        last = b
    return out


def to_int(bits: list[int]) -> int:
    v = 0
    for b in bits:
        v = (v << 1) | b
    return v


def ccsds_pn() -> list[int]:
    """h(x) = x^8+x^7+x^5+x^3+1, all-ones seed, MSB first, 255 bytes."""
    reg = [1] * 8
    bits: list[int] = []
    for _ in range(255 * 8):
        bits.append(reg[0])
        fb = reg[0] ^ reg[3] ^ reg[5] ^ reg[7]
        reg = [*reg[1:], fb]
    return [to_int(bits[i : i + 8]) for i in range(0, len(bits), 8)]


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    return ok


def masked_matches(word: int, pattern: int, skip: int = 12) -> bool:
    """Compare 64-symbol words, ignoring the first `skip` state-dependent symbols."""
    mask = (1 << (64 - skip)) - 1
    return (word & mask) == (pattern & mask)


def main() -> int:
    results: list[bool] = []

    # Polynomials are the bit-reversed form of the CCSDS octal values.
    results.append(check("G1 = 171 octal", int(f"{POLY_G1:07b}"[::-1], 2) == 0o171))
    results.append(check("G2 = 133 octal", int(f"{POLY_G2:07b}"[::-1], 2) == 0o133))

    # Encoded ASM with and without NRZ-M, after the 12-symbol start-up transient.
    plain = to_int(conv_encode(ASM_BITS))
    nrzm0 = to_int(conv_encode(nrzm_encode(ASM_BITS, 0)))
    nrzm1 = to_int(conv_encode(nrzm_encode(ASM_BITS, 1)))
    print(f"      encoded ASM, no NRZ-M    = {plain:016X}")
    print(f"      encoded ASM, NRZ-M last=0 = {nrzm0:016X}")
    print(f"      encoded ASM, NRZ-M last=1 = {nrzm1:016X}")

    # Compare against SatDump under both of its possible polarities ("Vectors are inverted").
    full = (1 << 64) - 1
    plain_hit = masked_matches(plain, SATDUMP_SYNC_PLAIN) or masked_matches(plain ^ full, SATDUMP_SYNC_PLAIN)
    nrzm_hit = any(
        masked_matches(p, SATDUMP_SYNC_NRZM) or masked_matches(p ^ full, SATDUMP_SYNC_NRZM) for p in (nrzm0, nrzm1)
    )
    results.append(check("plain encoded ASM matches SatDump constant (last 52 symbols)", plain_hit))
    results.append(check("NRZ-M encoded ASM matches SatDump constant (last 52 symbols)", nrzm_hit))

    # NRZ-M's two start polarities are complements, so they look like a 180 degree rotation.
    # Both generators have odd weight, so complementing the input complements the output.
    mask52 = (1 << 52) - 1
    results.append(check("NRZ-M polarities are complements (last 52 symbols)", (nrzm0 ^ nrzm1) & mask52 == mask52))

    # NRZ-M decoding recovers the bits from either polarity, except for the first bit.
    payload = [(i * 7 + 3) % 5 & 1 for i in range(64)]
    enc = nrzm_encode(payload, 0)
    inv = [b ^ 1 for b in enc]
    results.append(
        check("NRZ-M decode is inversion-transparent", nrzm_decode(enc)[1:] == nrzm_decode(inv)[1:] == payload[1:])
    )

    # Randomizer matches the first entries of SatDump's ccsds_pn table.
    pn = ccsds_pn()
    results.append(
        check("PN table start = FF 48 0E C0 9A 0D 70 BC", pn[:8] == [0xFF, 0x48, 0x0E, 0xC0, 0x9A, 0x0D, 0x70, 0xBC])
    )

    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
