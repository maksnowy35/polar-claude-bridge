#!/usr/bin/env python3
"""Generate SYNTHETIC AccessLink-v3-shaped JSON (35 days) + journal + medical files to test the
pipeline end to end. Values are invented; the last night simulates an infection-like pattern
(RHR up, HRV down, skin temp up, breathing up) after a late hard session.

Usage: python tests/make_fixtures.py <out_dir>
"""
import csv
import json
import os
import random
import sys
from datetime import date, datetime, timedelta



def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def generate(out):
    random.seed(7)
    raw = os.path.join(out, "raw", "api")
    os.makedirs(raw, exist_ok=True)
    end = date(2026, 10, 16)
    days = [end - timedelta(days=i) for i in range(34, -1, -1)]
    nights, recharges, acts = [], [], []

    for i, d in enumerate(days):
        sick = d == end
        on = datetime.combine(d - timedelta(days=1), datetime.min.time()) + timedelta(hours=23, minutes=random.randint(0, 70))
        if sick:
            on += timedelta(minutes=40)
        dur = random.randint(400, 500) - (70 if sick else 0)
        off = on + timedelta(minutes=dur)
        hyp, t, stage = {}, on, 2
        seq = [2, 3, 4, 3, 2, 1] * 6
        k = 0
        while t < off:
            hyp[t.strftime("%H:%M")] = seq[k % len(seq)] if not (sick and k % 5 == 0) else 0
            t += timedelta(minutes=random.randint(12, 25))
            k += 1
        base_hr = 47 + (7 if sick else 0)
        hr = {}
        t = on
        while t < off:
            hr[t.strftime("%H:%M")] = base_hr + random.randint(-3, 6)
            t += timedelta(minutes=5)
        asleep = (dur - 30) * 60
        nights.append({
            "polar_user": "https://www.polaraccesslink.com/v3/users/1", "date": d.isoformat(),
            "sleep_start_time": on.isoformat() + "+02:00", "sleep_end_time": off.isoformat() + "+02:00",
            "device_id": "16BDCC30", "continuity": 3.4 - (1.2 if sick else 0), "continuity_class": 3 - (1 if sick else 0),
            "light_sleep": int(asleep * 0.55), "deep_sleep": int(asleep * (0.2 if not sick else 0.12)),
            "rem_sleep": int(asleep * 0.25), "unrecognized_sleep_stage": 0,
            "sleep_score": random.randint(72, 86) - (20 if sick else 0),
            "total_interruption_duration": random.randint(900, 1800) + (1800 if sick else 0),
            "sleep_charge": 3, "sleep_goal": 28800, "sleep_rating": 3,
            "short_interruption_duration": 600, "long_interruption_duration": 300 + (1500 if sick else 0),
            "sleep_cycles": 5 - (2 if sick else 0), "group_duration_score": 80, "group_solidity_score": 75 - (25 if sick else 0),
            "group_regeneration_score": 70 - (15 if sick else 0), "hypnogram": hyp, "heart_rate_samples": hr})
        hrv_base = 55 - (20 if sick else 0)
        hrv = {}
        br = {}
        t = on + timedelta(minutes=20)
        for _ in range(48):
            hrv[t.strftime("%H:%M")] = hrv_base + random.randint(-8, 8)
            br[t.strftime("%H:%M")] = round(14 + (1.8 if sick else 0) + random.uniform(-0.5, 0.5), 1)
            t += timedelta(minutes=5)
        recharges.append({
            "polar_user": "https://www.polaraccesslink.com/v3/users/1", "date": d.isoformat(),
            "heart_rate_avg": base_hr + 3, "beat_to_beat_avg": int(60000 / (base_hr + 3)),
            "heart_rate_variability_avg": hrv_base + random.randint(-4, 4),
            "breathing_rate_avg": round(14 + (1.8 if sick else 0) + random.uniform(-0.3, 0.3), 1),
            "nightly_recharge_status": 2 if sick else random.randint(3, 5), "ans_charge": -7.5 if sick else round(random.uniform(-2, 6), 1),
            "ans_charge_status": 1 if sick else 3, "hrv_samples": hrv, "breathing_samples": br})
        steps = random.randint(6000, 13000)
        acts.append({"start_time": d.isoformat() + "T00:00:00", "end_time": d.isoformat() + "T23:59:59",
                     "active_duration": f"PT{random.randint(2, 4)}H{random.randint(0, 59)}M", "inactive_duration": "PT6H",
                     "daily_activity": 80, "calories": random.randint(2700, 3600), "active_calories": random.randint(700, 1400),
                     "steps": steps, "inactivity_alert_count": random.randint(0, 3), "distance_from_steps": steps * 0.75,
                     "samples": {"date": d.isoformat(), "steps": {"interval_ms": 3600000, "total_steps": steps,
                                 "samples": [{"steps": steps // 14 if 7 <= h <= 20 else 0, "timestamp": f"{d.isoformat()}T{h:02d}:00:00.000"} for h in range(24)]}}})
        # 24/7 HR
        chr_ = {"polar_user": "x", "date": d.isoformat(), "heart_rate_samples": []}
        for m in range(0, 1440, 5):
            h = m / 60
            v = (base_hr + random.randint(-2, 4)) if (h < 7 or h >= 23.5) else 70 + random.randint(-8, 15)
            chr_["heart_rate_samples"].append({"heart_rate": v, "sample_time": f"{m // 60:02d}:{m % 60:02d}:00"})
        _write_json(os.path.join(raw, f"chr_{d}.json"), chr_)
        # biosensing-like skin temperature (per night)
        _write_json(os.path.join(raw, f"skin_{d}.json"), {"sleep_date": d.isoformat(), "sleep_time_skin_temperature_celsius": round(34.4 + (0.8 if sick else 0) + random.uniform(-0.2, 0.2), 2)})
        # trainings: tennis Tue/Thu/Sat, gym Mon/Fri, late hard tennis the evening before the sick night
        wd = d.weekday()
        if wd in (1, 3, 5) or d == end - timedelta(days=1):
            late = d == end - timedelta(days=1)
            st = datetime.combine(d, datetime.min.time()) + timedelta(hours=21 if late else 18)
            durm = 120 if late else 90
            hrs = ",".join(str(random.randint(110, 175) if late else random.randint(95, 160)) for _ in range(durm * 60 // 5))
            _write_json(os.path.join(raw, f"ex_{d}.json"), {"id": f"ex{d}", "start_time": st.isoformat(), "start_time_utc_offset": 120, "duration": f"PT{durm // 60}H{durm % 60}M",
                       "calories": 900 if late else 650, "heart_rate": {"average": 148 if late else 128, "maximum": 182 if late else 168},
                       "training_load": 180 if late else 110, "sport": "OTHER", "detailed_sport_info": "TENNIS",
                       "heart_rate_zones": [{"index": i, "lower-limit": l, "upper-limit": l + 20, "in-zone": f"PT{z}M"}
                                            for i, (l, z) in enumerate(zip([98, 118, 137, 157, 176], [10, 25, 40, 35, 10] if late else [15, 35, 30, 10, 0]))],
                       "samples": [{"recording-rate": 5, "sample-type": "0", "data": hrs}],
                       "training_load_pro": {"date": d.isoformat(), "cardio-load": 160 if late else 95, "muscle-load": -1,
                                             "cardio-load-interpretation": "HIGH" if late else "MEDIUM", "user-rpe": "HARD" if late else None}})
        if wd in (0, 4):
            st = datetime.combine(d, datetime.min.time()) + timedelta(hours=17)
            _write_json(os.path.join(raw, f"gym_{d}.json"), {"id": f"gym{d}", "start_time": st.isoformat(), "duration": "PT1H10M", "calories": 420,
                       "heart_rate": {"average": 112, "maximum": 151}, "sport": "STRENGTH_TRAINING",
                       "detailed_sport_info": "STRENGTH_TRAINING",
                       "training_load_pro": {"cardio-load": 45, "muscle-load": 60, "cardio-load-interpretation": "LOW"}})

    _write_json(os.path.join(raw, "sleep.json"), {"nights": nights})
    _write_json(os.path.join(raw, "recharge.json"), {"recharges": recharges})
    _write_json(os.path.join(raw, "activities.json"), acts)

    os.makedirs(os.path.join(out, "journal"), exist_ok=True)
    with open(os.path.join(out, "journal", "log.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "time", "type", "item", "value", "unit", "note"])
        for d in days[-12:]:
            w.writerow([d.isoformat(), "09:00", "mood", "", random.randint(5, 8), "", ""])
            w.writerow([d.isoformat(), "21:30", "supp", "magnez", "400", "mg", ""])
        w.writerow([(end - timedelta(days=1)).isoformat(), "20:30", "caffeine", "kawa", "150", "mg", "przed tenisem"])
        w.writerow([end.isoformat(), "08:00", "symptom", "ból gardła", "2", "", "po basenie?"])

    os.makedirs(os.path.join(out, "medical"), exist_ok=True)
    _write_text(os.path.join(out, "medical", "timeline.md"),
        "# Medical timeline (SYNTHETIC TEST)\n\n## Aktualnie\n- lek X 10 mg rano (od 2026-05)\n- suplementy: magnez 400 mg wieczorem, omega-3\n\n## Historia\n- 2026-03 przykładowy wpis\n")
    with open(os.path.join(out, "medical", "labs.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "test", "value", "unit", "ref_low", "ref_high", "note"])
        w.writerow(["2026-08-01", "ferrytyna", "28", "ng/ml", "30", "400", ""])
        w.writerow(["2026-08-01", "TSH", "1.9", "uIU/ml", "0.27", "4.2", ""])
        w.writerow(["2026-08-01", "witamina D", "24", "ng/ml", "30", "50", ""])
    return out


if __name__ == "__main__":
    print("fixtures in", generate(sys.argv[1]))
