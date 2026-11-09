import unittest

from healthctx.parsers import api_recharge, api_sleep, walk
from healthctx.util import iso_dur_s


class IsoDurationTest(unittest.TestCase):
    def test_polar_duration_formats(self):
        self.assertEqual(iso_dur_s("PT29790S"), 29790)
        self.assertEqual(iso_dur_s("PT1H35M"), 5700)
        self.assertEqual(iso_dur_s("P1DT2H"), 93600)


class ApiSleepTest(unittest.TestCase):
    def test_hypnogram_and_heart_rate_cross_midnight(self):
        night = {
            "date": "2026-10-16",
            "sleep_start_time": "2026-10-15T23:00:00+02:00",
            "sleep_end_time": "2026-10-16T01:00:00+02:00",
            "light_sleep": 1800, "deep_sleep": 2400, "rem_sleep": 1200,
            "hypnogram": {"23:00": 2, "23:30": 4, "00:10": 1, "00:30": 0},
            "heart_rate_samples": {"23:05": 60, "23:35": 50, "00:05": 52, "00:35": 70},
        }

        sleep = api_sleep(night)

        self.assertEqual(sleep["date"], "2026-10-16")
        self.assertEqual((sleep["on_min"], sleep["off_min"]), (-60, 60))
        self.assertEqual(sleep["hyp"], "LLLDDDDRRWWW")
        self.assertEqual(sleep["hr30"], [60, 50, 52, 70])
        self.assertEqual(sleep["deep_pct"], 44)


class ApiRechargeTest(unittest.TestCase):
    def test_samples_starting_before_midnight(self):
        recharge = api_recharge({
            "date": "2026-10-16", "nightly_recharge_status": 4, "ans_charge": 2.5,
            "heart_rate_variability_avg": 50, "breathing_rate_avg": 14.0,
            "hrv_samples": {"23:50": 40, "23:55": 44, "00:20": 60},
            "breathing_samples": {"23:50": 14},
        })

        self.assertEqual(recharge["s30_from"], "23:50")
        self.assertEqual(recharge["hrv30"], [42, 60])


class DetectionTest(unittest.TestCase):
    def test_finds_nights_inside_any_wrapper(self):
        facts = walk({"whatever": {"nights": [{
            "sleep_start_time": "2026-10-15T23:00:00+02:00",
            "sleep_end_time": "2026-10-16T07:00:00+02:00",
            "date": "2026-10-16",
        }]}})

        self.assertEqual(facts[0]["k"], "sleep")


if __name__ == "__main__":
    unittest.main()
