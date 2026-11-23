"""Regenerate plots from data/results/ (CLAUDE.md §11.2). Never hand-edit the output."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from model.channel import TxConfig, apply_carrier, awgn, modulate, noise_sigma
from model.coding import build_cadus, encode_stream
from model.receiver import RxConfig, coarse_frequency, costas, ddc, matched_filter, oqpsk_timing

ROOT = Path(__file__).parents[1]
RESULTS = ROOT / "data" / "results"
MEDIA = ROOT / "docs" / "media"
DATE = "2026-11-02"
# Reference palette, fixed order, validated with the dataviz skill's script.
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "#fcfcfb",
            "axes.facecolor": "#fcfcfb",
            "axes.edgecolor": MUTED,
            "axes.labelcolor": INK,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "lines.linewidth": 2,
            "lines.markersize": 8,
            "font.size": 11,
            "legend.frameon": False,
        }
    )


def _rows(name: str) -> list[dict[str, str]]:
    with (RESULTS / f"{name}.csv").open() as f:
        return list(csv.DictReader(f))


def ber_plot() -> None:
    curves: dict[str, list[tuple[float, float, float, int]]] = defaultdict(list)
    for r in _rows("ber_awgn"):
        curves[r["curve"]].append((float(r["ebn0_db"]), float(r["ber"]), float(r["theory"]), int(r["errors"])))
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for label, curve, colour in (
        ("Uncoded OQPSK, waveform", "uncoded_waveform", BLUE),
        ("Viterbi soft, K=7 r=1/2", "viterbi_soft", ORANGE),
        ("Viterbi, after NRZ-M", "viterbi_after_nrzm", AQUA),
    ):
        pts = curves[curve]
        solid = [p for p in pts if p[3] >= 100 and p[1] > 0]
        ax.semilogy([p[0] for p in solid], [p[1] for p in solid], "o", color=colour, label=label)
    uncoded = curves["uncoded_waveform"]
    ax.semilogy([p[0] for p in uncoded], [p[2] for p in uncoded], color=BLUE, label="Theory: Q(sqrt(2Eb/N0))")
    coded = [p for p in curves["viterbi_soft"] if p[2] < 0.5]
    ax.semilogy([p[0] for p in coded], [p[2] for p in coded], color=ORANGE, label="Theory: union bound")
    ax.set_xlabel("Eb/N0 (dB)")
    ax.set_ylabel("Bit error rate")
    ax.set_ylim(1e-7, 1)
    ax.set_title("Model BER against theory, synthetic AWGN", color=INK, loc="left")
    ax.legend()
    fig.tight_layout()
    fig.savefig(MEDIA / f"{DATE}_phase-a_ber-vs-theory.png", dpi=150)
    plt.close(fig)


def fer_plot() -> None:
    sent: dict[float, int] = defaultdict(int)
    good: dict[float, int] = defaultdict(int)
    for r in _rows("fer_full_chain"):
        sent[float(r["ebn0_db"])] += int(r["frames_sent"])
        good[float(r["ebn0_db"])] += int(r["frames_good"])
    xs = sorted(sent)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(xs, [100 * good[x] / sent[x] for x in xs], "o-", color=BLUE)
    ax.set_xlabel("Eb/N0 (dB)")
    ax.set_ylabel("Frames recovered intact (% of sent)")
    ax.axhline(95, color=MUTED, linewidth=1, linestyle="--")
    ax.annotate(
        "Ceiling 95%: the first and last of each 40-frame run have no Viterbi margin",
        (6, 95),
        xytext=(0, -16),
        textcoords="offset points",
        ha="right",
        color=MUTED,
        fontsize=9,
    )
    ax.set_ylim(0, 100)
    ax.set_title("Full float receiver: samples to RS output, with Doppler and timing offset", color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(MEDIA / f"{DATE}_phase-a_full-chain-frames.png", dpi=150)
    plt.close(fig)


def constellation_plot() -> None:
    """Before and after carrier lock. Generated from the model directly (seed fixed)."""
    _, on_air = build_cadus(10, 7)
    tx = TxConfig(timing_offset_sym=0.37)
    x = awgn(apply_carrier(modulate(encode_stream(on_air), tx), tx.fs, 1000.0, 0.0, 0.7), noise_sigma(9.0, tx.fs), 7)
    cfg = RxConfig()
    fs2 = cfg.fs / cfg.decimation
    mf = matched_filter(ddc(x, cfg), fs2, cfg.rrc_span)
    unlocked = oqpsk_timing(mf, fs2, cfg.timing_kp, cfg.timing_ki)
    t = np.arange(mf.size) / fs2
    derotated = mf * np.exp(-2j * np.pi * coarse_frequency(mf, fs2, cfg) * t)
    locked = oqpsk_timing(costas(derotated, cfg.costas_bw, math.pi / 4)[0], fs2, cfg.timing_kp, cfg.timing_ki)
    fig, axes = plt.subplots(1, 2, figsize=(9, 4.6))
    for ax, y, title in ((axes[0], unlocked, "Before carrier lock"), (axes[1], locked, "After carrier lock")):
        start = (y.size // 4) * 2  # even, so each real strobe pairs with the next imaginary strobe
        pts = y[start : start + 6000]
        pairs = pts.real[0::2][:-1] + 1j * pts.imag[1::2][: pts.real[0::2].size - 1]
        ax.plot(pairs.real, pairs.imag, ".", markersize=2, color=BLUE, alpha=0.5)
        ax.set_aspect("equal")
        ax.set_xlim(-2.5, 2.5)
        ax.set_ylim(-2.5, 2.5)
        ax.set_xlabel("I (rail-normalized)")
        ax.set_ylabel("Q (rail-normalized)")
        ax.set_title(title, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(MEDIA / f"{DATE}_phase-a_constellation.png", dpi=150)
    plt.close(fig)


def soft_width_plot() -> None:
    curves: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for r in _rows("soft_width_ber"):
        if r["upper_bound"] == "False":
            curves[int(r["soft_bits"])].append((float(r["ebn0_db"]), float(r["ber"])))
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for bits, label, colour in ((0, "Unquantized soft", BLUE), (4, "4-bit soft", ORANGE), (3, "3-bit soft", AQUA)):
        pts = sorted(curves[bits])
        ax.semilogy([p[0] for p in pts], [p[1] for p in pts], "o-", color=colour, label=label)
    ax.axhline(1e-5, color=MUTED, linewidth=1, linestyle="--")
    ax.set_xlabel("Eb/N0 (dB)")
    ax.set_ylabel("Bit error rate after Viterbi (before NRZ-M)")
    ax.set_title("Soft-decision width, K=7 r=1/2, quantizer step 1/4 of rail rms", color=INK, loc="left")
    ax.legend()
    fig.tight_layout()
    fig.savefig(MEDIA / "2026-11-04_phase-a_soft-width-ber.png", dpi=150)
    plt.close(fig)


def traceback_plot() -> None:
    rows = _rows("traceback_depth")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharey=False)
    for ax, ebn0 in zip(axes, ("3.0", "4.0"), strict=True):
        pts = [r for r in rows if r["ebn0_db"] == ebn0]
        full = next(float(r["ber"]) for r in pts if r["start"] == "block")
        for start, label, colour in (("best", "From best state", BLUE), ("zero", "From state 0", ORANGE)):
            curve = sorted((int(r["depth"]), float(r["ber"])) for r in pts if r["start"] == start)
            ax.semilogy([c[0] for c in curve], [c[1] for c in curve], "o-", color=colour, label=label)
        ax.axhline(full, color=MUTED, linewidth=1, linestyle="--", label="Full-block traceback")
        ax.set_xlabel("Traceback depth (bits)")
        ax.set_ylabel("BER after Viterbi")
        ax.set_title(f"Eb/N0 = {ebn0} dB, 4-bit soft", color=INK, loc="left")
        ax.legend()
    fig.tight_layout()
    fig.savefig(MEDIA / "2026-11-04_phase-a_traceback-depth.png", dpi=150)
    plt.close(fig)


def ddc_spectrum_plot() -> None:
    """Board DDC input (ROM snippet) vs. output (captured from the Arty over UART): data/results/ddc_board_spectrum."""
    rows = _rows("ddc_board_spectrum")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    panels = (
        ("before", "Before: cu8 snippet in BRAM, 1.024 MS/s", BLUE),
        ("after", "After: DDC output from the Arty, 256 kS/s", ORANGE),
    )
    for ax, (stage, title, colour) in zip(axes, panels, strict=True):
        f = np.array([float(r["freq_hz"]) for r in rows if r["stage"] == stage]) / 1e3
        p = np.array([float(r["psd_db_per_hz"]) for r in rows if r["stage"] == stage])
        ax.plot(f, p - p.max(), color=colour, linewidth=1.2)
        ax.set_xlim(f.min(), f.max())
        ax.set_ylim(-70, 5)
        ax.set_xlabel("Frequency (kHz)")
        ax.set_ylabel("PSD (dB relative to peak)")
        ax.set_title(title, color=INK, loc="left")
    for ax, stage, labels in (
        (axes[0], "before", ((151e3, "signal, +151 kHz"), (0.0, "DC offset"))),
        (axes[1], "after", ((1e3, "signal, +1 kHz\n(DC offset removed)"),)),
    ):
        f = np.array([float(r["freq_hz"]) for r in rows if r["stage"] == stage])
        p = np.array([float(r["psd_db_per_hz"]) for r in rows if r["stage"] == stage])
        p -= p.max()
        for f0, text in labels:
            k = int(np.argmin(np.abs(f - f0)))
            ax.annotate(text, xy=(f[k] / 1e3, p[k]), xytext=(8, 10), textcoords="offset points", color=MUTED)
    fig.tight_layout()
    fig.savefig(MEDIA / "2026-11-04_phase-b_ddc-spectrum-board.png", dpi=150)
    plt.close(fig)


def ddc_ila_plot() -> None:
    """DDC output captured on the Arty by the ILA vs. the bit-true model: data/results/ddc_board_ila{,_iq}."""
    rows = _rows("ddc_board_ila_iq")
    summary = _rows("ddc_board_ila")[0]
    t = np.array([float(r["t_us"]) for r in rows]) / 1e3
    bi, bq, mi, mq = (np.array([int(r[k]) for r in rows]) for k in ("board_i", "board_q", "model_i", "model_q"))
    fig, (ax, sc) = plt.subplots(1, 2, figsize=(11, 4.4), gridspec_kw={"width_ratios": [2.2, 1]})
    w = t <= 0.5  # first 0.5 ms (128 outputs) in the trace; all rows in the scatter
    ax.plot(t[w], bi[w], color=BLUE, linewidth=1.2, label="I, board (ILA)")
    ax.plot(t[w], bq[w], color=ORANGE, linewidth=1.2, label="Q, board (ILA)")
    ax.plot(t[w], mi[w], "o", color=INK, markersize=2.5, label="bit-true model")
    ax.plot(t[w], mq[w], "o", color=INK, markersize=2.5)
    ax.set_xlim(0, 0.5)
    ax.set_xlabel("Time (ms) at 256 kS/s")
    ax.set_ylabel("DDC output (s16 counts)")
    ax.set_title(
        f"ILA capture: {int(summary['outputs']):,} outputs, {int(summary['mismatches'])} differ from the model",
        color=INK,
        loc="left",
    )
    ax.legend(loc="upper right", fontsize=8, ncol=3)
    sc.plot(bi, bq, ".", color=BLUE, markersize=2.5)
    lim = 1.1 * max(np.abs(bi).max(), np.abs(bq).max())
    sc.set_xlim(-lim, lim)
    sc.set_ylim(-lim, lim)
    sc.set_aspect("equal")
    sc.set_xlabel("I")
    sc.set_ylabel("Q")
    sc.set_title(f"I/Q, first {len(t)} outputs (no sync yet)", color=INK, loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(MEDIA / "2026-11-04_phase-b_ddc-ila-baseband.png", dpi=150)
    plt.close(fig)


def lock_time_plot() -> None:
    """Costas pull-in of the bit-true chain (RTL bit-exact) from reset: data/results/sync_lock_costas."""
    rows = _rows("sync_lock_costas")
    fig, ax = plt.subplots(figsize=(8, 5))
    by_res: dict[float, list[float]] = defaultdict(list)
    for r in rows:
        by_res[float(r["residual_hz"])].append(float(r["lock_time_s"]) * 1000)
    res = sorted(by_res)
    locked = [(f, t) for f in res for t in by_res[f] if not math.isnan(t)]
    ax.plot([p[0] for p in locked], [p[1] for p in locked], "o", color=BLUE, alpha=0.6, label="One seed")
    med = [(f, float(np.median(by_res[f]))) for f in res if not any(math.isnan(t) for t in by_res[f])]
    ax.plot([m[0] for m in med], [m[1] for m in med], "-", color=ORANGE, label="Median (every seed locked)")
    top = max(p[1] for p in locked) * 1.15
    misses = [f for f in res for t in by_res[f] if math.isnan(t)]
    if misses:
        ax.plot(misses, [top] * len(misses), "x", color=INK, label="No lock by end of run")
    ax.set_xlabel("Carrier error left after the coarse estimate (Hz)")
    ax.set_ylabel("Lock time from reset (ms)")
    ax.set_title("Costas pull-in, bit-true chain = RTL, 6 dB, 30 Hz/s ramp", color=INK, loc="left")
    ax.legend()
    fig.tight_layout()
    fig.savefig(MEDIA / "2026-11-05_phase-c_lock-time.png", dpi=150)
    plt.close(fig)


def doppler_plot() -> None:
    """Receiver's carrier estimate through closest approach: data/results/sync_doppler_track."""
    rows = _rows("sync_doppler_track")
    t = [float(r["time_s"]) for r in rows]
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 6), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    top.plot(t, [float(r["true_hz"]) for r in rows], color=MUTED, linewidth=4, label="True carrier offset")
    top.plot(
        t, [float(r["estimate_hz"]) for r in rows], color=BLUE, linewidth=1.5, label="Receiver estimate (NCO + Costas)"
    )
    top.set_ylabel("Carrier offset (Hz)")
    top.set_title(
        "Doppler tracking at the pass maximum rate (30 Hz/s), bit-true chain = RTL, 6 dB", color=INK, loc="left"
    )
    top.legend()
    bottom.plot(t, [float(r["error_hz"]) for r in rows], color=ORANGE, linewidth=1.2)
    bottom.set_ylabel("Error (Hz)")
    bottom.set_xlabel("Time from reset (s)")
    fig.tight_layout()
    fig.savefig(MEDIA / "2026-11-05_phase-c_doppler-tracking.png", dpi=150)
    plt.close(fig)


def constellation_gif() -> None:
    """Pull-in from reset on the bit-true chain (RTL bit-exact): a spinning ring that settles into four clusters.

    Generated from the model directly (seed fixed), like constellation_plot(). The DDC is tuned 150 Hz off the
    carrier, as if the coarse estimate had missed by that much (sync_lock_costas.csv: lock in 238-314 ms at 6 dB).
    15 dB rather than 6 so the four clusters read clearly at GIF size.
    """
    from matplotlib.animation import FuncAnimation, PillowWriter

    from analysis.ddc_fixed_study import TUNE_HZ
    from analysis.sync_lock_study import raw_signal
    from model.ddc_fixed import ddc_fixed_rails
    from model.rrc_fixed import rrc_fixed
    from model.sync_fixed import ONE, agc, loop_gains, timing
    from model.sync_fixed import costas as costas_fixed

    raw, _, fs = raw_signal(150.0, 1, frames=4, ebn0_db=15.0)
    cfg = RxConfig(fs=fs, tune_offset_hz=TUNE_HZ)
    i, q = rrc_fixed(*ddc_fixed_rails(raw, cfg), cfg)
    i, q, _ = agc(i, q)
    gains = loop_gains(cfg)
    re, im = timing(*costas_fixed(i, q, gains)[:2], gains)
    pts_i, pts_q = re[0::2] / ONE, im[1::2] / ONE  # each I strobe with the Q strobe half a symbol later
    n = min(pts_i.size, pts_q.size)
    sym_rate = 72_000.0
    window, step, frames = 200, int(0.0015 * sym_rate), 170  # 2.8 ms of symbols, a frame every 1.5 ms, to 258 ms
    fig, ax = plt.subplots(figsize=(4.8, 4.8), dpi=80)
    (dots,) = ax.plot([], [], ".", markersize=3, color=BLUE, alpha=0.6)
    label = ax.text(-2.3, 2.05, "", color=INK)
    ax.set_aspect("equal")
    ax.set_xlim(-2.5, 2.5)
    ax.set_ylim(-2.5, 2.5)
    ax.set_xlabel("I (rail rms = 1)")
    ax.set_ylabel("Q (rail rms = 1)")
    ax.set_title("Lock from reset: 150 Hz off, 15 dB, bit-true chain", color=INK, loc="left", fontsize=10)
    fig.tight_layout()

    def draw(k: int) -> None:
        end = min(n, window + k * step)
        dots.set_data(pts_i[end - window : end], pts_q[end - window : end])
        label.set_text(f"t = {end / sym_rate * 1000:5.0f} ms")

    anim = FuncAnimation(fig, draw, frames=frames)
    anim.save(MEDIA / "2026-11-05_phase-c_constellation-lock.gif", writer=PillowWriter(fps=15))
    plt.close(fig)


def board_ber_plot() -> None:
    """Hardware BER (scripts/ber_board.py) against the model and theory. Points with fewer than 100 errors are
    95% upper bounds, drawn as downward triangles."""
    if not (RESULTS / "ber_board.csv").exists():
        return
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ebn0 = np.arange(0.0, 8.01, 0.25)
    theory = [0.5 * math.erfc(math.sqrt(10 ** (e / 10))) for e in ebn0]
    ax.semilogy(ebn0, theory, color=BLUE, label="Uncoded OQPSK, theory Q(sqrt(2Eb/N0))")
    model = [r for r in _rows("ber_awgn") if r["curve"] == "viterbi_after_nrzm" and int(r["errors"]) >= 100]
    ax.semilogy([float(r["ebn0_db"]) for r in model], [float(r["ber"]) for r in model], "o-", color=ORANGE,
                label="Viterbi + NRZ-M, model (AWGN symbols)")
    board = _rows("ber_board")
    for curve, colour, label in (("viterbi_board", AQUA, "Viterbi + NRZ-M, board (pre-RS)"),
                                 ("viterbi_rs_board", YELLOW, "Viterbi + RS, board (data bytes)")):
        rows = [r for r in board if r["curve"] == curve]
        meas = [r for r in rows if r["ber"]]
        bound = [r for r in rows if not r["ber"] and r["ber_upper95"]]
        ax.semilogy([float(r["ebn0_db"]) for r in meas], [float(r["ber"]) for r in meas], "o", color=colour,
                    label=label)
        if bound:
            ax.semilogy([float(r["ebn0_db"]) for r in bound], [float(r["ber_upper95"]) for r in bound], "v",
                        color=colour, label=f"{label.split(',')[0]}: 95% upper bound, < 100 errors")
    ax.set_xlabel("Eb/N0 per encoder input bit (dB)")
    ax.set_ylabel("Bit error rate")
    ax.set_xlim(0, 8)
    ax.set_ylim(1e-8, 1)
    ax.set_title("Hardware BER: Arty receiver vs. model and theory", color=INK, loc="left")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(MEDIA / "2026-11-08_phase-e_ber-board.png", dpi=150)
    plt.close(fig)


def real_pass_plot() -> None:
    """Float model through the 2026-11-21 pass vs. SatDump: data/results/real_pass_model."""
    rows = [r for r in _rows("real_pass_model") if r["chunk_utc"] != "total"]
    # Chunk start + 15 s, in minutes after 19:00 UTC (the recording starts 19:37:51).
    t = [37 + 51 / 60 + (float(r["chunk_start_s"]) + 15) / 60 for r in rows]
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 6), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    top.plot(t, [int(r["frames_rs_good"]) for r in rows], "o-", color=BLUE, label="Float model, all RS codewords good")
    top.plot(t, [int(r["equal_to_satdump"]) for r in rows], "o-", color=ORANGE, label="Of those, equal to SatDump's")
    top.set_ylabel("Frames per 30 s chunk")
    top.set_ylim(0, 300)
    top.set_title("Meteor-M N2-4, 2026-11-21: this receiver's float model vs. SatDump 1.2.2", color=INK, loc="left")
    top.legend(loc="center left", bbox_to_anchor=(0.5, 0.45))
    # The carrier estimate means something only where frames decoded; elsewhere the loop follows noise.
    locked = [
        (x, float(r["median_carrier_hz"]) / 1e3) for x, r in zip(t, rows, strict=True) if r["frames_rs_good"] != "0"
    ]
    bottom.plot([x for x, _ in locked], [f for _, f in locked], "o-", color=AQUA, markersize=5)
    bottom.set_ylabel("Carrier offset (kHz)")
    bottom.set_xlabel("Minutes after 19:00 UTC")
    fig.tight_layout()
    fig.savefig(MEDIA / "2026-11-21_phase-a_real-pass-model.png", dpi=150)
    plt.close(fig)


def viterbi_ila_plot() -> None:
    """The board's Viterbi path metrics from the ILA (scripts/ila_viterbi.py): each state's metric above the best
    one, step by step. The survivors' metrics stay near zero; the others climb until a step makes them survivors."""
    if not (RESULTS / "viterbi_board_ila_pm.csv").exists():
        return
    rows = _rows("viterbi_board_ila_pm")
    rel = np.array([[int(r[f"s{s}"]) for s in range(64)] for r in rows]).T
    fig, ax = plt.subplots(figsize=(10, 4.8))
    im = ax.imshow(rel, aspect="auto", origin="lower", cmap="Blues_r", interpolation="nearest",
                   extent=(-0.5, rel.shape[1] - 0.5, -0.5, 63.5))
    ax.grid(False)
    ax.set_xlabel("ACS step on the board (one per decoded bit)")
    ax.set_ylabel("Trellis state")
    ax.set_yticks([0, 16, 32, 48, 63])
    bar = fig.colorbar(im, ax=ax, pad=0.01)
    bar.set_label("Path metric above the best state")
    ax.set_title("Viterbi path metrics, captured on the Arty by the ILA during a replay of the 2026-11-21 pass",
                 color=INK, loc="left", fontsize=11)
    fig.tight_layout()
    fig.savefig(MEDIA / "2026-11-23_phase-d_viterbi-ila-path-metrics.png", dpi=150)
    plt.close(fig)


def main() -> None:
    _style()
    MEDIA.mkdir(parents=True, exist_ok=True)
    ber_plot()
    fer_plot()
    constellation_plot()
    soft_width_plot()
    traceback_plot()
    ddc_spectrum_plot()
    ddc_ila_plot()
    lock_time_plot()
    doppler_plot()
    constellation_gif()
    board_ber_plot()
    real_pass_plot()
    viterbi_ila_plot()


if __name__ == "__main__":
    main()
