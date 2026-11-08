"""arty_rx_eth_top end to end (make sim-full): a recording in as MII nibbles, CADU and stats packets out of MII TX.

Why it matters: on the board the only evidence is the UDP packets that come back. This test sends a synthetic
recording as replay datagrams (docs/protocol.md "IQ replay") at the 100 Mb/s line rate, the fastest gs-replay can
send (5.69x real time), into a board top built with the NCO word the host's coarse estimate gives for it (ADR 0002),
and parses what leaves MII TX by docs/protocol.md alone. Each type 2 packet must carry the bit-true model chain's
CADU and status (raw -> ddc_fixed -> sync -> frame sync -> Viterbi -> cadu_fixed), in order with consecutive
pkt_seq, interleaved with stats packets by pkt_arb2 without either being cut. The last stats packet must report every
datagram received with no loss anywhere (eth_rx overflow, ingest gaps) and the frame sync's counters equal to the
model's: at line rate the ingest cannot push back on the sender, so a chain slower than the replay shows up as
eth_ovf_lost, here and on the board. The per-block and chain tests cover the decoding itself; what this adds is the
DDC -> rx_chain link, the parameter wiring (NCO word, rx_config_pkg), the packet path and the counters. The loops
start cold, so frame 0 is lost to pull-in.
"""

from __future__ import annotations

import os
import struct
import subprocess
from dataclasses import replace

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
from scripts.board_stats import FIELDS, parse_stats

FRAMES = 5
SEED = 20
FREQ_WORD = 0x25C0_EE00  # tb/cocotb/run.py; checked below against the coarse estimate of this stimulus
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

    for d in datagrams:  # back to back: 12-byte inter-frame gap, the line rate
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
    assert len(last.fields) == len(FIELDS) == 26
    want = {"ingest_ok": n_dgram, "eth_ok": n_dgram, "udp_ok": n_dgram, "ddc_out": n_dgram * SAMPLES // 4,
            "cadus_sent": len(cadus), "fs_locked": 1, "fs_dropped": res.dropped, "fs_slips": res.slips,
            "fs_early": early}
    for name in FIELDS:
        if name == "rx_fifo_hwm":
            continue
        assert last.fields[name] == want.get(name, 0), f"stats {name} = {last.fields[name]}, want {want.get(name, 0)}"
    led = int(dut.led_o.value)
    assert led & LED_ERR == 0 and led & LED_LOCK, f"LEDs {led:04b}: error lit or frame sync not locked"

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
