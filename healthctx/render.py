"""Render compact, Claude-friendly outputs.

out/
  INDEX.md                  what is where + legend (read first if unsure)
  status.md                 last 14 days + baselines + trends + flags + journal + medical pointer
  monthly.csv               one row per month (long-term trends)
  daily/daily_YYYY-MM.csv   one row per day
  sessions/sessions_YYYY-MM.csv
  days/day_YYYY-MM-DD.md    drill-down: hypnogram, night HR/HRV, skin temp, evening before, trainings
"""
from __future__ import annotations

import csv
import io
import os
from collections import defaultdict
from datetime import datetime

from .aggregate import baselines, week_loads, window_mean
from .journal import fmt_entry, labs_flags, medical_current
from .util import (BIN_MIN, coarsen, fmt_series, mean, min_to_hhmm, prev_day, rnd, s2d)

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DAILY_COLS = ["date", "on", "off", "sleep_h", "bed_h", "score", "s_dur", "s_sol", "s_reg", "deep_pct", "rem_pct",
              "intr_min", "cont", "cycles", "charge", "nr", "ans", "hrv", "br", "hr_nr", "rhr", "hr_night",
              "skin_t", "skin_dev", "steps", "kcal", "met_min", "mod_min", "vig_min", "sed_h", "nonwear_h",
              "sess", "train_min", "load", "load7", "acwr", "sports", "last_end", "wt",
              "mood", "energy", "stress", "alc", "caf_last", "sym", "supp", "flags"]

SESSION_COLS = ["date", "start", "end", "sport", "dur_min", "kcal", "hr_avg", "hr_max", "hr_min", "zones_min",
                "cardio_load", "cardio_int", "muscle_load", "trimp", "rpe", "recovery_h", "dist_km"]


class Writer:
    """Writes files only when content changed; remembers what changed (for the Drive uploader)."""

    def __init__(self, root):
        self.root, self.changed, self.total = root, [], 0

    def write(self, rel, text):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        self.total += 1
        if os.path.exists(p) and open(p, encoding="utf-8").read() == text:
            return
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        self.changed.append(rel)


def _csv(rows, cols):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])
    return buf.getvalue()


def _v(x, nd=None, unit=""):
    if x is None or x == "":
        return "-"
    if nd is not None and isinstance(x, (int, float)):
        x = rnd(x, nd)
    return f"{x}{unit}"


# ----------------------------------------------------------------------------- CSVs

def render_csvs(W, rows, sessions):
    by_m = defaultdict(list)
    for r in rows:
        by_m[r["date"][:7]].append(r)
    for m, rs in by_m.items():
        W.write(f"daily/daily_{m}.csv", _csv(rs, DAILY_COLS))
    s_by_m = defaultdict(list)
    for s in sessions:
        s = dict(s)
        s["zones_min"] = "/".join(str(z or 0) for z in (s.get("zones") or []))
        s_by_m[s["date"][:7]].append(s)
    for m, ss in s_by_m.items():
        W.write(f"sessions/sessions_{m}.csv", _csv(ss, SESSION_COLS))
    # monthly
    mrows = []
    for m, rs in sorted(by_m.items()):
        def mm(k, nd=1):
            return rnd(mean([r.get(k) for r in rs]), nd)
        mrows.append({"month": m, "days": len(rs), "sleep_h": mm("sleep_h", 2), "score": mm("score", 0),
                      "deep_pct": mm("deep_pct", 0), "rem_pct": mm("rem_pct", 0), "hrv": mm("hrv", 0),
                      "rhr": mm("rhr", 0), "br": mm("br"), "ans": mm("ans"), "skin_t": mm("skin_t", 2),
                      "steps": mm("steps", 0), "sess": sum(r.get("sess") or 0 for r in rs),
                      "train_h": rnd(sum(r.get("train_min") or 0 for r in rs) / 60, 1),
                      "load": rnd(sum(r.get("load") or 0 for r in rs), 0),
                      "mood": mm("mood"), "energy": mm("energy"), "stress": mm("stress"),
                      "flag_days": sum(1 for r in rs if r.get("flags"))})
    W.write("monthly.csv", _csv(mrows, list(mrows[0].keys()) if mrows else ["month"]))


# ----------------------------------------------------------------------------- day drill-down

def _hourly(bins, factor, nd=0):
    return coarsen(bins, factor, mean, nd) if bins else None


def render_day(W, d, days, rowmap, journal_rows):
    x = days.get(d, {})
    r = rowmap.get(d, {"date": d})
    pd_ = prev_day(d)
    px = days.get(pd_, {})
    L = [f"# {d} ({DOW[s2d(d).weekday()]})"]
    sl, rc = x.get("sleep"), x.get("recharge")

    # ---------------- night (ending this morning)
    L.append(f"\n## Night → morning of {d}")
    if sl:
        L.append(f"Sleep {sl['on']}–{sl['off']} | asleep {sl['sleep_h']} h / in bed {sl['bed_h']} h | score {_v(sl.get('score'))} "
                 f"(duration {_v(sl.get('s_dur'))}, solidity {_v(sl.get('s_sol'))}, regeneration {_v(sl.get('s_reg'))})")
        L.append(f"Stages: deep {_v(sl.get('deep_min'))} min ({_v(sl.get('deep_pct'))}%), REM {_v(sl.get('rem_min'))} min ({_v(sl.get('rem_pct'))}%), "
                 f"light {_v(sl.get('light_min'))} min, unrecognized {_v(sl.get('unk_min'))} min | interruptions {_v(sl.get('intr_min'))} min "
                 f"(long {_v(sl.get('intr_long_min'))}, short {_v(sl.get('intr_short_min'))}) | continuity {_v(sl.get('cont'))} "
                 f"(class {_v(sl.get('cont_class'))}/5) | cycles {_v(sl.get('cycles'))} | sleep charge {_v(sl.get('charge'))}/5")
        if sl.get("hyp"):
            L.append(f"Hypnogram (1 char = 10 min from {sl['on']}; W wake, R REM, L light, D deep, ? unknown): {sl['hyp']}")
        if sl.get("hr30"):
            L.append(f"Sleep HR 30-min from {sl['on']}: {fmt_series(sl['hr30'])} | min {_v(sl.get('hr_lo'))}")
        for n in x.get("naps", []):
            L.append(f"Other sleep: {n['on']}–{n['off']} ({n['sleep_h']} h)")
    elif r.get("sleep_h"):
        L.append(f"Sleep (activity-file estimate, no stages): {r['sleep_h']} h")
    else:
        L.append("Sleep: no data")
    if rc:
        L.append(f"Nightly Recharge: status {_v(rc.get('nr'))}/6 | ANS charge {_v(rc.get('ans'))} (status {_v(rc.get('ans_st'))}/5) | "
                 f"HRV {_v(rc.get('hrv'))} ms | HR {_v(rc.get('hr'))} | RRI {_v(rc.get('rri'))} ms | breathing {_v(rc.get('br'))}/min")
        if rc.get("hrv30"):
            L.append(f"HRV 30-min from {rc.get('s30_from')}: {fmt_series(rc['hrv30'])}")
        if rc.get("br30"):
            L.append(f"Breathing 30-min from {rc.get('s30_from')}: {fmt_series(rc['br30'])}")
    nw = "sleep window" if r.get("night_win") == "sleep" else "01:00–06:00 (no sleep window)"
    if r.get("rhr") is not None:
        rw = "sleep window" if r.get("night_win") == "sleep" else "22:00–12:00"
        L.append(f"24/7 HR: lowest 30-min mean {r['rhr']} ({rw}); mean over {nw} {_v(r.get('hr_night'))}")
    if r.get("skin_t") is not None:
        dev = f", Δ vs 28-night median {r['skin_dev']:+} °C" if r.get("skin_dev") is not None else ""
        L.append(f"Distal skin temp over {nw}: {r['skin_t']} °C{dev}")
    if r.get("flags"):
        L.append(f"Flags: {r['flags']}")

    # ---------------- evening before
    eve = []
    hb = px.get("hr_bins")
    if hb:
        eve.append(f"HR 30-min 18:00→24:00: {fmt_series(coarsen(hb[18 * 60 // BIN_MIN:], 30 // BIN_MIN, mean, 0))}")
    pa = px.get("activity") or {}
    if pa.get("steps_h"):
        eve.append(f"Steps per hour 18→24: {fmt_series(pa['steps_h'][18:])}")
    for s in px.get("sessions", []):
        if s["end_min"] >= 15 * 60:
            eve.append(f"Session {s['start']}–{s['end']} {s['sport']} {s['dur_min']} min, HR {_v(s.get('hr_avg'))}/{_v(s.get('hr_max'))}, "
                       f"zones {'/'.join(str(z or 0) for z in s.get('zones') or [])} min, load {_v(s.get('cardio_load'))} ({_v(s.get('cardio_int'))})")
    je = [fmt_entry(j) for j in journal_rows.get(pd_, []) if (j.get("time") or "99") >= "15:00"]
    if je:
        eve.append("Journal: " + "; ".join(je))
    if eve:
        L.append(f"\n## Evening before ({pd_} from 18:00)")
        L += eve

    # ---------------- day
    L.append(f"\n## Day {d}")
    a = x.get("activity")
    if a:
        lv = a.get("lvl") or {}
        items = [(a.get("steps"), "{} steps"), (a.get("kcal"), "{} kcal"), (a.get("active_kcal"), "active {} kcal"),
                 (a.get("active_min"), "active {} min"), (a.get("met_min"), "MET-min {}"), (lv.get("mod"), "moderate {} min"),
                 (lv.get("vig"), "vigorous {} min"), (r.get("sed_h"), "sedentary {} h"), (r.get("nonwear_h"), "non-wear {} h"),
                 (a.get("inact_alerts"), "inactivity alerts {}")]
        L.append("Activity: " + ", ".join(f.format(v) for v, f in items if v is not None))
        if a.get("steps_h"):
            L.append(f"Steps per hour 0→23: {fmt_series(a['steps_h'])}")
        if a.get("met_h"):
            L.append(f"MET per hour 0→23: {fmt_series(a['met_h'])}")
    if x.get("hr_bins"):
        L.append(f"24/7 HR hourly mean 0→23: {fmt_series(_hourly(x['hr_bins'], 60 // BIN_MIN))}")
    if x.get("skin_bins"):
        L.append(f"Skin temp hourly 0→23: {fmt_series(_hourly(x['skin_bins'], 60 // BIN_MIN, 1))}")
    for s in x.get("sessions", []):
        zs = (f" | zones Z1–Z5 {'/'.join(str(z or 0) for z in s['zones'])} min (lower limits {'/'.join(str(z) for z in s['zone_lims'])})"
              if s.get("zone_lims") else "")
        L.append(f"Training {s['start']}–{s['end']} {s['sport']} {s['dur_min']} min | {_v(s.get('kcal'))} kcal | HR avg {_v(s.get('hr_avg'))} "
                 f"max {_v(s.get('hr_max'))}" + (f" min {s['hr_min']}" if s.get("hr_min") else "") + zs +
                 f" | cardio load {_v(s.get('cardio_load'))} ({_v(s.get('cardio_int'))})"
                 + (f", muscle load {s['muscle_load']}" if s.get("muscle_load") is not None else "")
                 + (f", recovery {s['recovery_h']} h" if s.get("recovery_h") else "")
                 + (f", RPE {s['rpe']}" if s.get("rpe") else "") + (f", {s['dist_km']} km" if s.get("dist_km") else ""))
        if s.get("hr5"):
            L.append(f"  HR 5-min: {fmt_series(s['hr5'])}")
    je = [fmt_entry(j) for j in journal_rows.get(d, [])]
    if je:
        L.append("Journal: " + "; ".join(je))
    W.write(f"days/day_{d}.md", "\n".join(L) + "\n")


# ----------------------------------------------------------------------------- status

def _g(x):
    return int(x) if isinstance(x, float) and x.is_integer() else x


def _arrow(a, b, tol):
    if a is None or b is None:
        return ""
    return "↑" if a - b > tol else "↓" if b - a > tol else "→"


def render_status(W, rows, profile, coverage, journal_rows, med_dir, end_date, generated):
    rows_end = [r for r in rows if r["date"] <= end_date]
    last14 = rows_end[-14:]
    B = baselines(rows_end, end_date, 60)
    age = None
    if profile.get("birthday"):
        b = s2d(profile["birthday"])
        e = s2d(end_date)
        age = e.year - b.year - ((e.month, e.day) < (b.month, b.day))
    L = [f"# Health status — data through {end_date} (generated {generated})"]
    pr = [f"{(profile.get('sex') or '?').replace('SEX_', '')[0]}", f"{age} y" if age else None,
          f"{rnd(profile.get('height'), 0)} cm" if profile.get("height") else None,
          f"{rnd(profile.get('weight'), 1)} kg" if profile.get("weight") else None,
          f"VO2max {profile.get('vo2max')}" if profile.get("vo2max") else None,
          f"HRmax {profile.get('hrmax')}" if profile.get("hrmax") else None,
          f"HRrest(set) {profile.get('hrrest')}" if profile.get("hrrest") else None,
          f"AeT {profile.get('aet')}/AnT {profile.get('ant')}" if profile.get("aet") else None,
          f"sleep goal {profile.get('sleep_goal_h')} h" if profile.get("sleep_goal_h") else None,
          f"fitness test {profile['fitness_test']}" if profile.get("fitness_test") else None]
    pr = [p for p in pr if p and p != "?"]
    L.append("Profile: " + (", ".join(pr) if pr else "(no profile data yet)"))
    L.append("Coverage: " + "; ".join(f"{k} {v}" for k, v in coverage.items()))

    # baselines
    fmt = {"sleep_h": ("sleep h", 1), "score": ("score", 0), "deep_pct": ("deep%", 0), "rem_pct": ("REM%", 0),
           "intr_min": ("interrupt min", 0), "ans": ("ANS", 1), "hrv": ("HRV ms", 0), "br": ("BR/min", 1),
           "rhr": ("RHR", 0), "hr_night": ("night HR", 0), "skin_t": ("skin °C", 2), "steps": ("steps", 0),
           "met_min": ("MET-min", 0), "mood": ("mood", 1), "energy": ("energy", 1), "stress": ("stress", 1)}
    parts = []
    for k, (lab, nd) in fmt.items():
        b = B.get(k)
        if b and "med" in b:
            parts.append(f"{lab} {rnd(b['med'], nd)} [{rnd(b['p10'], nd)}–{rnd(b['p90'], nd)}] n{b['n']}")
    if "load" in B:
        parts.append(f"cardio load/week {B['load']['wk']}; training h/week {rnd((B['train_min']['wk'] or 0) / 60, 1)}")
    L.append("\n## Baselines, last 60 days: median [p10–p90] n")
    L.append(" | ".join(parts) if parts else "not enough data yet")

    # trends 7 vs 28
    tr = []
    for k, lab, nd, tol in [("sleep_h", "sleep h", 2, 0.25), ("score", "score", 0, 3), ("hrv", "HRV", 0, 3),
                            ("rhr", "RHR", 0, 1.5), ("br", "BR", 1, 0.4), ("skin_t", "skin °C", 2, 0.2),
                            ("steps", "steps", 0, 1000), ("mood", "mood", 1, 0.7), ("energy", "energy", 1, 0.7)]:
        a, na = window_mean(rows_end, end_date, k, 0, 7)
        b, nb = window_mean(rows_end, end_date, k, 7, 35)
        if a is not None and b is not None:
            tr.append(f"{lab} {rnd(a, nd)} vs {rnd(b, nd)} {_arrow(a, b, tol)}")
    if tr:
        L.append("\n## Trend: last 7 d vs previous 28 d")
        L.append(" | ".join(tr))

    # table
    L.append("\n## Last 14 days (night values = night ending that morning)")
    L.append("|date|sleep|h|score d/s/r|deep/REM%|intr|NR/ANS|HRV|RHR|BR|ΔT|steps|training|J|flags|")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in last14:
        sl = f"{r['on']}–{r['off']}" if r.get("on") else ("act" if r.get("sleep_src") else "-")
        sc = f"{_v(r.get('score'))} {_v(r.get('s_dur'))}/{_v(r.get('s_sol'))}/{_v(r.get('s_reg'))}" if r.get("score") is not None else "-"
        tr_ = f"{r['sports']} {r['train_min']}′ L{_v(r.get('load'))}" if r.get("sess") else "-"
        j = " ".join(p for p in [f"m{_g(r['mood'])}" if r.get("mood") is not None else "", f"e{_g(r['energy'])}" if r.get("energy") is not None else "",
                                 r.get("sym") or "", f"alc{r['alc']}" if r.get("alc") else ""] if p) or "-"
        L.append(f"|{r['date'][5:]} {DOW[s2d(r['date']).weekday()][:2]}|{sl}|{_v(r.get('sleep_h'), 1)}|{sc}|"
                 f"{_v(r.get('deep_pct'))}/{_v(r.get('rem_pct'))}|{_v(r.get('intr_min'))}|{_v(r.get('nr'))}/{_v(r.get('ans'))}|"
                 f"{_v(r.get('hrv'))}|{_v(r.get('rhr'))}|{_v(r.get('br'))}|{_v(r.get('skin_dev'))}|{_v(r.get('steps'))}|{tr_}|{j}|{r.get('flags') or ''}|")

    # load
    wl = week_loads(rows_end, end_date, 6)
    if any(w["sess"] for w in wl):
        L.append("\n## Training load per ISO week (cardio load | sessions | hours | mean steps)")
        L.append(" · ".join(f"w{w['week']}: {w['load']} | {w['sess']} | {w['h']} h | {_v(w['steps'])}" for w in wl))
        last = rows_end[-1]
        if last.get("acwr") is not None:
            L.append(f"Acute:chronic (7 d vs 28 d) = {last['acwr']}" + (f"; Polar cardio-load status: {last['cl_status']}" if last.get("cl_status") else ""))

    # flags
    fl = [f"{r['date']}: {r['flags']}" for r in rows_end[-14:] if r.get("flags")]
    L.append("\n## Flags, last 14 days (auto, hints only — see INDEX legend)")
    L += [f"- {f}" for f in fl] or ["- none"]

    # journal
    jr = [(d, j) for d in sorted(journal_rows) if 0 <= (s2d(end_date) - s2d(d)).days < 14 for j in journal_rows[d]]
    L.append("\n## Journal, last 14 days (mood/energy/stress are in the table; repeated items collapsed)")
    L += _journal_lines(jr) or ["- (empty — log mood/symptoms/supplements in journal/log.csv)"]

    # medical
    cur = medical_current(med_dir)
    lab_last, lab_fl = labs_flags(med_dir, since=None)
    L.append("\n## Medical (details: medical/timeline.md, medical/labs.csv)")
    if cur:
        L += cur
    else:
        L.append("- no '## Aktualnie' section in medical/timeline.md yet")
    if lab_last:
        L.append(f"- last labs: {lab_last}" + (f"; out of range (all time, newest last): {'; '.join(lab_fl[-8:])}" if lab_fl else "; none out of range"))
    W.write("status.md", "\n".join(L) + "\n")


def _journal_lines(jr):
    """Collapse routine repeats (same supp/med/caffeine item+dose >= 3x) into one line; drop scores shown in the table."""
    groups = defaultdict(list)
    for d, j in jr:
        if j["type"] in ("supp", "med", "caffeine"):
            groups[(j["type"], j.get("item", ""), j.get("value", ""), j.get("unit", ""))].append((d, j))
    collapsed = {k for k, v in groups.items() if len(v) >= 3}
    out, done = [], set()
    for d, j in jr:
        if j["type"] in ("mood", "energy", "stress") and not j.get("note"):
            continue
        k = (j["type"], j.get("item", ""), j.get("value", ""), j.get("unit", ""))
        if k in collapsed and not j.get("note"):
            if k in done:
                continue
            done.add(k)
            v = [x for x in groups[k] if not x[1].get("note")]
            times = sorted(x[1].get("time") for x in v if x[1].get("time"))
            t = f" usually ~{times[len(times) // 2]}" if times else ""
            out.append(f"- {v[0][0]}→{v[-1][0]} {k[0]} {k[1]} {k[2]}{k[3]} ×{len(v)} days{t}")
            continue
        out.append(f"- {d} {fmt_entry(j)}")
    return out


def render_index(W, coverage, generated, n_days, end_date):
    txt = f"""# claude_health — INDEX (generated {generated}, data through {end_date})

Read order for any health question: status.md first (≈2–3k tokens). Then only what the question needs:
- "why did I sleep badly / why score X" → days/day_<today>.md (night + evening before) and, if needed, day_<yesterday>.md
- "symptom today (sore throat, fatigue)" → status.md flags + days/day_<today>.md + daily/daily_<month>.csv (last 7–14 rows)
- "mood/energy worse for N days" → status.md, daily CSV for the period, sessions CSV, medical/timeline.md, medical/labs.csv
- long-term trends → monthly.csv
- one training in detail → sessions/sessions_<month>.csv, then the day file (HR 5-min profile)

Files
- status.md — profile, coverage, 60-day baselines, 7-vs-28-day trends, last-14-day table, weekly load, flags, journal, medical summary
- daily/daily_YYYY-MM.csv — 1 row/day (columns below)
- sessions/sessions_YYYY-MM.csv — 1 row/training: zones_min = minutes in HR zones Z1/Z2/Z3/Z4/Z5
- days/day_YYYY-MM-DD.md — drill-down ({n_days} days)
- monthly.csv — monthly means/sums
- journal/log.csv — manual log: date,time,type,item,value,unit,note (type: supp, med, symptom, mood, energy, stress, alcohol, caffeine, illness, rpe, weight, note)
- medical/timeline.md (section "## Aktualnie" = current meds/diagnoses, copied into status.md), medical/labs.csv (date,test,value,unit,ref_low,ref_high,note)
- raw/ — untouched Polar exports / API JSON (do not read unless debugging)

Conventions
- Night metrics (sleep, Nightly Recharge, RHR, night skin temp) belong to the date of waking up.
- Times are local. "-" = no data.

Daily columns
on/off sleep start/end; sleep_h actual sleep; bed_h time in bed; score Polar sleep score 1–100; s_dur/s_sol/s_reg sleep score groups (duration/solidity/regeneration); deep_pct/rem_pct share of actual sleep; intr_min interruptions; cont continuity 1–5; cycles sleep cycles; charge sleep charge 1–5;
nr Nightly Recharge status 1–6 (1 very poor … 6 very good); ans ANS charge −10…+10; hrv RMSSD ms (first ~4 h of sleep); br breathing rate/min; hr_nr NR heart rate;
rhr lowest 30-min mean of 24/7 HR in the night window; hr_night mean HR in window; skin_t mean distal skin temp in window; skin_dev deviation vs 28-night median;
steps, kcal, met_min, mod_min/vig_min moderate/vigorous minutes, sed_h sedentary h, nonwear_h; sess/train_min/load (sum cardio load)/load7 (7-day sum)/acwr (7 d vs 28 d avg week); sports; last_end last training end; wt weight;
mood/energy/stress 1–10, alc drinks, caf_last last caffeine time, sym symptoms, supp supplements/meds taken (journal).

Flags (computed vs the person's own trailing 28 days; hints, not diagnoses)
T+x skin temp ≥ +0.5 °C | RHR+x ≥ max(5 bpm, 2 SD) | HRV−x% ≤ −max(1.5 SD, 15%) | BR+x ≥ max(1/min, 2 SD) | MULTI ≥ 2 of the previous four on one night (typical of infection, overreaching, alcohol, late heavy meal) |
SLEEP<6h | SCORE_LOW below own p10 | ANS≤−5 | LATE_HARD hard session ended < 2 h before sleep | TIMING±h sleep midpoint shift ≥ 1.5 h vs 14-day median | ACWR≥1.5 load spike.

Coverage: {"; ".join(f"{k} {v}" for k, v in coverage.items())}
"""
    W.write("INDEX.md", txt)
