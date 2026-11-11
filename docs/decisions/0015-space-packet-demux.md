# 0015: Space packet demultiplexing in gs-rx: SatDump's packets on clean streams, damaged ones dropped and counted

## Context

Phase F's definition of done (buildplan §9) is a recorded pass replayed through the Arty coming out as space packets
that match SatDump bit for bit. SatDump 1.2.2 builds packets from VCID-5 M_PDUs with `ccsds_aos::Demuxer(882, true)`
(`docs/signal-spec.md`, "Frame layers above the CADU"). It checks neither the VCDU counter nor whether a packet's
length agrees with the next first header pointer, so after a lost CADU it emits a packet with another CADU's bytes in
it, and on a length/pointer disagreement it emits a packet one byte past the data before the next header, short of
its declared length. Our receiver drops nothing silently (CLAUDE.md §3.1), and the board's CADU stream can lose
frames that SatDump's doesn't (and the reverse), so the two streams won't always be the same.

## Options considered

| Option | Effect |
|---|---|
| **Correct and counted: drop a packet that crosses a counter gap, disagrees with the first header pointer, or meets an invalid pointer; count each** | On an unbroken stream, identical to SatDump. Where SatDump emits a damaged packet, gs-rx emits none and says why. `gs-diff` reports differences next to gaps as expected, not as failures |
| Exact port of SatDump's demultiplexer | Matches SatDump on any CADU stream, including its damaged packets; no counter for them |
| Both, behind a `--satdump-compat` switch | Both behaviours to maintain and test, for a comparison the Python port already allows |

## Decision

The user chose the first option (2026-11-10). `model/space_packets.py` holds both: `satdump_demux`, a statement-by-
statement port of SatDump's `Demuxer::work` (the reference), and `demux`, the golden model `gs-rx` is tested
against. Rules of `demux`, per VCID-5 CADU (other VCIDs ignored and counted; CADUs with an uncorrectable codeword are
dropped before, as SatDump's `rs_usecheck` does):

1. The VCDU counter must be the previous VCID-5 CADU's + 1 (mod 2²⁴). Otherwise the packet in progress is dropped
   (`dropped_gap`) and parsing resumes at this M_PDU's first header pointer.
2. A first header pointer from 882 to 2046 is invalid: the packet in progress is dropped (`dropped_pointer`) and the
   zone skipped (`bad_pointer`).
3. A packet in progress must end exactly at this M_PDU's first header pointer, or, with no header in the zone
   (pointer 2047), not end inside it. Otherwise it is dropped (`dropped_length`) and parsing resumes at the pointer.
4. From the pointer, packets are read back to back; a header may span zones.

A complete packet is emitted at once (SatDump emits one kind a CADU late, `signal-spec.md`; content is the same).
No version, APID or idle-packet filtering: SatDump does none either.

## Consequences

- gs-rx's packet stream equals SatDump's on unbroken stretches; around a lost CADU it lacks the one packet SatDump
  emits damaged. `gs-diff` has to align the two streams (by APID and sequence count) and report gap-adjacent
  differences separately.
  **Amended 2026-11-10 (user's choice):** `gs-diff` (C++) compares CADUs only (buildplan §8.5); the packets are
  compared by `scripts/packet_diff.py`, against `satdump_demux` over SatDump's .cadu (SatDump 1.2.2 writes no
  packets). It keys packets by where they start (VCDU counter, zone offset), not by APID and sequence count, which
  wrap within a pass. A difference is expected only where it touches a CADU one side lacks, a SatDump packet that
  crosses a gap or is short, a CADU where the golden model drops a packet, or SatDump's held-back last packet;
  anything else fails.
- The counters (`DemuxCounts`) go into gs-rx's report and `gs-view`.

## Measured evidence

- `model/tests/test_space_packets.py` (34 tests), expected values from `mux` (signal-spec.md's layout), not from
  either demultiplexer: on 20 random unbroken streams, plus headers split at every offset 1–7 bytes before a zone's
  end, packets ending on zone boundaries, a packet over five zones, a counter wrap and an interleaved VCID 63,
  `demux` and `satdump_demux` return exactly the packets put in. A lost CADU, a length one too long and one too short,
  and invalid pointers 882 and 2046: `demux` drops exactly the damaged packet with the right counter and keeps the
  rest; `satdump_demux` reproduces SatDump's damaged output (one stray byte, `demuxer.cpp:103`).
- Planted bugs: in `demux`, gap check removed, counter wrap ignored, late or early packet end not dropped, invalid
  pointer keeping the packet; in the port, the stray byte removed. Each fails one test. One more, in the port, a
  header exactly 6 bytes before the zone's end read at once instead of buffered as split, passes: it is equivalent
  (the payload continues from the next zone's byte 0 either way).
- gs-rx (C++) `SpaceDemux` against this model: all 9 vector scenarios (`gs/tests/data/demux`, from `scripts/gen_gs_vectors.py`) byte for byte and counter for counter, Release and Debug. Planted bugs (gap check, counter wrap, late or early end kept, invalid pointer keeping the packet, header completion not continuing, 5-bit VCID mask) each fail a scenario; the VCID mask only after a VCID-37 stream was added to `mixed_vcid`. `make fuzz`: 373 k runs in 60 s, no finding; a planted length bug aborts at once.
