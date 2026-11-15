"""passes: the predictor that decides when the antenna goes out.

Why it matters: a wrong sidereal angle or a wrong local frame shifts every pass by minutes or reports the wrong
elevation, and a pass finder that drops or truncates passes hides the best ones. GMST is checked against Vallado's
worked example; the look angles by geometry with known answers; the pass finder on a scripted elevation; the whole
chain on a real TLE against orbital bounds. (The 2026-11-13 pass matched the recording; see the module docstring.
That site is not committed, so it is not a test.)
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from analysis import passes as p

# Meteor-M N2-4 from SatDump's cache, epoch 2026-11-13 (26317.589)
TLE = [
    "METEOR-M2 4",
    "1 59051U 24039A   26317.58910567  .00000013  00000+0  25344-4 0  9993",
    "2 59051  98.7244 275.1553 0008132  96.2612 263.9492 14.22443109140509",
]
GREENWICH = p.Site(51.4769, 0.0)


def test_gmst_matches_vallado_example_3_5() -> None:
    # Vallado, Fundamentals of Astrodynamics, Example 3-5: 1992-08-20 12:14 UT1 -> GMST 152.578787810°.
    # The book prints JD 2448855.009722 (rounded: that alone moves GMST by 8e-5°); use the exact 12:14:00.
    jd = 2448854.5 + (12 * 60 + 14) / 1440
    assert math.degrees(p.gmst_rad(jd)) == pytest.approx(152.578787810, abs=1e-6)


def ecef_to_teme(r: tuple[float, float, float], jd: float) -> tuple[float, float, float]:
    th = p.gmst_rad(jd)
    return (r[0] * math.cos(th) - r[1] * math.sin(th), r[0] * math.sin(th) + r[1] * math.cos(th), r[2])


@pytest.mark.parametrize("jd", [2461000.25, 2461357.8])
def test_look_angles_overhead_north_east(jd: float) -> None:
    s = p.Site(43.0, -81.3)  # any mid-latitude, western site (exercises a negative longitude)
    sx, sy, sz = p.site_ecef(s)
    la, lo = math.radians(s.lat_deg), math.radians(s.lon_deg)
    up = (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))
    north = (-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la))
    east = (-math.sin(lo), math.cos(lo), 0.0)

    def at(d: tuple[float, float, float], km: float) -> tuple[float, float, float]:
        return ecef_to_teme((sx + km * d[0], sy + km * d[1], sz + km * d[2]), jd)

    assert p.look_angles(at(up, 800), jd, s)[1] == pytest.approx(90.0, abs=1e-6)
    az, el = p.look_angles(at(north, 1000), jd, s)
    assert (az % 360 if az < 180 else az - 360, el) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert p.look_angles(at(east, 1000), jd, s) == pytest.approx((90.0, 0.0), abs=1e-6)


def scripted(monkeypatch: pytest.MonkeyPatch, t0: datetime, windows: list[tuple[float, float, float]]) -> None:
    """Elevation as half-sine bumps: (start min, length min, peak °) after t0; -10° otherwise."""

    def fake(_sat: object, t: datetime, _s: p.Site) -> tuple[float, float]:
        m = (t - t0).total_seconds() / 60
        for a, length, peak in windows:
            if a < m < a + length:
                return 100.0 + m, peak * math.sin(math.pi * (m - a) / length)
        return 0.0, -10.0

    monkeypatch.setattr(p, "az_el", fake)


def test_pass_finder_times_and_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = datetime(2026, 11, 17, tzinfo=UTC)
    # A pass already up at start (skipped), two full passes, one that runs past the end (kept, completed).
    scripted(monkeypatch, t0, [(-5, 10, 30), (60, 15, 83), (200, 12, 20), (1430, 14, 50)])
    got = list(p.passes(object(), GREENWICH, t0, 1.0))  # type: ignore[arg-type]
    assert [round((x.aos - t0).total_seconds() / 60) for x in got] == [60, 200, 1430]
    assert [round((x.los - t0).total_seconds() / 60) for x in got] == [75, 212, 1444]
    assert [round((x.t_max - t0).total_seconds() / 60, 1) for x in got] == [67.5, 206.0, 1437.0]
    assert got[0].max_el == pytest.approx(83.0, abs=0.1)
    assert got[0].aos_az == pytest.approx(160.0, abs=0.2)


def test_real_tle_obeys_orbit_bounds(tmp_path: Path) -> None:
    f = tmp_path / "tles.txt"
    f.write_text("\n".join(["OTHER SAT", *TLE[1:], *TLE]) + "\n")
    sat = p.load_tle(f, "METEOR-M2 4")
    assert sat.satnum == 59051
    found = list(p.passes(sat, GREENWICH, datetime(2026, 11, 14, tzinfo=UTC), 2.0))
    # ~830 km altitude: horizon half-angle acos(6378 / 7208) = 27.7° of a 101.2 min orbit (14.224 rev/day), so no
    # pass lasts over 2 * 27.7 / 360 * 101.2 = 15.6 min (+1 step of slack).
    assert len(found) >= 6
    for x in found:
        assert x.los - x.aos <= timedelta(minutes=15.6, seconds=10)
        assert 0 < x.max_el <= 90 and x.aos < x.t_max < x.los
    assert max(x.max_el for x in found) > 60


def test_missing_satellite_is_an_error(tmp_path: Path) -> None:
    f = tmp_path / "tles.txt"
    f.write_text("\n".join(TLE) + "\n")
    with pytest.raises(SystemExit, match="NOAA 19"):
        p.load_tle(f, "NOAA 19")


def test_site_ecef_matches_wgs84_radii() -> None:
    # Equatorial radius a = 6378.137 km on the equator; polar radius b = a (1 - f) = 6356.752 km at the pole.
    # (A spherical z would put a 43° N site ~29 km off and its elevations off by a fraction of a degree.)
    assert p.site_ecef(p.Site(0.0, 0.0)) == pytest.approx((6378.137, 0.0, 0.0), abs=1e-6)
    assert p.site_ecef(p.Site(90.0, 0.0))[2] == pytest.approx(6356.7523142, abs=1e-6)
    assert p.site_ecef(p.Site(0.0, 90.0, alt_km=1.0)) == pytest.approx((0.0, 6379.137, 0.0), abs=1e-6)
