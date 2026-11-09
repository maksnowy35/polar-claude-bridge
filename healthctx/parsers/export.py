"""Parsers for files from the Polar Flow data export (account.polar.com -> Download your data)."""
from __future__ import annotations

from datetime import timedelta

from ..util import bin_series, coarsen, hhmm_to_min, iso_dur_s, mean, parse_dt, rnd
from .common import _clean_hr, _hr_profile, _num


def export_activity(o):
    s = o.get("summary", {})
    lv = {x["level"]: (iso_dur_s(x.get("duration")) or 0) / 60 for x in s.get("activityLevels", [])}
    steps = o.get("samples", {}).get("steps", [])
    mets = o.get("samples", {}).get("mets", [])
    steps_h = [0] * 24
    for x in steps:
        steps_h[hhmm_to_min(x["localTime"]) // 60] += int(x.get("value") or 0)
    met_pts = [(hhmm_to_min(x["localTime"]), _num(x.get("value"))) for x in mets]
    met_h = coarsen(bin_series(met_pts, 60, mean), 1, mean, 1)
    pi = o.get("physicalInformation", {})
    return [{
        "k": "activity", "src": "export", "date": o["date"],
        "steps": s.get("stepCount"), "kcal": s.get("calories"),
        "dist_km": rnd((s.get("stepsDistance") or 0) / 1000, 1),
        "met_min": rnd(s.get("dailyMetMinutes"), 0),
        "inact_alerts": s.get("inactivityAlertCount"),
        "lvl": {
            "sleep": rnd(lv.get("SLEEP"), 0),
            "sed": rnd(lv.get("SEDENTARY"), 0),
            "light": rnd(lv.get("LIGHT"), 0),
            "mod": rnd((lv.get("CONTINUOS_MODERATE") or 0) + (lv.get("INTERMITTENT_MODERATE") or 0), 0),
            "vig": rnd((lv.get("CONTINUOS_VIGOROUS") or 0) + (lv.get("INTERMITTENT_VIGOROUS") or 0), 0),
            "nonwear": rnd(lv.get("NON_WEAR"), 0),
        },
        "sleep_h_act": rnd((iso_dur_s(s.get("sleepDuration")) or 0) / 3600, 2) or None,
        "sleep_q_act": rnd((s.get("sleepQuality") or 0) * 100, 0) or None,
        "steps_h": steps_h, "met_h": met_h,
        "wt": pi.get("weight, kg"),
    }]


def export_hr247(o):
    out = []
    by_date = {}
    for dd in o.get("deviceDays", []):
        by_date.setdefault(dd["date"], []).extend(dd.get("samples", []))
    for d, samples in by_date.items():
        pts = [(x["secondsFromDayStart"] / 60, _clean_hr(x.get("heartRate"))) for x in samples]
        bins = bin_series(pts)
        out.append({"k": "hr", "src": "export", "date": d, "bins": [rnd(b, 0) for b in bins], "n": len(samples)})
    return out


def export_generic_period(o):
    data, meta = o.get("data", {}), o.get("meta", {})
    mt = data.get("measurementType")
    if mt != "TM_SKIN_TEMPERATURE":
        return [{"k": "skip", "why": f"generic-period {mt}"}]
    # meta.created is the local day start (verified against 24/7 HR: wake-up drop matches)
    d = meta.get("created", "")[:10]
    pts = []
    for x in data.get("temperatureMeasurementSamples", []):
        t = float(x.get("recordingTimeDeltaMilliseconds") or 0) / 60000   # offset from day start
        v = _num(x.get("temperatureCelsius"))
        pts.append((t, v if v is not None and 20 < v < 42 else None))
    bins = bin_series(pts)
    return [{"k": "skin", "src": "export", "date": d, "loc": data.get("sensorLocation"),
             "bins": [rnd(b, 2) for b in bins]}]


def export_training_session(o):
    start = parse_dt(o["startTime"])
    stop = parse_dt(o["stopTime"]) if o.get("stopTime") else start + timedelta(milliseconds=o.get("durationMillis", 0))
    exs = o.get("exercises", [])
    zones = [0.0] * 5
    lims = []
    hr_pts, hr_min, dist = [], None, None
    for ex in exs:
        for z in ex.get("zones", []):
            if z.get("type") == "ZONE_TYPE_HEART_RATE":
                for i, zz in enumerate(z.get("zones", [])[:5]):
                    zones[i] += (zz.get("inZone") or 0) / 60000
                    if len(lims) < 5:
                        lims.append(rnd(zz.get("lowerLimit"), 0))
        for stt in ex.get("statistics", {}).get("statistics", []):
            if stt.get("type") == "STATISTICS_TYPE_HEART_RATE" and stt.get("min"):
                hr_min = stt["min"] if hr_min is None else min(hr_min, stt["min"])
        ex_start = parse_dt(ex.get("startTime", o["startTime"]))
        off = (ex_start - start).total_seconds()
        for smp in ex.get("samples", {}).get("samples", []):
            step = (smp.get("intervalMillis") or 1000) / 1000
            if smp.get("type") == "HEART_RATE":
                hr_pts += [((off + i * step) / 60, _clean_hr(v)) for i, v in enumerate(smp.get("values", []))]
            elif smp.get("type") == "DISTANCE":
                vals = [_num(v) for v in smp.get("values", [])]
                vals = [v for v in vals if v is not None]
                if vals:
                    dist = (dist or 0) + vals[-1]
        if ex.get("distance"):
            dist = (dist or 0) + float(ex["distance"])
    tl = o.get("trainingLoadReport") or (exs[0].get("trainingLoadReport") if exs else {}) or {}
    ml = tl.get("muscleLoad")
    return [{
        "k": "session", "src": "export",
        "id": (o.get("identifier") or {}).get("id") or o["startTime"],
        "date": start.date().isoformat(),
        "start": start.strftime("%H:%M"), "end": stop.strftime("%H:%M"),
        "start_min": start.hour * 60 + start.minute, "end_min": stop.hour * 60 + stop.minute,
        "end_date": stop.date().isoformat(),
        "sport_id": str((o.get("sport") or {}).get("id", "")), "sport_name": o.get("name") or None,
        "dur_min": rnd((o.get("durationMillis") or 0) / 60000, 0),
        "kcal": o.get("calories"), "hr_avg": o.get("hrAvg"), "hr_max": o.get("hrMax"), "hr_min": rnd(hr_min, 0),
        "dist_km": rnd(dist / 1000, 2) if dist else None,
        "cardio_load": rnd(tl.get("cardioLoad"), 0),
        "cardio_int": (tl.get("cardioLoadInterpretation") or "").replace("LOAD_INTERPRETATION_", "").lower() or None,
        "muscle_load": rnd(ml, 0) if ml is not None and ml >= 0 else None,
        "recovery_h": rnd(float(o.get("recoveryTimeMillis") or 0) / 3.6e6, 1),
        "zones": [rnd(z, 0) for z in zones], "zone_lims": lims,
        "hr5": _hr_profile(hr_pts), "laps": sum(len(ex.get("laps", {}).get("laps", [])) for ex in exs),
        "device": (o.get("product") or {}).get("modelName"),
    }]


def export_account(o):
    pi = o.get("physicalInformation", {})
    return [{"k": "profile", "date": None, "sex": pi.get("sex"), "birthday": pi.get("birthday"),
             "height": pi.get("height, cm"), "weight": pi.get("weight, kg"), "vo2max": pi.get("vo2Max"),
             "sleep_goal_h": rnd((iso_dur_s(pi.get("sleepGoal")) or 0) / 3600, 1),
             "bg": pi.get("trainingBackground"), "typical_day": pi.get("typicalDay")}]


def export_session_physinfo(o):
    """Training sessions carry the thresholds valid at that time (HRmax, AeT, AnT, rest HR)."""
    pi = o.get("physicalInformation") or {}
    if not pi:
        return []
    return [{"k": "profile", "date": o["startTime"][:10], "sex": pi.get("sex"), "birthday": pi.get("birthday"),
             "height": pi.get("heightCm"), "weight": pi.get("weightKg"), "vo2max": pi.get("vo2Max"),
             "hrmax": pi.get("maximumHeartRate"), "hrrest": pi.get("restingHeartRate"),
             "aet": pi.get("aerobicThreshold"), "ant": pi.get("anaerobicThreshold"),
             "ftp": pi.get("functionalThresholdPower"),
             "sleep_goal_h": rnd((pi.get("sleepGoalMinutes") or 0) / 60, 1) or None}]


def export_fitness_test(o):
    r = o.get("fitnessTestResult", {})
    return [{"k": "fitness_test", "date": o.get("startTime", "")[:10], "vo2": r.get("ownIndex"),
             "hr_avg": r.get("averageHeartRate"), "class": r.get("fitnessClass")}]
