"""Build and run the cocotb regression with Verilator: python tb/cocotb/run.py [test_module ...]"""

from __future__ import annotations

import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

ROOT = Path(__file__).resolve().parents[2]

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
    "test_arty_ddc_rom_top": (
        "arty_ddc_rom_top",
        ["rtl/lib/reset_sync.sv", "rtl/lib/cdc_sync_bit.sv", "rtl/io/iq_rom_source.sv", "rtl/io/capture_dump.sv",
         "rtl/io/uart_tx.sv"]
        + [f"rtl/ddc/{f}.sv" for f in ("ddc_ingest", "ddc_nco_mixer", "ddc_cic", "ddc_comp_fir", "ddc_top")]
        + ["rtl/top/arty_ddc_rom_top.sv"],
        [{
            "N_SAMPLES": 2048,  # tb/cocotb/ddc_board.py N_SIM
            "CLKS_PER_BIT": 8,  # test_arty_ddc_rom_top.py CLKS_PER_BIT
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


def main(names: list[str]) -> int:
    failed = 0
    # The tests import the bit-true model from the repo root. The runner builds the simulator's PYTHONPATH from
    # sys.path, so the paths go there. results.xml goes into the build directory.
    sys.path[:0] = [str(ROOT), str(ROOT / "tb" / "cocotb")]
    for name in names or list(TESTS):
        top, srcs, param_sets = TESTS[name]
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
                build_args=["--assert", "-Wall"],
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
