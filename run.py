#!/usr/bin/env python3
"""Build Claude-friendly health context from raw Polar data.

Usage:
  python run.py --raw data/raw --out data/out [--journal data/journal/log.csv] [--medical data/medical]
                [--sports sports.json] [--end 2026-10-16] [--no-cache]

Raw folder may contain Polar Flow export files and/or AccessLink API JSON responses in any
sub-folder structure; files are recognized by content. Parsed results are cached per file
(path + size + mtime) so daily runs only re-parse new or changed files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from healthctx.aggregate import build_rows, collect, latest_profile           # noqa: E402
from healthctx.journal import journal_by_day, load_journal                     # noqa: E402
from healthctx.parsers import parse_file                                       # noqa: E402
from healthctx.render import (Writer, render_csvs, render_day, render_index,   # noqa: E402
                              render_status)

CACHE_VERSION = "1"


def parse_all(raw, cache_dir, use_cache=True):
    facts, stats = [], {"files": 0, "parsed": 0, "cached": 0, "errors": []}
    os.makedirs(cache_dir, exist_ok=True)
    for root, _, files in os.walk(raw):
        for fn in sorted(files):
            if not fn.lower().endswith(".json"):
                continue
            p = os.path.join(root, fn)
            stats["files"] += 1
            st = os.stat(p)
            key = hashlib.sha1(f"{CACHE_VERSION}|{os.path.relpath(p, raw)}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()
            cp = os.path.join(cache_dir, key + ".json")
            if use_cache and os.path.exists(cp):
                facts += json.load(open(cp, encoding="utf-8"))
                stats["cached"] += 1
                continue
            try:
                ff = parse_file(p)
            except Exception as e:                       # keep going; report at the end
                stats["errors"].append(f"{fn}: {type(e).__name__}: {e}")
                continue
            json.dump(ff, open(cp, "w", encoding="utf-8"), separators=(",", ":"))
            facts += ff
            stats["parsed"] += 1
    return facts, stats


def coverage(days, sessions, jrows):
    def span(key):
        ds = sorted(d for d, x in days.items() if x.get(key))
        return f"{ds[0]}→{ds[-1]} ({len(ds)} d)" if ds else "none"
    cov = {"sleep": span("sleep"), "nightly_recharge": span("recharge"), "activity": span("activity"),
           "hr24/7": span("hr_bins")}
    sk = sorted(d for d, x in days.items() if x.get("skin_bins") or x.get("skin_night"))
    cov["skin_temp"] = f"{sk[0]}→{sk[-1]} ({len(sk)} d)" if sk else "none"
    cov["trainings"] = f"{sessions[0]['date']}→{sessions[-1]['date']} ({len(sessions)})" if sessions else "none"
    cov["journal"] = f"{len(jrows)} entries" if jrows else "none"
    return cov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--journal")
    ap.add_argument("--medical")
    ap.add_argument("--sports", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "sports.json"))
    ap.add_argument("--end", help="last date to report in status.md (default: latest date with data)")
    ap.add_argument("--cache", default=None, help="cache dir (default: <out>/.cache)")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()

    t0 = time.time()
    sports = json.load(open(a.sports, encoding="utf-8")) if a.sports and os.path.exists(a.sports) else {}
    sports = {k: v for k, v in sports.items() if not k.startswith("_")}
    facts, stats = parse_all(a.raw, a.cache or os.path.join(a.out, ".cache"), not a.no_cache)
    days, sessions, profiles, tests, skipped = collect(facts, sports)
    jrows = load_journal(a.journal)
    jdays = journal_by_day(jrows)
    jby = {}
    for j in jrows:
        jby.setdefault(j["date"], []).append(j)
    profile = latest_profile(profiles, tests)
    rows = build_rows(days, jdays, profile)
    if not rows:
        print("No data recognized.", stats, skipped)
        return 1
    end = a.end or rows[-1]["date"]
    rowmap = {r["date"]: r for r in rows}
    cov = coverage(days, sessions, jrows)
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")

    W = Writer(a.out)
    render_csvs(W, rows, sessions)
    for d in sorted(set(days) | set(jby)):
        render_day(W, d, days, rowmap, jby)
    render_status(W, rows, profile, cov, jby, a.medical, end, gen)
    render_index(W, cov, gen, len(days), end)

    with open(os.path.join(a.out, ".changed.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(W.changed))
    print(f"files: {stats['files']} (parsed {stats['parsed']}, cached {stats['cached']}), facts: {len(facts)}, "
          f"days: {len(rows)}, sessions: {len(sessions)}, outputs: {W.total} (changed {len(W.changed)}), "
          f"{time.time() - t0:.1f}s")
    if skipped:
        print("skipped:", skipped)
    for e in stats["errors"]:
        print("ERROR", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
