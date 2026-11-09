"""Small helpers shared by parsers and builders (stdlib only)."""
from __future__ import annotations

import math
import re
import statistics as st
from datetime import date, datetime, timedelta

_ISO_DUR = re.compile(
    r"^P(?:(?P<d>\d+(?:\.\d+)?)D)?(?:T(?:(?P<h>\d+(?:\.\d+)?)H)?(?:(?P<m>\d+(?:\.\d+)?)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?)?$"
)

BIN_MIN = 5                      # resolution of stored HR / skin-temp day curves
BINS_PER_DAY = 24 * 60 // BIN_MIN


def iso_dur_s(v) -> float | None:
    """'PT1H35M12.5S' -> seconds. Also accepts numbers (returned as-is)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = _ISO_DUR.match(str(v).strip())
    if not m:
        return None
    d, h, mi, s = (float(m.group(k) or 0) for k in ("d", "h", "m", "s"))
    return d * 86400 + h * 3600 + mi * 60 + s


def hhmm_to_min(t: str) -> int:
    """'23:41' or '23:41:07' -> minutes from midnight."""
    p = t.split(":")
    return int(p[0]) * 60 + int(p[1]) + (int(float(p[2])) // 60 if len(p) > 2 else 0)


def min_to_hhmm(m: float | None) -> str:
    if m is None:
        return ""
    m = int(round(m)) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_dt(s: str) -> datetime:
    """Parse ISO timestamps from Polar (with or without offset / millis)."""
    s = s.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def d2s(d: date) -> str:
    return d.isoformat()


def s2d(s: str) -> date:
    return date.fromisoformat(s[:10])


def prev_day(s: str) -> str:
    return d2s(s2d(s) - timedelta(days=1))


def mean(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return sum(xs) / len(xs) if xs else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def sd(xs):
    xs = [x for x in xs if x is not None]
    return st.stdev(xs) if len(xs) >= 3 else None


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    return xs[f] if f == c else xs[f] + (xs[c] - xs[f]) * (k - f)


def rnd(x, n=1):
    if x is None:
        return None
    r = round(x, n)
    return int(r) if n == 0 else r


def bin_series(points, bin_min=BIN_MIN, agg=median):
    """points: iterable of (minute_of_day, value) -> list[BINS_PER_DAY] of aggregated values or None."""
    n = 24 * 60 // bin_min
    buckets = [[] for _ in range(n)]
    for m, v in points:
        if v is None:
            continue
        i = int(m // bin_min)
        if 0 <= i < n:
            buckets[i].append(v)
    return [agg(b) if b else None for b in buckets]


def coarsen(series, factor, agg=mean, nd=0):
    """Collapse a binned series by `factor` (e.g. 5-min -> 30-min with factor 6)."""
    out = []
    for i in range(0, len(series), factor):
        out.append(rnd(agg(series[i:i + factor]), nd))
    return out


def fmt_series(xs, missing="-"):
    return " ".join(missing if x is None else str(x) for x in xs)


def rolling_min_mean(series, window):
    """Lowest mean over `window` consecutive non-None bins (gaps break windows)."""
    best = None
    run = []
    for v in series:
        if v is None:
            run = []
            continue
        run.append(v)
        if len(run) > window:
            run.pop(0)
        if len(run) == window:
            m = sum(run) / window
            best = m if best is None or m < best else best
    return best
