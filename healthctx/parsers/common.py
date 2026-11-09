"""Small numeric/time-series helpers shared by the export and API parsers."""
from __future__ import annotations

import math

from ..util import hhmm_to_min, mean, rnd


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _clean_hr(v):
    f = _num(v)
    return f if f is not None and 25 <= f <= 240 else None


def _night_series(d: dict):
    """{'23:41': 58, '00:05': 55, ...} -> sorted [(minutes rel. to wake-day midnight, value)].

    Clock times from 12:00 onward are treated as the previous evening (negative minutes)."""
    out = []
    for k, v in (d or {}).items():
        m = hhmm_to_min(k)
        out.append((m - 1440 if m >= 720 else m, _num(v)))
    return sorted(out)


def _resample_rel(points, step=30, nd=0):
    """(rel_min, value) -> list of means per `step` minutes starting at 0."""
    if not points:
        return []
    last = max(p[0] for p in points)
    n = int(last // step) + 1
    buckets = [[] for _ in range(n)]
    for m, v in points:
        if v is not None and m >= 0:
            buckets[int(m // step)].append(v)
    return [rnd(mean(b), nd) if b else None for b in buckets]


def _hr_profile(pts, step=5):
    if not pts:
        return []
    return _resample_rel([(m, v) for m, v in pts if v is not None], step, 0)
