"""MSU-MR images by the golden model (model/msumr.py) against SatDump's, pixel by pixel (buildplan §4, optional step).

    python -m analysis.msumr_study --cadus RX/cadus.bin --packets RX/packets.bin --satdump-images RX_SATDUMP/MSU-MR
        [--pass-cadu PASS.cadu --pass-images PASS_SATDUMP/MSU-MR] [--gs-image build/gs-Release/gs-image]
        --recording NAME

RX is a board run's gs-rx output; RX_SATDUMP is `satdump meteor_m2-x_lrpt cadu RX/cadus.bin RX_SATDUMP`, SatDump's
images from those same CADUs. Three cases, one row per channel SatDump wrote:

- `model_satdump_demux`: the board's CADUs through SatDump's demultiplexer (model/space_packets.satdump_demux) and
  the model. Same packets as SatDump, so the pixels must be identical: this checks the image model.
- `model_satdump_pass`: the same on SatDump's own CADUs of the recording against SatDump's images of the pass (a
  second, independent input), if given.
- `own_packets`: gs-rx's packets.bin (the receiver's demultiplexer, ADR 0015) through the model: the image from this
  receiver's own packets. A differing segment is explained when our image has no segment there and the packet SatDump
  used for it is not among ours (gs-rx drops a packet that crosses a CADU gap instead of passing it on damaged).

With --gs-image, also runs the C++ tool on packets.bin and writes `gs_image_real`: its PNGs against the model's image of
the same packets (must be equal) and against SatDump's (explained as for `own_packets`).
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from analysis.common import write_result
from model.msumr import MCUS, Reader
from model.space_packets import satdump_demux
from scripts.packet_diff import split_cadus, split_packets

SEG_W = MCUS * 8  # 112 pixels


def reader(packets: list[bytes]) -> Reader:
    r = Reader()
    for p in packets:
        r.add(p)
    return r


def compare(ours: Reader, ref_dir: Path, case: str, explain_by: Reader | None = None,
            own: set[bytes] | None = None) -> list[list[object]]:
    rows: list[list[object]] = []
    for ch in range(6):
        f = ref_dir / f"MSU-MR-{ch + 1}.png"
        img = ours.image(ch)
        if not f.exists():
            if img.size:
                raise ValueError(f"{case}: channel {ch + 1} has an image here but not in SatDump's output")
            continue
        ref = np.array(Image.open(f))
        same_shape = img.shape == ref.shape
        diff = img != ref if same_shape else np.ones(1, dtype=bool)
        segs = sorted({(int(y) // 8, int(x) // SEG_W) for y, x in zip(*np.nonzero(diff), strict=True)}) \
            if same_shape else []
        explained = 0
        if explain_by is not None and own is not None and same_shape:
            first = explain_by.extent(ch)[0]
            for scan, j in segs:
                seg_id = first + scan * MCUS + j
                pkt = explain_by.ch[ch].packets.get(seg_id)
                if seg_id not in ours.ch[ch].segments and pkt is not None and pkt not in own:
                    explained += 1
        rows.append([case, ch + 1, img.shape[0], img.shape[1], ref.shape[0], int(diff.sum()) if same_shape else -1,
                     len(segs), explained, len(segs) - explained if explain_by is not None else len(segs)])
        print(rows[-1], flush=True)
    return rows


def gs_image(binary: Path, packets: Path, model: Reader, via_satdump: Reader, own: set[bytes], ref_dir: Path,
             recording: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        r = subprocess.run([str(binary), str(packets), tmp], capture_output=True, text=True, check=True)
        elapsed = time.perf_counter() - t0
        print(r.stdout, end="")
        rows: list[list[object]] = []
        for ch in range(6):
            png = Path(tmp) / f"MSU-MR-{ch + 1}.png"
            want = model.image(ch)
            if not png.exists():
                if want.size:
                    raise ValueError(f"gs-image wrote no channel {ch + 1}; the model has {want.shape[0]} rows")
                continue
            got = np.array(Image.open(png))
            vs_model = int((got != want).sum()) if got.shape == want.shape else -1
            ref = np.array(Image.open(ref_dir / png.name))
            if got.shape != ref.shape:
                raise ValueError(f"channel {ch + 1}: gs-image {got.shape}, SatDump {ref.shape}")
            diff = got != ref
            segs = sorted({(int(y) // 8, int(x) // SEG_W) for y, x in zip(*np.nonzero(diff), strict=True)})
            first = via_satdump.extent(ch)[0]
            explained = sum(1 for scan, j in segs
                            if (first + scan * MCUS + j) not in model.ch[ch].segments
                            and via_satdump.ch[ch].packets.get(first + scan * MCUS + j) not in (None, *own))
            rows.append([ch + 1, got.shape[0], got.shape[1], vs_model, int(diff.sum()), len(segs), explained,
                         len(segs) - explained, round(elapsed, 2)])
            print(rows[-1], flush=True)
    write_result("gs_image_real", ["channel", "rows", "cols", "pixels_differ_model", "pixels_differ_satdump",
                                   "segments_differ_satdump", "segments_explained", "segments_unexplained",
                                   "gs_image_s"], rows, "", recording=recording)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cadus", type=Path, required=True)
    ap.add_argument("--packets", type=Path, required=True)
    ap.add_argument("--satdump-images", type=Path, required=True)
    ap.add_argument("--pass-cadu", type=Path)
    ap.add_argument("--pass-images", type=Path)
    ap.add_argument("--gs-image", type=Path, help="the gs-image binary: also compare its PNGs (gs_image_real)")
    ap.add_argument("--recording", required=True, help="data/MANIFEST.md name of the recording")
    a = ap.parse_args()
    cadus = split_cadus(a.cadus.read_bytes(), "cadus")
    via_satdump = reader(satdump_demux(cadus))
    rows = compare(via_satdump, a.satdump_images, "model_satdump_demux")
    if a.pass_cadu and a.pass_images:
        rows += compare(reader(satdump_demux(split_cadus(a.pass_cadu.read_bytes(), "pass"))), a.pass_images,
                        "model_satdump_pass")
    own = split_packets(a.packets.read_bytes())
    rows += compare(reader(own), a.satdump_images, "own_packets", via_satdump, set(own))
    if a.gs_image:
        gs_image(a.gs_image, a.packets, reader(own), via_satdump, set(own), a.satdump_images, a.recording)
    write_result("msumr_model", ["case", "channel", "rows", "cols", "satdump_rows", "pixels_differ",
                                 "segments_differ", "segments_explained", "segments_unexplained"], rows,
                 "", recording=a.recording)
    ok = all(r[5] == 0 for r in rows if r[0] != "own_packets") and all(r[8] == 0 for r in rows)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
