"""Build and run the cocotb regression with Verilator: python tb/cocotb/run.py [--slow | --full | test_module ...]

No arguments runs TESTS except SLOW (make sim, < 5 min). --slow runs SLOW (make sim-slow, part of make ci).
--full runs FULL_TESTS, the long runs (make sim-full)."""

from __future__ import annotations

import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

ROOT = Path(__file__).resolve().parents[2]

SYNC_TOP_SRCS = ["rtl/ddc/ddc_comp_fir.sv"] + [f"rtl/sync/{f}.sv" for f in ("sync_rrc", "sync_agc", "sync_costas",
                                                                           "sync_timing", "sync_top")]
SYNC_TOP_PARAMS: dict[str, int | str] = {
    "RRC_TAP_FILE": f'"{ROOT / "rtl/sync/rrc_taps.mem"}"',
    "NCO_LUT_FILE": f'"{ROOT / "rtl/ddc/nco_lut.mem"}"',
}

FRAMESYNC_SRCS = [f"rtl/fec/{f}.sv" for f in ("fec_fs_correlator", "fec_fs_fsm", "fec_fs_window", "fec_framesync")]
FRAMESYNC_PARAMS: dict[str, int | str] = {"PATTERN_FILE": f'"{ROOT / "rtl/fec/asm_patterns.mem"}"'}

# fpga-rs-core at its tag (submodule rtl/rs); the package first
RS_SRCS = [f"rtl/rs/rtl/{f}.sv" for f in ("rs_gf_pkg", "rs_syndrome", "rs_ribm", "rs_chien_forney", "rs_decoder")]

# test module -> (toplevel, sources, parameter sets)
NCO_LUT = {"LUT_FILE": f'"{ROOT / "rtl/ddc/nco_lut.mem"}"'}

TESTS: dict[str, tuple[str, list[str], list[dict[str, int | str]]]] = {
    "test_ddc_ingest": ("ddc_ingest", ["rtl/ddc/ddc_ingest.sv"], [{}]),
    "test_ddc_nco_mixer": ("ddc_nco_mixer", ["rtl/ddc/ddc_nco_mixer.sv"], [NCO_LUT]),
    "test_ddc_cic": ("ddc_cic", ["rtl/ddc/ddc_cic.sv"], [{}]),
    "test_ddc_comp_fir": (
        "ddc_comp_fir",
        ["rtl/ddc/ddc_comp_fir.sv"],
        [{"TAP_FILE": f'"{ROOT / "rtl/ddc/comp_fir_taps.mem"}"'}],
    ),
    "test_sync_rrc": (
        "sync_rrc",
        ["rtl/ddc/ddc_comp_fir.sv", "rtl/sync/sync_rrc.sv"],
        [{"TAP_FILE": f'"{ROOT / "rtl/sync/rrc_taps.mem"}"'}],
    ),
    "test_sync_agc": ("sync_agc", ["rtl/sync/sync_agc.sv"], [{}]),
    "test_sync_costas": ("sync_costas", ["rtl/sync/sync_costas.sv"], [NCO_LUT]),
    "test_sync_timing": ("sync_timing", ["rtl/sync/sync_timing.sv"], [{}]),
    "test_sync_top": ("sync_top", SYNC_TOP_SRCS, [SYNC_TOP_PARAMS]),
    "test_fec_bm": ("fec_bm", ["rtl/fec/fec_bm.sv"], [{}]),
    "test_fec_acs": ("fec_acs", ["rtl/fec/fec_acs.sv"], [{}]),
    "test_fec_acs_array": ("fec_acs_array", [f"rtl/fec/{f}.sv" for f in ("fec_bm", "fec_acs", "fec_acs_array")], [{}]),
    "test_fec_traceback": ("fec_traceback", ["rtl/fec/fec_traceback.sv"], [{}]),
    "test_fec_viterbi": (
        "fec_viterbi",
        [f"rtl/fec/{f}.sv" for f in ("fec_bm", "fec_acs", "fec_acs_array", "fec_traceback", "fec_viterbi")],
        [{}],
    ),
    "test_fec_soft_quant": ("fec_soft_quant", ["rtl/fec/fec_soft_quant.sv"], [{}]),
    "test_fec_frame_extract": ("fec_frame_extract", ["rtl/fec/fec_frame_extract.sv"], [{}]),
    "test_fec_cadu": ("fec_cadu", [*RS_SRCS, "rtl/fec/fec_cadu.sv"], [{}]),
    "test_fec_framesync": ("fec_framesync", FRAMESYNC_SRCS, [FRAMESYNC_PARAMS]),
    "test_fec_framesync_fifo": ("fec_framesync", FRAMESYNC_SRCS, [{**FRAMESYNC_PARAMS, "DEPTH": 131072}]),
    "test_stats_packet": ("stats_packet", ["rtl/io/stats_packet.sv"], [{"N_FIELDS": 18, "PERIOD": 60}]),
    "test_iq_udp_ingest": ("iq_udp_ingest", ["rtl/io/iq_udp_ingest.sv"], [{"DEPTH": 1024}, {"DEPTH": 512}]),
    "test_arty_ddc_rom_top": (
        "arty_ddc_rom_top",
        ["rtl/lib/reset_sync.sv", "rtl/lib/cdc_sync_bit.sv", "rtl/io/iq_rom_source.sv", "rtl/io/capture_dump.sv",
         "rtl/io/uart_tx.sv"]
        + [f"rtl/ddc/{f}.sv" for f in ("ddc_ingest", "ddc_nco_mixer", "ddc_cic", "ddc_comp_fir", "ddc_top")]
        + ["rtl/top/arty_ddc_rom_top.sv"],
        [{
            "N_SAMPLES": 2048,  # tb/cocotb/ddc_board.py N_SIM
            "CLKS_PER_BIT": 8,  # tb/cocotb/ddc_board.py CLKS_PER_BIT
            "NCO_LUT_FILE": f'"{ROOT / "rtl/ddc/nco_lut.mem"}"',
            "COMP_TAP_FILE": f'"{ROOT / "rtl/ddc/comp_fir_taps.mem"}"',
        }],
    ),
    "test_arty_ddc_eth_top": (
        "arty_ddc_eth_top",
        ["tb/models/MMCME2_BASE.sv", "tb/models/BUFG.sv", "tb/models/ODDR.sv", "rtl/lib/xilinx/clk_gen_eth.sv",
         "rtl/lib/reset_sync.sv", "rtl/lib/cdc_sync_bit.sv", "rtl/io/iq_udp_ingest.sv", "rtl/io/capture_dump.sv",
         "rtl/io/uart_tx.sv", "rtl/io/stats_packet.sv"]
        + [f"rtl/eth/rtl/{f}.sv" for f in ("async_fifo", "mii_rx", "rx_ovf_guard", "crc32_d8", "eth_fcs_check",
                                           "frame_buffer", "eth_rx", "udp_rx", "udp_tx", "mii_tx", "eth_tx")]
        + [f"rtl/ddc/{f}.sv" for f in ("ddc_ingest", "ddc_nco_mixer", "ddc_cic", "ddc_comp_fir", "ddc_top")]
        + ["rtl/top/arty_ddc_eth_top.sv"],
        [{
            "N_OUT": 512,  # tb/cocotb/ddc_board.py N_SIM / 4
            "CLKS_PER_BIT": 8,  # tb/cocotb/ddc_board.py CLKS_PER_BIT
            "PHY_RST_CYCLES": 100,
            "MAC_START_CYCLES": 400,  # test_arty_ddc_eth_top.py MAC_START_CYCLES
            "STATS_PERIOD": 20000,  # test_arty_ddc_eth_top.py STATS_PERIOD
            "NCO_LUT_FILE": f'"{ROOT / "rtl/ddc/nco_lut.mem"}"',
            "COMP_TAP_FILE": f'"{ROOT / "rtl/ddc/comp_fir_taps.mem"}"',
        }],
    ),
    "test_ddc_top": (
        "ddc_top",
        [f"rtl/ddc/{f}.sv" for f in ("ddc_ingest", "ddc_nco_mixer", "ddc_cic", "ddc_comp_fir", "ddc_top")],
        [{
            "NCO_LUT_FILE": f'"{ROOT / "rtl/ddc/nco_lut.mem"}"',
            "COMP_TAP_FILE": f'"{ROOT / "rtl/ddc/comp_fir_taps.mem"}"',
        }],
    ),
}


# In TESTS but left out of make sim to keep it under 5 min; make ci still runs them (make sim-slow).
SLOW = ["test_fec_framesync"]  # ~100 s


# Long runs, make sim-full only (CLAUDE.md §6: make sim stays under 5 min)
FULL_TESTS: dict[str, tuple[str, list[str], list[dict[str, int | str]]]] = {
    "test_sync_top_full": ("sync_top", SYNC_TOP_SRCS, [SYNC_TOP_PARAMS]),
    "test_rx_chain_full": (
        "rx_chain",
        SYNC_TOP_SRCS
        + ["rtl/fec/fec_soft_quant.sv"]
        + FRAMESYNC_SRCS
        + [f"rtl/fec/{f}.sv" for f in ("fec_bm", "fec_acs", "fec_acs_array", "fec_traceback", "fec_viterbi")]
        + ["rtl/top/rx_chain.sv"],
        [{**SYNC_TOP_PARAMS, **FRAMESYNC_PARAMS}],
    ),
}


def main(names: list[str]) -> int:
    failed = 0
    if names == ["--full"]:
        names = list(FULL_TESTS)
    elif names == ["--slow"]:
        names = SLOW
    elif not names:
        names = [t for t in TESTS if t not in SLOW]
    # The tests import the bit-true model from the repo root. The runner builds the simulator's PYTHONPATH from
    # sys.path, so the paths go there. results.xml goes into the build directory.
    sys.path[:0] = [str(ROOT), str(ROOT / "tb" / "cocotb")]
    for name in names:
        top, srcs, param_sets = {**TESTS, **FULL_TESTS}[name]
        for params in param_sets:
            tag = "_".join(f"{k}{v}" for k, v in params.items() if isinstance(v, int)) or "default"
            build_dir = ROOT / "build" / "sim" / f"{name}_{tag}"
            if name == "test_arty_ddc_rom_top":  # the ROM image must exist before $readmemh at elaboration
                from ddc_board import prepare, rom_path

                prepare(build_dir)
                params = {**params, "ROM_FILE": f'"{rom_path(build_dir)}"'}
            runner = get_runner("verilator")
            runner.build(
                sources=[ROOT / s for s in srcs],
                hdl_toplevel=top,
                parameters=params,
                build_args=["--assert", "-Wall"]
                + ([str(ROOT / "tb/cocotb/eth_core.vlt")] if any(x.startswith("rtl/eth/") for x in srcs) else []),
                build_dir=build_dir,
                always=True,
            )
            results = runner.test(
                hdl_toplevel=top,
                test_module=name,
                test_dir=build_dir,
                build_dir=build_dir,
            )
            _, fails = get_results(results)
            failed += fails
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
