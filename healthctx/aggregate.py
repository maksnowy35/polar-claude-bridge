"""Merge parsed facts into per-day records, compute baselines, derived metrics and flags.

Day convention: everything about a night (sleep, Nightly Recharge, night HR, night skin
temperature) belongs to the date you WOKE UP (Polar's convention). Daytime activity and
trainings belong to their calendar date.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .util import (BIN_MIN, d2s, mean, median, pct, prev_day, rnd, rolling_min_mean,
                   s2d, sd)

FALLBACK_NIGHT = (60, 360)     # 01:00-06:00 when no sleep window is known (night HR mean, skin temp)
FALLBACK_RHR = (-120, 720)     # 22:00 prev day - 12:00 for lowest 30-min HR when no sleep window
BASE_DAYS = 28                 # trailing window for per-day deviations / flags
MIN_BASE_N = 7

HARD_INT = {"medium", "high", "very_high", "load_interpretation_medium"}


def _merge(a, b):
    """Fill None/missing fields of a with b."""
    if not a:
        return dict(b)
    out = dict(a)
    for k, v in b.items():
        if out.get(k) in (None, "", [], {}) and v not in (None, "", [], {}):
            out[k] = v
    return out


def _merge_bins(a, b):
    if not a:
        return b
    return [x if x is not None else y for x, y in zip(a, b)]


def collect(facts, sports=None):
    sports = sports or {}
    days = defaultdict(dict)
    sessions = {}
    profiles, tests, skipped = [], [], defaultdict(int)
    for f in facts:
        k = f.get("k")
        d = f.get("date")
        if k == "activity":
            # export first (richer); API fills gaps
            cur = days[d].get("activity")
            days[d]["activity"] = _merge(cur, f) if (cur or {}).get("src") == "export" or f["src"] == "api" else _merge(f, cur or {})
        elif k == "hr":
            days[d]["hr_bins"] = _merge_bins(days[d].get("hr_bins"), f["bins"])
        elif k == "skin":
            days[d]["skin_bins"] = _merge_bins(days[d].get("skin_bins"), f["bins"])
        elif k == "skin_night":
            days[d]["skin_night"] = f
        elif k == "sleep":
            cur = days[d].get("sleep")
            if cur and (cur.get("bed_h") or 0) >= (f.get("bed_h") or 0):
                days[d].setdefault("naps", []).append(f)
            else:
                if cur:
                    days[d].setdefault("naps", []).append(cur)
                days[d]["sleep"] = f
        elif k == "recharge":
            days[d]["recharge"] = _merge(days[d].get("recharge"), f)
        elif k == "cardio_load":
            days[d]["cardio"] = f
        elif k == "session":
            key = (f["date"], f["start"])
            s = dict(f)
            s["sport"] = (sports.get(str(f.get("sport_id"))) if f.get("sport_id") else None) or f.get("sport_name") \
                or (f"sport#{f['sport_id']}" if f.get("sport_id") else "?")
            sessions[key] = _merge(sessions.get(key), s) if key in sessions and sessions[key]["src"] == "export" else _merge(s, sessions.get(key) or {})
        elif k == "profile":
            profiles.append(f)
        elif k == "fitness_test":
            tests.append(f)
        else:
            skipped[f.get("why", "?")] += 1
    for s in sessions.values():
        days[s["date"]].setdefault("sessions", []).append(s)
    for d in days.values():
        d.get("sessions", []).sort(key=lambda s: s["start"])
    return dict(days), sorted(sessions.values(), key=lambda s: (s["date"], s["start"])), profiles, tests, dict(skipped)


def latest_profile(profiles, tests):
    p = {}
    for f in sorted(profiles, key=lambda f: f.get("date") or "9999"):
        for k, v in f.items():
            if v not in (None, "", 0) and k not in ("k", "date"):
                p[k] = v
    if tests:
        t = max(tests, key=lambda t: t["date"])
        p["fitness_test"] = f"{t['date']} VO2 {t['vo2']} ({(t.get('class') or '').lower()})"
    return p


def _window_values(days, d, bins_key, lo, hi):
    """Values of 5-min bins between lo..hi minutes relative to midnight of day d (lo may be < 0)."""
    out = []
    prev = days.get(prev_day(d), {}).get(bins_key)
    cur = days.get(d, {}).get(bins_key)
    for m in range(int(lo // BIN_MIN) * BIN_MIN, int(hi), BIN_MIN):
        if m < 0:
            if prev:
                out.append(prev[(1440 + m) // BIN_MIN])
        elif m < 1440 and cur:
            out.append(cur[m // BIN_MIN])
    return out


def _trail(rows, i, key, n=BASE_DAYS):
    """Trailing values of `key` over the previous n calendar days (excluding row i)."""
    d0 = s2d(rows[i]["date"])
    out = []
    j = i - 1
    while j >= 0 and (d0 - s2d(rows[j]["date"])).days <= n:
        v = rows[j].get(key)
        if v is not None:
            out.append(v)
        j -= 1
    return out


def build_rows(days, journal_days=None, profile=None):
    journal_days = journal_days or {}
    profile = profile or {}
    all_dates = sorted(set(days) | set(journal_days))
    rows = []
    for d in all_dates:
        x = days.get(d, {})
        r = {"date": d}
        sl, rc, act = x.get("sleep"), x.get("recharge"), x.get("activity")
        # --- sleep
        if sl:
            for k in ("on", "off", "sleep_h", "bed_h", "score", "s_dur", "s_sol", "s_reg", "deep_pct", "rem_pct",
                      "intr_min", "cont", "cycles", "charge"):
                r[k] = sl.get(k)
            r["mid_min"] = (sl["on_min"] + sl["off_min"]) / 2
            win = (sl["on_min"], sl["off_min"])
        else:
            win = None
            if act and act.get("sleep_h_act"):
                r["sleep_h"] = act["sleep_h_act"]          # activity-file estimate (no stages)
                r["sleep_src"] = "act"
        # --- nightly recharge
        if rc:
            r.update({"nr": rc.get("nr"), "ans": rc.get("ans"), "hrv": rc.get("hrv"), "br": rc.get("br"),
                      "hr_nr": rc.get("hr")})
        # --- night HR & skin temp from continuous curves
        lo, hi = win or FALLBACK_NIGHT
        hr_w = _window_values(days, d, "hr_bins", lo, hi)
        # RHR = lowest 30-min mean; without a sleep window search wide (22:00 prev day - 12:00)
        hr_r = hr_w if win else _window_values(days, d, "hr_bins", *FALLBACK_RHR)
        if sum(v is not None for v in hr_r) >= 12:
            r["rhr"] = rnd(rolling_min_mean(hr_r, 30 // BIN_MIN), 0)
        if sum(v is not None for v in hr_w) >= 12:
            r["hr_night"] = rnd(mean(hr_w), 0)
        sk_w = _window_values(days, d, "skin_bins", lo, hi)
        if x.get("skin_night", {}).get("t") is not None:
            r["skin_t"] = x["skin_night"]["t"]
        elif sum(v is not None for v in sk_w) >= 12:
            r["skin_t"] = rnd(mean(sk_w), 2)
        r["night_win"] = "sleep" if win else "01-06"
        # --- activity
        if act:
            lv = act.get("lvl") or {}
            r.update({"steps": act.get("steps"), "kcal": act.get("kcal"), "met_min": act.get("met_min"),
                      "mod_min": lv.get("mod"), "vig_min": lv.get("vig"),
                      "sed_h": rnd((lv.get("sed") or 0) / 60, 1) if lv.get("sed") is not None else None,
                      "nonwear_h": rnd((lv.get("nonwear") or 0) / 60, 1) if lv.get("nonwear") else None,
                      "wt": act.get("wt")})
        # --- trainings
        ss = x.get("sessions", [])
        if ss:
            r["sess"] = len(ss)
            r["train_min"] = sum(s.get("dur_min") or 0 for s in ss)
            loads = [s.get("cardio_load") if s.get("cardio_load") is not None else s.get("trimp") for s in ss]
            r["load"] = rnd(sum(l for l in loads if l is not None), 0) if any(l is not None for l in loads) else None
            r["sports"] = "+".join(s["sport"] for s in ss)
            r["last_end"] = max(s["end"] for s in ss)
        if x.get("cardio"):
            r["cl_status"] = x["cardio"].get("status")
            r["cl_ratio"] = x["cardio"].get("ratio")
        # --- journal
        r.update(journal_days.get(d, {}))
        rows.append(r)

    # --- trailing baselines, deviations, flags
    for i, r in enumerate(rows):
        fl = []
        sig = 0
        b = {k: _trail(rows, i, k) for k in ("rhr", "hrv", "br", "skin_t", "sleep_h", "score", "hr_night")}
        if r.get("skin_t") is not None and len(b["skin_t"]) >= MIN_BASE_N:
            r["skin_dev"] = rnd(r["skin_t"] - median(b["skin_t"]), 2)
            if r["skin_dev"] >= 0.5:
                fl.append(f"T+{r['skin_dev']}"); sig += 1
        if r.get("rhr") is not None and len(b["rhr"]) >= MIN_BASE_N:
            m, s = mean(b["rhr"]), sd(b["rhr"]) or 0
            if r["rhr"] - m >= max(5, 2 * s):
                fl.append(f"RHR+{rnd(r['rhr'] - m, 0)}"); sig += 1
        if r.get("hrv") is not None and len(b["hrv"]) >= MIN_BASE_N:
            m, s = mean(b["hrv"]), sd(b["hrv"]) or 0
            if r["hrv"] <= m - max(1.5 * s, 0.15 * m):
                fl.append(f"HRV{rnd(100 * (r['hrv'] - m) / m, 0)}%"); sig += 1
        if r.get("br") is not None and len(b["br"]) >= MIN_BASE_N:
            m, s = mean(b["br"]), sd(b["br"]) or 0
            if r["br"] - m >= max(1.0, 2 * s):
                fl.append(f"BR+{rnd(r['br'] - m, 1)}"); sig += 1
        if sig >= 2:
            fl.append("MULTI")      # >=2 independent physiological deviations: infection / overreach / alcohol?
        if r.get("sleep_h") is not None and r["sleep_h"] < 6:
            fl.append("SLEEP<6h")
        if r.get("score") is not None and len(b["score"]) >= MIN_BASE_N and r["score"] < (pct(b["score"], 0.1) or 0):
            fl.append("SCORE_LOW")
        if r.get("ans") is not None and r["ans"] <= -5:
            fl.append(f"ANS{r['ans']}")
        # late hard session the evening before this night
        if r.get("on") is not None and i > 0:
            sl = days.get(r["date"], {}).get("sleep")
            for s in days.get(prev_day(r["date"]), {}).get("sessions", []):
                if s.get("end_date", s["date"]) != prev_day(r["date"]):
                    continue
                gap = (sl["on_min"] + 1440) - s["end_min"]
                z = s.get("zones") or []
                hard = (s.get("cardio_int") or "") in HARD_INT or sum((z[2:] if len(z) >= 3 else [])) >= 15
                if 0 <= gap < 120 and hard:
                    fl.append(f"LATE_HARD({s['sport']},{int(gap)}min)")
        # sleep timing shift
        if r.get("mid_min") is not None:
            mids = _trail(rows, i, "mid_min", 14)
            if len(mids) >= MIN_BASE_N and abs(r["mid_min"] - median(mids)) >= 90:
                fl.append(f"TIMING{'+' if r['mid_min'] > median(mids) else '-'}{rnd(abs(r['mid_min'] - median(mids)) / 60, 1)}h")
        # acute:chronic load
        d0 = s2d(r["date"])
        win7 = [x.get("load") or 0 for x in rows[max(0, i - 40):i + 1] if (d0 - s2d(x["date"])).days < 7]
        win28 = [x.get("load") or 0 for x in rows[max(0, i - 40):i + 1] if (d0 - s2d(x["date"])).days < 28]
        # ACWR only when the watch was worn on most of the last 28 days (else rest days look like gaps)
        worn28 = sum(1 for x in rows[max(0, i - 40):i + 1] if (d0 - s2d(x["date"])).days < 28
                     and any(x.get(k) is not None for k in ("steps", "rhr", "sleep_h", "hrv")))
        r["load7"] = rnd(sum(win7), 0)
        if worn28 >= 21 and sum(win28) > 0:
            r["acwr"] = rnd(sum(win7) / (sum(win28) / 4), 2)
            if r["acwr"] >= 1.5:
                fl.append(f"ACWR{r['acwr']}")
        r["flags"] = ";".join(fl)
    return rows


def baselines(rows, end_date, days=60):
    keys = ["sleep_h", "score", "deep_pct", "rem_pct", "intr_min", "ans", "hrv", "br", "rhr", "hr_night",
            "skin_t", "steps", "met_min", "train_min", "load", "mood", "energy", "stress"]
    d1 = s2d(end_date)
    sel = [r for r in rows if 0 <= (d1 - s2d(r["date"])).days < days]
    out = {}
    for k in keys:
        v = [r.get(k) for r in sel if r.get(k) is not None]
        if k in ("train_min", "load"):          # include rest days as 0 for weekly sums
            out[k] = {"wk": rnd(sum(v) / max(1, days / 7), 0), "n": len(v)}
            continue
        if len(v) >= 3:
            out[k] = {"med": median(v), "p10": pct(v, 0.1), "p90": pct(v, 0.9), "mean": mean(v), "n": len(v)}
    return out


def window_mean(rows, end_date, key, start_ago, end_ago):
    d1 = s2d(end_date)
    v = [r.get(key) for r in rows if start_ago <= (d1 - s2d(r["date"])).days < end_ago and r.get(key) is not None]
    return mean(v), len(v)


def week_loads(rows, end_date, weeks=6):
    d1 = s2d(end_date)
    monday = d1 - timedelta(days=d1.weekday())
    out = []
    for w in range(weeks - 1, -1, -1):
        a = monday - timedelta(weeks=w)
        b = a + timedelta(days=7)
        sel = [r for r in rows if a <= s2d(r["date"]) < b]
        out.append({"week": a.isocalendar()[1], "from": d2s(a),
                    "load": rnd(sum(r.get("load") or 0 for r in sel), 0),
                    "sess": sum(r.get("sess") or 0 for r in sel),
                    "h": rnd(sum(r.get("train_min") or 0 for r in sel) / 60, 1),
                    "steps": rnd(mean([r.get("steps") for r in sel]), 0)})
    return out
