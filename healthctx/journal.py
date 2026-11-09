"""Manual journal (supplements, meds, symptoms, mood...) and medical files.

journal/log.csv columns:  date,time,type,item,value,unit,note
  type: supp | med | symptom | mood | energy | stress | alcohol | caffeine | illness | rpe | weight | note
  mood/energy/stress: value 1-10 (10 = best mood / most energy / most stress)
  alcohol: value = standard drinks;  caffeine: value = mg (time matters)
  symptom/illness: item = e.g. "ból gardła", value = severity 1-3 (optional)
  rpe: item = sport / session start HH:MM, value = 1-10
"""
from __future__ import annotations

import csv
import os
import re
from collections import defaultdict

from .util import mean, rnd


def load_journal(path):
    if not path or not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if not re.match(r"\d{4}-\d{2}-\d{2}", r.get("date", "")):
                continue
            r["type"] = r.get("type", "note").lower()
            rows.append(r)
    rows.sort(key=lambda r: (r["date"], r.get("time", "")))
    return rows


def _f(v):
    try:
        return float(v.replace(",", "."))
    except (ValueError, AttributeError):
        return None


def journal_by_day(rows):
    out = defaultdict(lambda: defaultdict(list))
    for r in rows:
        out[r["date"]][r["type"]].append(r)
    days = {}
    for d, t in out.items():
        rec = {}
        for k in ("mood", "energy", "stress"):
            v = mean([_f(r.get("value")) for r in t.get(k, [])])
            if v is not None:
                rec[k] = rnd(v, 1)
        if t.get("alcohol"):
            rec["alc"] = rnd(sum(_f(r.get("value")) or 1 for r in t["alcohol"]), 1)
        if t.get("caffeine"):
            times = [r.get("time") for r in t["caffeine"] if r.get("time")]
            rec["caf_last"] = max(times) if times else "y"
        sym = [r.get("item") + (f"({r['value']})" if r.get("value") else "") for r in t.get("symptom", []) + t.get("illness", [])]
        if sym:
            rec["sym"] = "|".join(sym)
        sup = [r.get("item") for r in t.get("supp", []) + t.get("med", [])]
        if sup:
            rec["supp"] = "|".join(dict.fromkeys(sup))
        days[d] = rec
    return days


def fmt_entry(r):
    parts = [r.get("time") or "--:--", r["type"], r.get("item", "")]
    if r.get("value"):
        parts.append(r["value"] + (r.get("unit") or ""))
    if r.get("note"):
        parts.append(f"„{r['note']}”")
    return " ".join(p for p in parts if p)


def medical_current(med_dir, max_lines=25):
    """Return the '## Aktualnie' / '## Current' section of medical/timeline.md (if any)."""
    p = os.path.join(med_dir or "", "timeline.md")
    if not med_dir or not os.path.exists(p):
        return None
    lines = open(p, encoding="utf-8").read().splitlines()
    out, on = [], False
    for ln in lines:
        if ln.startswith("## "):
            if on:
                break
            on = ln[3:].strip().lower() in ("aktualnie", "current", "teraz")
            continue
        if on and ln.strip():
            out.append(ln)
    return out[:max_lines] or None


def labs_flags(med_dir, since=None):
    """labs.csv: date,test,value,unit,ref_low,ref_high,note -> latest result per test + out-of-range list."""
    p = os.path.join(med_dir or "", "labs.csv")
    if not med_dir or not os.path.exists(p):
        return None, []
    latest, flagged = {}, []
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("date"):
                continue
            v, lo, hi = _f(r.get("value")), _f(r.get("ref_low")), _f(r.get("ref_high"))
            mark = ("↓" if lo is not None and v is not None and v < lo else
                    "↑" if hi is not None and v is not None and v > hi else "")
            if mark and (since is None or r["date"] >= since):
                flagged.append(f"{r['date']} {r['test']} {r['value']}{r.get('unit','')} {mark} (ref {r.get('ref_low','')}–{r.get('ref_high','')})")
            if r["test"] not in latest or r["date"] >= latest[r["test"]]["date"]:
                latest[r["test"]] = r
    last_date = max((r["date"] for r in latest.values()), default=None)
    return last_date, flagged
