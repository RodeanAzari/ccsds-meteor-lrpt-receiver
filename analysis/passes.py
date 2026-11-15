"""Predict satellite passes over a site from a TLE, to plan captures (CLAUDE.md §1, buildplan §2.4).

    python -m analysis.passes --lat LAT --lon LON [--days 7] [--min-el 30] [--start 2026-11-16T00:00] [--tz ZONE]

The TLE comes from SatDump's cache (~/.config/satdump/satdump_tles.txt; refresh it in SatDump before each pass).
Propagation is the sgp4 library; TEME -> Earth-fixed uses GMST only (no polar motion or equation of the equinoxes),
which costs well under 0.1° and is far below the 10 s step. Checked against the 2026-11-13 pass: predicted
19:17-19:32 UTC, max 64° at 19:24; the signal showed in the recording at 19:22-19:24 (docs/log.md).
The site is an argument, not a default: this repo is public.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sgp4.api import Satrec, jday

TLE_FILE = Path.home() / ".config" / "satdump" / "satdump_tles.txt"
SAT_NAME = "METEOR-M2 4"  # name in SatDump's TLE file (NORAD 59051)
WGS84_A_KM = 6378.137
WGS84_F = 1 / 298.257223563


@dataclass(frozen=True)
class Site:
    lat_deg: float
    lon_deg: float  # east positive
    alt_km: float = 0.0


@dataclass(frozen=True)
class Pass:
    aos: datetime
    los: datetime
    t_max: datetime
    max_el: float
    aos_az: float
    los_az: float


def load_tle(path: Path, name: str) -> Satrec:
    lines = [line.rstrip() for line in path.read_text().splitlines()]
    for i, line in enumerate(lines[:-2]):
        if line.strip() == name:
            return Satrec.twoline2rv(lines[i + 1], lines[i + 2])
    raise SystemExit(f"{name!r} not in {path}")


def gmst_rad(jd_ut1: float) -> float:
    """Greenwich mean sidereal time (IAU 1982, Vallado eq. 3-45), radians."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    deg = 280.46061837 + 360.98564736629 * (jd_ut1 - 2451545.0) + 0.000387933 * t * t - t**3 / 38710000.0
    return math.radians(deg % 360.0)


def site_ecef(s: Site) -> tuple[float, float, float]:
    la, lo = math.radians(s.lat_deg), math.radians(s.lon_deg)
    e2 = WGS84_F * (2 - WGS84_F)
    n = WGS84_A_KM / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return (
        (n + s.alt_km) * math.cos(la) * math.cos(lo),
        (n + s.alt_km) * math.cos(la) * math.sin(lo),
        (n * (1 - e2) + s.alt_km) * math.sin(la),
    )


def look_angles(r_teme_km: tuple[float, float, float], jd_ut1: float, s: Site) -> tuple[float, float]:
    """(azimuth from north through east, elevation), degrees, of a TEME position seen from the site."""
    th = gmst_rad(jd_ut1)
    x = r_teme_km[0] * math.cos(th) + r_teme_km[1] * math.sin(th)
    y = -r_teme_km[0] * math.sin(th) + r_teme_km[1] * math.cos(th)
    sx, sy, sz = site_ecef(s)
    dx, dy, dz = x - sx, y - sy, r_teme_km[2] - sz
    la, lo = math.radians(s.lat_deg), math.radians(s.lon_deg)
    e = -math.sin(lo) * dx + math.cos(lo) * dy
    n = -math.sin(la) * math.cos(lo) * dx - math.sin(la) * math.sin(lo) * dy + math.cos(la) * dz
    u = math.cos(la) * math.cos(lo) * dx + math.cos(la) * math.sin(lo) * dy + math.sin(la) * dz
    return math.degrees(math.atan2(e, n)) % 360.0, math.degrees(math.atan2(u, math.hypot(e, n)))


def az_el(sat: Satrec, t: datetime, s: Site) -> tuple[float, float]:
    jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
    err, r, _ = sat.sgp4(jd, fr)
    if err:
        raise RuntimeError(f"sgp4 error {err} at {t:%Y-%m-%d %H:%M:%S} UTC")
    return look_angles((r[0], r[1], r[2]), jd + fr, s)


def passes(sat: Satrec, s: Site, start: datetime, days: float, step_s: float = 10.0) -> Iterator[Pass]:
    """Passes whose AOS falls in [start, start + days); a pass already up at start is skipped."""
    t, end = start, start + timedelta(days=days)
    up = az_el(sat, t, s)[1] > 0
    aos = t_max = t
    max_el = aos_az = 0.0
    while t < end or up:
        az, el = az_el(sat, t, s)
        if el > 0 and not up:
            up, aos, aos_az, max_el, t_max = True, t, az, el, t
        elif el > 0 and el > max_el:
            max_el, t_max = el, t
        elif el <= 0 and up:
            up = False
            if aos > start:
                yield Pass(aos, t, t_max, max_el, aos_az, az)
            elif t >= end:
                return
        t += timedelta(seconds=step_s)


def compass(az: float) -> str:
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((az + 22.5) // 45) % 8]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True, help="site latitude, degrees north")
    ap.add_argument("--lon", type=float, required=True, help="site longitude, degrees east (west is negative)")
    ap.add_argument("--alt-km", type=float, default=0.0)
    ap.add_argument("--start", help="UTC, ISO (default: now)")
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--min-el", type=float, default=30.0, help="list passes at least this high, degrees")
    ap.add_argument("--tz", help="also show local time in this zone, e.g. America/Toronto")
    ap.add_argument("--tle", type=Path, default=TLE_FILE)
    ap.add_argument("--sat", default=SAT_NAME)
    a = ap.parse_args(argv)
    sat = load_tle(a.tle, a.sat)
    start = datetime.fromisoformat(a.start).replace(tzinfo=UTC) if a.start else datetime.now(UTC)
    epoch = datetime(2000 + sat.epochyr, 1, 1, tzinfo=UTC) + timedelta(days=sat.epochdays - 1)
    print(f"{a.sat}: TLE epoch {epoch:%Y-%m-%d %H:%M} UTC ({(start - epoch).total_seconds() / 86400:.1f} d old)")
    tz = ZoneInfo(a.tz) if a.tz else None
    for p in passes(sat, Site(a.lat, a.lon, a.alt_km), start, a.days):
        if p.max_el >= a.min_el:
            local = f"  ({p.aos.astimezone(tz):%H:%M %Z})" if tz else ""
            print(
                f"{p.aos:%a %Y-%m-%d %H:%M}-{p.los:%H:%M} UTC{local}  max {p.max_el:4.1f}° at {p.t_max:%H:%M}  "
                f"{compass(p.aos_az)}->{compass(p.los_az)}"
            )


if __name__ == "__main__":
    main()
