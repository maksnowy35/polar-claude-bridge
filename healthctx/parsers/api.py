"""Parsers for Polar AccessLink v3 API responses (one object each; wrappers are handled by walk())."""
from __future__ import annotations

from datetime import datetime, timedelta

from ..util import bin_series, hhmm_to_min, iso_dur_s, parse_dt, rnd
from .common import _clean_hr, _hr_profile, _night_series, _num, _resample_rel


HYP = {0: "W", 1: "R", 2: "L", 3: "L", 4: "D", 5: "?"}   # 2=lighter NREM, 3=light NREM


def api_sleep(n):
    on, off = parse_dt(n["sleep_start_time"]), parse_dt(n["sleep_end_time"])
    wake_date = off.date().isoformat()
    midnight = datetime.combine(off.date(), datetime.min.time(), tzinfo=off.tzinfo)
    on_min = (on - midnight).total_seconds() / 60          # negative if fell asleep before midnight
    off_min = (off - midnight).total_seconds() / 60
    light, deep, rem = (n.get("light_sleep") or 0), (n.get("deep_sleep") or 0), (n.get("rem_sleep") or 0)
    unk = n.get("unrecognized_sleep_stage") or 0
    asleep = light + deep + rem
    # hypnogram: change points -> one letter per 10 min
    hyp = ""
    pts = [(m - on_min, v) for m, v in _night_series(n.get("hypnogram"))]
    if pts:
        total = int((off - on).total_seconds() // 60)
        cur, j = pts[0][1], 0
        for t in range(0, total, 10):
            while j + 1 < len(pts) and pts[j + 1][0] <= t + 5:   # stage at mid-slot
                j += 1
                cur = pts[j][1]
            hyp += HYP.get(int(cur) if cur is not None else 5, "?")
    hr_pts = [(m - on_min, v) for m, v in _night_series(n.get("heart_rate_samples"))]
    hr_vals = [v for _, v in hr_pts if v]
    return {
        "k": "sleep", "src": "api", "date": wake_date,
        "on": on.strftime("%H:%M"), "off": off.strftime("%H:%M"),
        "on_min": rnd(on_min, 0), "off_min": rnd(off_min, 0),
        "sleep_h": rnd(asleep / 3600, 2), "bed_h": rnd((off - on).total_seconds() / 3600, 2),
        "score": n.get("sleep_score"),
        "s_dur": rnd(n.get("group_duration_score"), 0), "s_sol": rnd(n.get("group_solidity_score"), 0),
        "s_reg": rnd(n.get("group_regeneration_score"), 0),
        "deep_min": rnd(deep / 60, 0), "rem_min": rnd(rem / 60, 0), "light_min": rnd(light / 60, 0),
        "unk_min": rnd(unk / 60, 0),
        "deep_pct": rnd(100 * deep / asleep, 0) if asleep else None,
        "rem_pct": rnd(100 * rem / asleep, 0) if asleep else None,
        "intr_min": rnd((n.get("total_interruption_duration") or 0) / 60, 0),
        "intr_long_min": rnd((n.get("long_interruption_duration") or 0) / 60, 0),
        "intr_short_min": rnd((n.get("short_interruption_duration") or 0) / 60, 0),
        "cont": n.get("continuity"), "cont_class": n.get("continuity_class"),
        "cycles": n.get("sleep_cycles"), "charge": n.get("sleep_charge"), "rating": n.get("sleep_rating"),
        "goal_h": rnd((n.get("sleep_goal") or 0) / 3600, 1) or None,
        "hyp": hyp, "hr30": _resample_rel(hr_pts, 30, 0), "hr_lo": rnd(min(hr_vals), 0) if hr_vals else None,
    }


def api_recharge(r):
    hrv_n, br_n = _night_series(r.get("hrv_samples")), _night_series(r.get("breathing_samples"))
    t0 = min([m for m, _ in hrv_n + br_n], default=None)
    hrv = [(m - t0, v) for m, v in hrv_n]
    br = [(m - t0, v) for m, v in br_n]
    first = None if t0 is None else t0 % 1440
    return {
        "k": "recharge", "src": "api", "date": r["date"],
        "nr": r.get("nightly_recharge_status"), "ans": rnd(_num(r.get("ans_charge")), 1),
        "ans_st": r.get("ans_charge_status"), "hrv": rnd(_num(r.get("heart_rate_variability_avg")), 0),
        "hr": rnd(_num(r.get("heart_rate_avg")), 0), "rri": rnd(_num(r.get("beat_to_beat_avg")), 0),
        "br": rnd(_num(r.get("breathing_rate_avg")), 1),
        "hrv30": _resample_rel(hrv, 30, 0), "br30": _resample_rel(br, 30, 1),
        "s30_from": None if first is None else f"{first // 60:02d}:{first % 60:02d}",
    }


def api_activity(a):
    st = a.get("start_time") or a.get("date")
    d = st[:10]
    smp = a.get("samples") or {}
    if isinstance(smp, list):
        smp = smp[0] if smp else {}
    steps_h = [0] * 24
    for x in ((smp.get("steps") or {}).get("samples") or []):
        ts = x.get("timestamp", "")
        if "T" in ts:
            t = parse_dt(ts)
            steps_h[t.hour] += int(x.get("steps") or 0)
    # activity zones: consecutive timestamps -> durations
    zs = (smp.get("activity_zones") or {}).get("samples") or []
    lv = {}
    for z0, z1 in zip(zs, zs[1:] + [None]):
        t0 = parse_dt(z0["timestamp"])
        t1 = parse_dt(z1["timestamp"]) if z1 else datetime.combine(t0.date() + timedelta(days=1), datetime.min.time(), tzinfo=t0.tzinfo)
        lv[z0["zone"]] = lv.get(z0["zone"], 0) + (t1 - t0).total_seconds() / 60
    return {
        "k": "activity", "src": "api", "date": d,
        "steps": a.get("steps"), "kcal": a.get("calories"), "active_kcal": a.get("active_calories"),
        "dist_km": rnd((a.get("distance_from_steps") or 0) / 1000, 1),
        "active_min": rnd((iso_dur_s(a.get("active_duration")) or 0) / 60, 0),
        "inact_alerts": a.get("inactivity_alert_count"),
        "lvl": {"sleep": rnd(lv.get("SLEEP"), 0), "sed": rnd(lv.get("SEDENTARY"), 0),
                "light": rnd(lv.get("LIGHT"), 0),
                "mod": rnd((lv.get("MODERATE") or 0) + (lv.get("CONTINUOUS_MODERATE") or 0), 0),
                "vig": rnd((lv.get("VIGOROUS") or 0) + (lv.get("CONTINUOUS_VIGOROUS") or 0), 0),
                "nonwear": rnd(lv.get("NON_WEAR"), 0)} if lv else {},
        "steps_h": steps_h if any(steps_h) else None,
    }


def api_continuous_hr(o):
    pts = [(hhmm_to_min(x["sample_time"]) + (int(x["sample_time"].split(":")[2]) / 60 if x["sample_time"].count(":") == 2 else 0),
            _clean_hr(x.get("heart_rate"))) for x in o.get("heart_rate_samples", [])]
    return {"k": "hr", "src": "api", "date": o["date"], "bins": [rnd(b, 0) for b in bin_series(pts)], "n": len(pts)}


def api_exercise(e):
    start = parse_dt(e["start_time"])
    dur = (iso_dur_s(e.get("duration")) or 0) / 60
    stop = start + timedelta(minutes=dur)
    zones, lims = [0.0] * 5, []
    for z in sorted(e.get("heart_rate_zones") or [], key=lambda z: z.get("index", 0))[:5]:
        i = int(z.get("index", 0))
        if 0 <= i < 5:
            zones[i] = (iso_dur_s(z.get("in-zone")) or 0) / 60
            lims.append(z.get("lower-limit"))
    hr_pts = []
    for s in e.get("samples") or []:
        if str(s.get("sample-type")) == "0":
            rate = float(s.get("recording-rate") or 1)
            vals = str(s.get("data", "")).split(",")
            hr_pts = [(i * rate / 60, _clean_hr(v)) for i, v in enumerate(vals)]
    tlp = e.get("training_load_pro") or {}
    if isinstance(tlp, list):
        tlp = tlp[0] if tlp else {}
    hr = e.get("heart_rate") or {}
    ml = _num(tlp.get("muscle-load"))
    return {
        "k": "session", "src": "api", "id": str(e.get("id") or e["start_time"]),
        "date": start.date().isoformat(), "start": start.strftime("%H:%M"), "end": stop.strftime("%H:%M"),
        "start_min": start.hour * 60 + start.minute, "end_min": stop.hour * 60 + stop.minute,
        "end_date": stop.date().isoformat(),
        "sport_id": None, "sport_name": (e.get("detailed_sport_info") or e.get("sport") or "").lower() or None,
        "dur_min": rnd(dur, 0), "kcal": e.get("calories"),
        "hr_avg": hr.get("average"), "hr_max": hr.get("maximum"), "hr_min": None,
        "dist_km": rnd((e.get("distance") or 0) / 1000, 2) or None,
        "cardio_load": rnd(_num(tlp.get("cardio-load")), 0),
        "cardio_int": (tlp.get("cardio-load-interpretation") or "").lower() or None,
        "muscle_load": rnd(ml, 0) if ml is not None and ml >= 0 else None,
        "trimp": rnd(_num(e.get("training_load")), 0), "rpe": tlp.get("user-rpe"),
        "recovery_h": None, "zones": [rnd(z, 0) for z in zones], "zone_lims": lims,
        "hr5": _hr_profile(hr_pts), "laps": None, "device": e.get("device"),
    }


def api_cardio_load(c):
    return {"k": "cardio_load", "date": c["date"], "status": c.get("cardio_load_status"),
            "load": rnd(_num(c.get("cardio_load")), 0), "strain": rnd(_num(c.get("strain")), 1),
            "tolerance": rnd(_num(c.get("tolerance")), 1), "ratio": rnd(_num(c.get("cardio_load_ratio")), 2)}


def api_skin_night(o):
    """Tolerant parser for biosensing skin-temperature summaries (one value per night)."""
    d = o.get("sleep_date") or o.get("date")
    val = next((o[k] for k in o if "skin_temperature" in k and "deviation" not in k and _num(o[k]) is not None), None)
    dev = next((o[k] for k in o if "deviation" in k and _num(o[k]) is not None), None)
    return {"k": "skin_night", "date": d[:10], "t": rnd(_num(val), 2), "dev_polar": rnd(_num(dev), 2)}
