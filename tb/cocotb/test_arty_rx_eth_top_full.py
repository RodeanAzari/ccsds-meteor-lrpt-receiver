"""arty_rx_eth_top end to end (make sim-full): a recording in as MII nibbles, CADU and stats packets out of MII TX.

Why it matters: on the board the only evidence is the UDP packets that come back. This test sends a synthetic
recording as replay datagrams (docs/protocol.md "IQ replay") at the 100 Mb/s line rate, the fastest gs-replay can
send (5.69x real time), into a board top built with the default NCO word (150 kHz), after a SET_NCO command
(docs/protocol.md "Control commands", ADR 0014) with the word the host's coarse estimate gives for it (ADR 0002):
151 kHz is 1 kHz from the default, far outside the Costas loop's pull-in, so nothing decodes unless the command
reaches the DDC. A second SET_NCO mid-replay must be refused (it would retune the DDC under a running replay). It
parses what leaves MII TX by docs/protocol.md alone. Each type 2 packet must carry the bit-true model chain's
CADU and status (raw -> ddc_fixed -> sync -> frame sync -> Viterbi -> cadu_fixed), in order with consecutive
pkt_seq, interleaved with stats packets by pkt_arb2 without either being cut. The last stats packet must report every
datagram received with no loss anywhere (eth_rx overflow, ingest gaps) and the frame sync's counters equal to the
model's: at line rate the ingest cannot push back on the sender, so a chain slower than the replay shows up as
eth_ovf_lost, here and on the board. The per-block and chain tests cover the decoding itself; what this adds is the
DDC -> rx_chain link, the parameter wiring (NCO word, rx_config_pkg), the command path, the packet path and the
counters. The loops
start cold, so frame 0 is lost to pull-in.
"""

from __future__ import annotations

import os
import struct
import subprocess
from dataclasses import replace
from pathlib import Path

import cocotb
import numpy as np
from cocotb import start_soon, test
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from mii import collect_mii_tx, parse_udp_frame, send_mii, udp_frame
from sync_chain import expected, raw_input

from model import ddc_fixed, sync_fixed
from model.cadu_fixed import CaduOut, cadus_from_windows
from model.coding import ASM_BYTES
from model.framesync_fixed import decode_windows, frame_sync_fixed, windows
from model.sync_fixed import serial
from model.viterbi_fixed import quantize
from scripts.board_rx import set_nco_command
from scripts.board_stats import FIELDS, parse_stats

FRAMES = 5
SEED = 20
FREQ_WORD = 0x25C0_EE00  # sent by SET_NCO; checked below against the coarse estimate of this stimulus
DEFAULT_WORD = 0x2580_0000  # arty_rx_eth_top's FREQ_WORD default (tb/cocotb/run.py leaves it): 150 kHz
LATE_AT = 200  # datagram before which a second, refused SET_NCO is sent
SOFT_BITS = 4
SHIFT = 10  # ADR 0005
THR64 = 48  # rx_config_pkg
FLYWHEEL = 4  # rx_config_pkg
DATA_BYTES = 892
SAMPLES = 512  # per datagram, docs/protocol.md
GROUP_IP = 0xEF01_0101
PORT = 26400
STATS_PORT = 26401
SENDER_IP = 0xC0A8_0164  # mii.udp_frame's default source
SENDER_MAC = bytes.fromhex("02aabbccddee")
MAC_START_CYCLES = 400  # tb/cocotb/run.py
STATS_PERIOD = 20_000  # tb/cocotb/run.py
DRAIN_CLOCKS = 3_000_000  # after the input: the last window through the Viterbi (~100 clocks/bit) and out
LED_LOCK, LED_ERR = 0b0010, 0b1000


def model_cadus(raw: np.ndarray, cfg) -> tuple[list[CaduOut], object, int]:
    i, q = ddc_fixed.ddc_fixed_rails(raw, cfg)
    re, im = expected(i, q, cfg)
    u = quantize(serial(re, im), SOFT_BITS, SHIFT)
    res = frame_sync_fixed(u, THR64, FLYWHEEL)
    wins, early = windows(u, res)
    return cadus_from_windows(decode_windows(wins), wins), res, early


def status_bytes(c: CaduOut) -> bytes:
    """docs/protocol.md "CADU" bytes 16..23 of the packet."""
    flags = int(c.alternate) | int(c.swap) << 1 | int(c.flywheel) << 2
    return bytes([flags, c.asm_errors, *(0x80 if x < 0 else x for x in c.corrections), 0, 0])


@test(timeout_time=600, timeout_unit="ms")
async def recording_in_cadus_out(dut) -> None:
    raw, cfg, truth = raw_input(FRAMES, SEED)
    raw = raw[: raw.size // (2 * SAMPLES) * 2 * SAMPLES]  # whole datagrams only (gs-replay drops a partial one)
    hz = sync_fixed.coarse_tune_hz(raw, cfg)
    assert ddc_fixed.freq_word(hz, cfg.fs) == FREQ_WORD, "stale FREQ_WORD: update it here and in run.py"
    cfg = replace(cfg, tune_offset_hz=hz)
    cadus, res, early = model_cadus(raw, cfg)
    assert len(cadus) >= 2, "the stimulus must give at least two CADUs"
    n_dgram = raw.size // (2 * SAMPLES)
    datagrams = [k.to_bytes(8, "big") + raw[2 * SAMPLES * k: 2 * SAMPLES * (k + 1)].tobytes() for k in range(n_dgram)]

    start_soon(Clock(dut.clk100_i, 10, unit="ns").start())
    start_soon(Clock(dut.eth_rx_clk_i, 40, unit="ns").start())
    start_soon(Clock(dut.eth_tx_clk_i, 40, unit="ns").start())
    tx: list[bytes] = []
    start_soon(collect_mii_tx(dut.eth_tx_clk_i, dut.eth_txd_o, dut.eth_tx_en_o, tx))
    dut.btn0_i.value = 0
    dut.eth_rx_dv_i.value = 0
    dut.eth_rxd_i.value = 0
    dut.eth_rxerr_i.value = 0
    dut.ck_rst_n_i.value = 0
    await ClockCycles(dut.clk100_i, 5)
    dut.ck_rst_n_i.value = 1
    await ClockCycles(dut.clk100_i, MAC_START_CYCLES + 30)
    assert dut.eth_rstn_o.value == 1, "PHY reset not released"

    await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i,
                   udp_frame(set_nco_command(FREQ_WORD), GROUP_IP, PORT))
    for k, d in enumerate(datagrams):  # back to back: 12-byte inter-frame gap, the line rate
        if k == LATE_AT:
            await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i,
                           udp_frame(set_nco_command(DEFAULT_WORD), GROUP_IP, PORT))
        await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i, udp_frame(d, GROUP_IP, PORT))

    def packets(ptype: int) -> list[bytes]:
        out = []
        for wire in tx:
            f = parse_udp_frame(wire)
            assert (f["dst_mac"], f["dst_ip"], f["dport"]) == (SENDER_MAC, SENDER_IP, STATS_PORT), "misaddressed"
            assert f["payload"][0] in (1, 2), f"packet type {f['payload'][0]}"
            if f["payload"][0] == ptype:
                out.append(f["payload"])
        return out

    for _ in range(DRAIN_CLOCKS // 1000):
        if len(packets(2)) >= len(cadus):
            break
        await ClockCycles(dut.clk100_i, 1000)
    seen = len(packets(1))
    for _ in range(3 * STATS_PERIOD // 1000):  # two more stats packets: the last one counts everything
        if len(packets(1)) >= seen + 2:
            break
        await ClockCycles(dut.clk100_i, 1000)

    got = packets(2)
    assert len(got) == len(cadus), f"{len(got)} CADU packets, the model gives {len(cadus)}"
    for k, (pkt, c) in enumerate(zip(got, cadus, strict=True)):
        typ, ver, n, seq, _ = struct.unpack(">BBHIQ", pkt[:16])
        assert (typ, ver, n, seq, len(pkt)) == (2, 1, 1032, k, 1048), f"CADU packet {k} header"
        assert pkt[16:24] == status_bytes(c), f"CADU {k}: status differs from the model"
        assert pkt[24:] == bytes(c.data), f"CADU {k}: bytes differ from the model"
    good = sum(bytes(c.data[:4]) == ASM_BYTES and bytes(c.data[4: 4 + DATA_BYTES]) in truth for c in cadus)

    stats = [parse_stats(p) for p in packets(1)]
    assert [s.pkt_seq for s in stats] == list(range(len(stats))), "stats pkt_seq not consecutive from 0"
    last = stats[-1]
    assert len(last.fields) == len(FIELDS) == 29
    want = {"ingest_ok": n_dgram, "eth_ok": n_dgram + 2, "udp_ok": n_dgram + 2, "ddc_out": n_dgram * SAMPLES // 4,
            "cadus_sent": len(cadus), "fs_locked": 1, "fs_dropped": res.dropped, "fs_slips": res.slips,
            "fs_early": early, "nco_word": FREQ_WORD, "ctrl_ok": 1, "ctrl_bad": 1}
    for name in FIELDS:
        if name == "rx_fifo_hwm":
            continue
        assert last.fields[name] == want.get(name, 0), f"stats {name} = {last.fields[name]}, want {want.get(name, 0)}"
    led = int(dut.led_o.value)
    assert led & LED_ERR == 0 and led & LED_LOCK, f"LEDs {led:04b}: error lit or frame sync not locked"

    if os.environ.get("CAPTURE_DIR"):
        capture(Path(os.environ["CAPTURE_DIR"]), got, packets(1))
    hwm = last.fields["rx_fifo_hwm"]
    dut._log.info("%d datagrams at line rate; %d CADU packets bit-exact with the model, %d of %d a frame sent; %d "
                  "stats packets; eth_rx FIFO high-water %d B; NCO word 0x%08X (coarse estimate %.1f Hz)", n_dgram,
                  len(got), good, len(cadus), len(stats), hwm, FREQ_WORD, hz)
    if os.environ.get("WRITE_RESULTS") == "1":
        from analysis.common import write_result

        verilator = subprocess.run(["verilator", "--version"], capture_output=True, text=True).stdout.split()[1]
        write_result(
            "rx_top_rtl_decode",
            ["datagrams", "replay_speed_x", "cadus", "bytes_checked", "mismatches", "cadus_matching_sent",
             "stats_packets", "eth_ovf_lost", "ingest_lost", "rx_fifo_hwm_bytes", "freq_word"],
            [[n_dgram, 5.69, len(got), 1048 * len(got), 0, good, len(stats), 0, 0, hwm, f"0x{FREQ_WORD:08X}"]],
            f"seed {SEED} in tb/cocotb/test_arty_rx_eth_top_full.py via sync_chain.raw_input() ({FRAMES} CADUs of "
            "OQPSK at 6 dB Eb/N0, 151 kHz + 30 Hz/s, 0.37 symbol late, 20 ppm clock, cu8), as replay datagrams over "
            "MII at the 100 Mb/s line rate; arty_rx_eth_top from reset",
            command="make rx-top-rtl-results",
            tools=f"Verilator {verilator}, cocotb {cocotb.__version__}",
        )
    assert good == len(cadus), f"{len(cadus) - good} CADUs are no frame sent"


def capture(out: Path, cadu_pkts: list[bytes], stats_pkts: list[bytes]) -> None:
    """Save packets as the RTL sent them (UDP payloads) for the C++ parser tests (gs/tests/board_packets_test.cpp),
    with the values the reference parsers (scripts/board_rx.py, scripts/board_stats.py) read from them: every CADU
    packet, the first two stats packets and the last."""
    from scripts.board_rx import parse_cadu

    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for k, pkt in enumerate(cadu_pkts):
        c = parse_cadu(pkt)
        name = f"cadu_{k}.bin"
        (out / name).write_bytes(pkt)
        flags = int(c.alternate) | int(c.swap) << 1 | int(c.flywheel) << 2
        rs = " ".join(str(x) for x in c.corrections)
        lines.append(f"{name} cadu {c.pkt_seq} {c.uptime} {flags} {c.asm_errors} {rs}")
    for pkt in [*stats_pkts[:2], stats_pkts[-1]]:
        st = parse_stats(pkt)
        name = f"stats_{st.pkt_seq}.bin"
        (out / name).write_bytes(pkt)
        vals = " ".join(str(st.fields[f]) for f in FIELDS)
        lines.append(f"{name} stats {st.pkt_seq} {st.uptime} {len(FIELDS)} {vals}")
    (out / "expected.txt").write_text("\n".join(lines) + "\n")


RESTART_AT = 300  # datagram index during whose transfer the MAC restart is forced


@test(timeout_time=600, timeout_unit="ms")
async def mac_restart_mid_replay(dut) -> None:
    """A MAC restart (request 0005 stopgap) in the middle of a replay resets the whole receiver; it must resume.

    Why it matters: on the board the reorder-ingest bitstream broke in 5 of 8 replays (docs/log.md 2026-11-08) with
    ingest_lost ~ the replay's seq, the signature of an ingest reset to head 0 mid-replay. After the restart the
    ingest must skip the seqs it will never see (lost = first complete seq after the restart), release from there in
    order, and the receiver must decode what follows from a cold start bit-exactly; every packet stays well formed.
    """
    from cocotb.handle import Force, Release

    raw, cfg, _ = raw_input(FRAMES, SEED)
    raw = raw[: raw.size // (2 * SAMPLES) * 2 * SAMPLES]
    hz = sync_fixed.coarse_tune_hz(raw, cfg)
    cfg = replace(cfg, tune_offset_hz=hz)
    n_dgram = raw.size // (2 * SAMPLES)
    datagrams = [k.to_bytes(8, "big") + raw[2 * SAMPLES * k: 2 * SAMPLES * (k + 1)].tobytes() for k in range(n_dgram)]

    start_soon(Clock(dut.clk100_i, 10, unit="ns").start())
    start_soon(Clock(dut.eth_rx_clk_i, 40, unit="ns").start())
    start_soon(Clock(dut.eth_tx_clk_i, 40, unit="ns").start())
    tx: list[bytes] = []
    start_soon(collect_mii_tx(dut.eth_tx_clk_i, dut.eth_txd_o, dut.eth_tx_en_o, tx))
    dut.btn0_i.value = 0
    dut.eth_rx_dv_i.value = 0
    dut.eth_rxd_i.value = 0
    dut.eth_rxerr_i.value = 0
    dut.ck_rst_n_i.value = 0
    await ClockCycles(dut.clk100_i, 5)
    dut.ck_rst_n_i.value = 1
    await ClockCycles(dut.clk100_i, MAC_START_CYCLES + 30)
    await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i,
                   udp_frame(set_nco_command(FREQ_WORD), GROUP_IP, PORT))

    async def restart() -> None:
        await ClockCycles(dut.clk100_i, 2000)  # ~ a quarter into the datagram's 8,300-clock transfer
        dut.fifo_level.value = Force(4095)
        await ClockCycles(dut.clk100_i, 4)
        dut.fifo_level.value = Release()

    for k, d in enumerate(datagrams):
        if k == RESTART_AT:
            start_soon(restart())
        await send_mii(dut.eth_rx_clk_i, dut.eth_rxd_i, dut.eth_rx_dv_i, udp_frame(d, GROUP_IP, PORT))
    for _ in range(DRAIN_CLOCKS // 1000):
        await ClockCycles(dut.clk100_i, 1000)

    # After the restart the receiver starts cold on the first datagram that arrives whole: RESTART_AT is cut.
    first = RESTART_AT + 1
    cadus, res, early = model_cadus(raw[2 * SAMPLES * first:], cfg)
    assert cadus, "the stimulus after the restart must give at least one CADU"
    frames = [parse_udp_frame(w)["payload"] for w in tx]
    got = [p for p in frames if p[0] == 2]
    assert len(got) == len(cadus), f"{len(got)} CADU packets after the restart, the model gives {len(cadus)}"
    for k, (pkt, c) in enumerate(zip(got, cadus, strict=True)):
        typ, ver, n, seq, _ = struct.unpack(">BBHIQ", pkt[:16])
        assert (typ, ver, n, seq, len(pkt)) == (2, 1, 1032, k, 1048), f"CADU packet {k} header"
        assert pkt[16:24] == status_bytes(c), f"CADU {k}: status differs from the model"
        assert pkt[24:] == bytes(c.data), f"CADU {k}: bytes differ from the model"
    last = parse_stats([p for p in frames if p[0] == 1][-1])
    n_after = n_dgram - first
    # Counters restart with the MAC (ctrl_ok too); mac_restarts and the NCO word do not: the CADUs after the restart
    # decode only with the word set before it. The cut datagram ends as an rx_err frame (MII abort).
    want = {"ingest_ok": n_after, "ingest_gap": 1, "ingest_lost": first, "eth_ok": n_after, "eth_rx_err": 1,
            "udp_ok": n_after, "ddc_out": n_after * SAMPLES // 4, "mac_restarts": 1, "cadus_sent": len(cadus),
            "fs_locked": 1, "fs_dropped": res.dropped, "fs_slips": res.slips, "fs_early": early,
            "nco_word": FREQ_WORD}
    for name in FIELDS:
        if name == "rx_fifo_hwm":
            continue
        assert last.fields[name] == want.get(name, 0), f"stats {name} = {last.fields[name]}, want {want.get(name, 0)}"
    dut._log.info("MAC restart in datagram %d: %d skipped as lost, %d CADU packets after it bit-exact with the model",
                  RESTART_AT, first, len(got))
