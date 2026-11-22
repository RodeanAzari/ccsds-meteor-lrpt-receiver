"""board_gs_rx.packet_check: gs-rx's packets on hardware against the truth recording and SatDump.

Why it matters: this is the pass/fail of the hardware packet-path run. It must pass when gs-rx emits exactly the
packets of the frames the board delivered, and fail when one is missing, extra, from a frame the board lost, or
damaged; a check that passes a short packets.bin would hide a demultiplexer that silently drops.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from model.coding import encode_cadus
from model.space_packets import demux
from scripts.board_gs_rx import packet_check, replay_passed
from scripts.make_synthetic_iq import packet_cadus

N = 24


@pytest.fixture(scope="module")
def truth_cadus() -> list[bytes]:
    plain, _ = encode_cadus(packet_cadus(N, 3))
    return [bytes(c) for c in plain]


def setup(tmp: Path, truth_cadus: list[bytes],
          packets: list[bytes] | None = None) -> tuple[Path, Path, tuple[Path, Path]]:
    ours = truth_cadus[1:N - 1]  # the board loses the first and last frame
    out = tmp / "rx"
    out.mkdir()
    (out / "cadus.bin").write_bytes(b"".join(ours))
    (out / "packets.bin").write_bytes(b"".join(demux(ours)[0] if packets is None else packets))
    satdump = tmp / "satdump.cadu"
    satdump.write_bytes(b"".join(truth_cadus[4:N - 3]))  # SatDump acquires later
    truth = (tmp / "truth.cadu", tmp / "truth.packets")
    truth[0].write_bytes(b"".join(truth_cadus))
    truth[1].write_bytes(b"".join(demux(truth_cadus)[0]))
    return out, satdump, truth


def test_passes_on_exactly_the_delivered_frames_packets(tmp_path: Path, truth_cadus: list[bytes]) -> None:
    row, ok = packet_check(*setup(tmp_path, truth_cadus))
    assert ok and row[3] == 1 and row[-1] == "PASS"
    assert row[0] == row[2] < row[1]  # fewer than the truth: frames 0 and N-1 were lost


@pytest.mark.parametrize("damage", ["drop_one", "add_lost_frame_packet", "flip_bit"])
def test_fails_on_wrong_packets(tmp_path: Path, truth_cadus: list[bytes], damage: str) -> None:
    good = demux(truth_cadus[1:N - 1])[0]
    lost = [p for p in demux(truth_cadus)[0] if p not in good]
    assert lost  # the fixture's lost frames do carry packets
    packets = {
        "drop_one": good[:3] + good[4:],
        "add_lost_frame_packet": [lost[0], *good],
        "flip_bit": [good[0], bytes(np.frombuffer(good[1], np.uint8) ^ np.eye(1, len(good[1]), 6, np.uint8)[0]),
                     *good[2:]],
    }[damage]
    row, ok = packet_check(*setup(tmp_path, truth_cadus, packets))
    assert not ok and row[3] == 0


def test_fails_on_a_drop_satdump_cannot_see(tmp_path: Path, truth_cadus: list[bytes]) -> None:
    """gs-rx's first packet lies in frames SatDump never decoded: only the truth comparison can catch its loss."""
    good = demux(truth_cadus[1:N - 1])[0]
    row, ok = packet_check(*setup(tmp_path, truth_cadus, good[1:]))
    assert not ok and row[3] == 0 and row[-1] == "PASS"


def test_fails_when_satdump_disagrees(tmp_path: Path, truth_cadus: list[bytes]) -> None:
    """Ours equal the truth, SatDump's copy of one frame differs: only packet_diff can catch it."""
    out, satdump, truth = setup(tmp_path, truth_cadus)
    blob = bytearray(satdump.read_bytes())
    blob[2 * 1024 + 500] ^= 0x01  # a packet zone byte of SatDump's third frame
    satdump.write_bytes(bytes(blob))
    row, ok = packet_check(out, satdump, truth)
    assert not ok and row[3] == 1 and row[-1] == "FAIL"


# replay_passed: a real pass has frames only one decoder has (they acquire and drop out at different points) and
# channel errors in SatDump's ASM and parity bytes, so those must not fail a real replay; but a data-byte difference
# on a common frame, a CADU gs-rx missed, or an NCO word the board didn't take always must.
CLEAN = {"cadu_seq_missing": "0", "malformed": "0", "ring_full": "0"}
REAL_DIFF = {"result": "PASS", "only_ours": "1003", "only_satdump": "1", "data_bits_differ": "0",
             "asm_frames_differ": "12", "parity_bytes_differ": "40"}


def test_real_replay_passes_with_frames_only_one_decoder_has() -> None:
    assert replay_passed(CLEAN, REAL_DIFF, nco_ok=True, real=True)


def test_synthetic_replay_fails_on_what_a_real_one_may_have() -> None:
    assert not replay_passed(CLEAN, REAL_DIFF, nco_ok=True, real=False)
    assert replay_passed(CLEAN, {**REAL_DIFF, "only_satdump": "0", "asm_frames_differ": "0",
                                 "parity_bytes_differ": "0"}, nco_ok=True, real=False)
    for k in ("only_satdump", "asm_frames_differ", "parity_bytes_differ"):
        assert not replay_passed(CLEAN, {**REAL_DIFF, "only_satdump": "0", "asm_frames_differ": "0",
                                         "parity_bytes_differ": "0", k: "1"}, nco_ok=True, real=False)


@pytest.mark.parametrize("bad", [
    ({**CLEAN, "cadu_seq_missing": "2"}, REAL_DIFF, True),
    ({**CLEAN, "ring_full": "1"}, REAL_DIFF, True),
    (CLEAN, {**REAL_DIFF, "result": "FAIL", "data_bits_differ": "3"}, True),
    (CLEAN, REAL_DIFF, False),
])
def test_real_replay_fails_on_loss_data_difference_or_nco(bad: tuple[dict[str, str], dict[str, str], bool]) -> None:
    assert not replay_passed(bad[0], bad[1], nco_ok=bad[2], real=True)
