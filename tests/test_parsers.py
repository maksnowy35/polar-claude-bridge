"""Minimal self-checks: python tests/test_parsers.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from healthctx.parsers import api_recharge, api_sleep, walk  # noqa: E402
from healthctx.util import iso_dur_s  # noqa: E402


def test_iso():
    assert iso_dur_s("PT29790S") == 29790
    assert iso_dur_s("PT1H35M") == 5700
    assert iso_dur_s("P1DT2H") == 93600


def test_hypnogram_across_midnight():
    n = {"date": "2026-10-16", "sleep_start_time": "2026-10-15T23:00:00+02:00",
         "sleep_end_time": "2026-10-16T01:00:00+02:00", "light_sleep": 1800, "deep_sleep": 2400, "rem_sleep": 1200,
         "hypnogram": {"23:00": 2, "23:30": 4, "00:10": 1, "00:30": 0},
         "heart_rate_samples": {"23:05": 60, "23:35": 50, "00:05": 52, "00:35": 70}}
    s = api_sleep(n)
    assert s["date"] == "2026-10-16"
    assert s["on_min"] == -60 and s["off_min"] == 60
    assert s["hyp"] == "LLLDDDDRRWWW", s["hyp"]
    assert s["hr30"] == [60, 50, 52, 70], s["hr30"]
    assert s["deep_pct"] == 44


def test_recharge_midnight():
    r = api_recharge({"date": "2026-10-16", "nightly_recharge_status": 4, "ans_charge": 2.5,
                      "heart_rate_variability_avg": 50, "breathing_rate_avg": 14.0,
                      "hrv_samples": {"23:50": 40, "23:55": 44, "00:20": 60}, "breathing_samples": {"23:50": 14}})
    assert r["s30_from"] == "23:50", r["s30_from"]
    assert r["hrv30"] == [42, 60], r["hrv30"]


def test_wrappers():
    facts = walk({"whatever": {"nights": [{"sleep_start_time": "2026-10-15T23:00:00+02:00",
                                           "sleep_end_time": "2026-10-16T07:00:00+02:00", "date": "2026-10-16"}]}})
    assert facts and facts[0]["k"] == "sleep"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
