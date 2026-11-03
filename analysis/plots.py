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
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
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


def main() -> None:
    _style()
    MEDIA.mkdir(parents=True, exist_ok=True)
    ber_plot()
    fer_plot()
    constellation_plot()


if __name__ == "__main__":
    main()
