"""Bit-true, causal frame sync: what the RTL will do (buildplan §3.5; float reference: receiver.frame_sync()).

receiver.frame_sync() is offline: it confirms a peak by looking one frame ahead and holds frames back until lock is
confirmed. Hardware sees each symbol once, so this version decides as the stream arrives:

- Correlation: the 4-bit soft symbols the Viterbi decoder also gets (viterbi_fixed.quantize()), as odd levels
  v = 2u - 15, against the 52-symbol encoded ASM under the 4 phase hypotheses (receiver._hypothesis_patterns()).
  Each correlation is a sum of ±v: adds and subtracts only.
- Threshold: |c| / sum|v| > thr, with sum|v| over the same 52 symbols. The float model divides by 52 * mean|v| over
  the whole stream; a causal mean over a trailing window instead let false peaks through while the AGC was still
  rising after reset (the window held the quieter past). Normalizing over the correlation's own symbols has no such
  lag. In integers: |c| * 64 > thr64 * sum|v|.
- SEARCH: every peak above threshold goes into a CANDIDATES-deep queue (lowest hypothesis first on a tie); a full
  queue drops the new peak and counts it.
- VERIFY: when a queued peak's position + one frame arrives, the same hypothesis must peak there too. The first
  confirmed peak locks, and its own frame is emitted too: the RTL feeds the Viterbi through a one-frame symbol delay
  line (which it needs anyway, to decode from before a frame's start), so that frame is still there.
- LOCK: every frame from the confirming ASM on is emitted. If the locked hypothesis misses an ASM but any
  hypothesis peaks within SLIP_SYMBOLS of it, follow that peak (nearest first, then lowest hypothesis): a carrier
  slip changes the hypothesis, and a timing slip of one sample shifts the stream by a symbol, which on OQPSK also
  changes it. Counted as a slip, not a miss. The RTL decides SLIP_SYMBOLS after the expected position, from a short
  history of the 4 hit flags. Without this, a slip cost the flywheel's frames, emitted under the wrong phase,
  before a new search (data/results/framesync_fixed.csv). Otherwise a missed ASM is a miss; the frame under it is still
  emitted and flagged (RS decides). More than `flywheel` consecutive misses return to SEARCH.
- OUTPUT (windows()): each emitted frame goes to the Viterbi as its own window, PRE_SYMBOLS before the frame start
  to POST_SYMBOLS after its end, derotated and paired; the RTL reads it from a ring buffer, so windows may overlap
  (a slip of -1 or -2 symbols). Overlap costs ~2% extra Viterbi steps (ADR 0010).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from model.coding import ASM_TRANSIENT_SYMBOLS, CODED_FRAME_SYMBOLS
from model.ddc_fixed import Ints
from model.receiver import _hypothesis_patterns
from model.viterbi_fixed import TRACEBACK_DEPTH

SOFT_BITS = 4  # ADR 0005: the Viterbi's input
CANDIDATES = 4  # peaks awaiting verification
SLIP_SYMBOLS = 2  # how far from the expected position a slipped ASM is followed
THR_FRAC = 6  # threshold register in 1/64ths: 0.75 = 48
PRE_SYMBOLS = 128  # Viterbi run-in before a frame: RxConfig.viterbi_margin_bits steps, as receiver.decode_frames()
POST_SYMBOLS = 2 * TRACEBACK_DEPTH  # after a frame: its last bit leaves the sliding traceback within its own window


@dataclass
class SyncResult:
    frames: list[tuple[int, bool, bool]]  # (frame start = ASM peak - 12, alternate, swap), as receiver.frame_sync()
    flywheel: list[bool]  # True for a frame emitted under a missed ASM
    dropped: int  # peaks dropped because the candidate queue was full
    slips: int  # hypothesis switches in lock


def patterns() -> Ints:
    """(4, 52) ±1 patterns, in receiver._hypothesis_patterns() order."""
    out: Ints = np.array([p for _, _, p in _hypothesis_patterns()], dtype=np.int64)
    return out


def correlate(u: Ints) -> Ints:
    """(4, n - 51) integer correlations: c[h, n] = sum_k pattern[h, k] * v[n + k], v = 2u - (2^bits - 1)."""
    v = 2 * u - ((1 << SOFT_BITS) - 1)
    pats = patterns()
    out: Ints = np.stack([np.correlate(v, p, mode="valid") for p in pats])
    return out


def hits(u: Ints, thr64: int) -> npt.NDArray[np.bool_]:
    """(4, n - 51): peak above threshold at each position, judged when its last symbol arrives."""
    v = np.abs(2 * u - ((1 << SOFT_BITS) - 1))
    level = np.correlate(v, np.ones(patterns().shape[1], dtype=np.int64), mode="valid")
    out: npt.NDArray[np.bool_] = np.abs(correlate(u)) * 64 > thr64 * level
    return out


def frame_sync_fixed(u: Ints, thr64: int = 48, flywheel: int = 4) -> SyncResult:
    hit = hits(u, thr64)
    hyps = _hypothesis_patterns()
    frames: list[tuple[int, bool, bool]] = []
    fly: list[bool] = []
    queue: list[tuple[int, int]] = []  # (position, hypothesis)
    dropped = 0
    slips = 0
    locked: tuple[int, int] | None = None  # (next ASM position, hypothesis)
    misses = 0
    peaks = np.flatnonzero(hit.any(axis=0))  # positions where SEARCH sees something; the loop jumps between events
    size = hit.shape[1]
    n = 0
    while n < size:
        if locked is not None:
            n, h = locked
            if n >= size:
                break
            if not hit[h, n]:
                for d in sorted(range(-SLIP_SYMBOLS, SLIP_SYMBOLS + 1), key=abs):
                    if 0 <= n + d < size and hit[:, n + d].any():
                        n, h = n + d, int(np.flatnonzero(hit[:, n + d])[0])
                        slips += 1
                        break
            misses = 0 if hit[h, n] else misses + 1
            if misses > flywheel:
                locked = None
                n += 1
            else:
                frames.append((n - ASM_TRANSIENT_SYMBOLS, hyps[h][0], hyps[h][1]))
                fly.append(misses > 0)
                locked = (n + CODED_FRAME_SYMBOLS, h)
            continue
        # Next event: a queued peak coming due, or the next peak.
        k = int(np.searchsorted(peaks, n))
        nxt = int(peaks[k]) if k < peaks.size else size
        if queue:
            nxt = min(nxt, queue[0][0] + CODED_FRAME_SYMBOLS)
        n = nxt
        if n >= size:
            break
        # VERIFY the oldest queued peak whose frame comes due now.
        if queue and queue[0][0] + CODED_FRAME_SYMBOLS == n:
            p, h = queue.pop(0)
            if hit[h, n]:
                queue.clear()
                misses = 0
                frames += [
                    (p - ASM_TRANSIENT_SYMBOLS, hyps[h][0], hyps[h][1]),
                    (n - ASM_TRANSIENT_SYMBOLS, hyps[h][0], hyps[h][1]),
                ]
                fly += [False, False]
                locked = (n + CODED_FRAME_SYMBOLS, h)
                continue
        # SEARCH: queue a new peak, lowest hypothesis on a tie.
        found = np.flatnonzero(hit[:, n])
        if found.size:
            if len(queue) < CANDIDATES:
                queue.append((n, int(found[0])))
            else:
                dropped += 1
        n += 1
    return SyncResult(frames, fly, dropped, slips)


@dataclass
class Window:
    pairs: Ints  # (WINDOW_SYMBOLS / 2,) Viterbi input words {b, a} = a | b << SOFT_BITS, derotated
    alternate: bool
    swap: bool
    flywheel: bool


WINDOW_SYMBOLS = PRE_SYMBOLS + CODED_FRAME_SYMBOLS + POST_SYMBOLS


def undo_levels(u: Ints, alternate: bool, swap: bool) -> Ints:
    """receiver._undo_hypothesis() on 4-bit levels. Negating level v = 2u - 15 is 15 - u: a bit inversion, exact
    because the midrise levels are symmetric about zero. u must start on a frame-aligned even symbol."""
    out = u.copy()
    top = (1 << SOFT_BITS) - 1
    if alternate:
        out[1::2] = top - out[1::2]
    if swap:
        out[0::2], out[1::2] = out[1::2].copy(), out[0::2].copy()
    return out


def windows(u: Ints, res: SyncResult) -> tuple[list[Window], int]:
    """What the RTL sends the Viterbi: per emitted frame, symbols [start - PRE, start + frame + POST) of u, derotated
    and paired. A frame whose window would begin before the first symbol is not emitted and is counted (only the
    first frame of an acquisition in the first ~16,500 symbols after reset can be). Returns (windows whose last
    symbol is in u, early frames)."""
    out: list[Window] = []
    early = 0
    for (start, alternate, swap), fly in zip(res.frames, res.flywheel, strict=True):
        first = start - PRE_SYMBOLS
        if first < 0:
            early += 1
            continue
        if first + WINDOW_SYMBOLS > u.size:
            break
        w = undo_levels(u[first : first + WINDOW_SYMBOLS], alternate, swap)
        out.append(Window(w[0::2] | (w[1::2] << SOFT_BITS), alternate, swap, fly))
    return out, early
