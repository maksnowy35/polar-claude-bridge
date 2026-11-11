import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from healthctx.db import Database
from healthctx.fetch_polar import API_URL, PolarApiError, PolarClient, fetch_all
from healthctx.pipeline import import_raw_files


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    """Answers by path, records the calls so the tests can check the query params."""

    def __init__(self, responses):
        self.responses = responses
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        path = url.removeprefix(API_URL)
        self.calls.append((path, params, timeout))
        return self.responses.get(path, FakeResponse(204))


NIGHT = {"date": "2026-11-10", "sleep_start_time": "2026-11-09T23:30:00+01:00",
         "sleep_end_time": "2026-11-10T07:10:00+01:00", "sleep_score": 80}
RECHARGE = {"date": "2026-11-10", "ans_charge": 3.2, "nightly_recharge_status": 4}
EXERCISES = [
    {"id": "abc-1", "start_time": "2026-11-09T18:00:00", "duration": "PT1H", "sport": "OTHER",
     "detailed_sport_info": "TENNIS", "heart_rate": {"average": 130, "maximum": 170}},
    {"id": "abc-2", "start_time": "2026-11-09T20:00:00", "duration": "PT30M", "sport": "OTHER",
     "detailed_sport_info": "STRETCHING", "heart_rate": {"average": 90, "maximum": 105}},
]


class FetchAllTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="healthctx-fetch-"))
        self.session = FakeSession({
            "/v3/users/sleep": FakeResponse(200, {"nights": [NIGHT]}),
            "/v3/users/nightly-recharge": FakeResponse(200, {"recharges": [RECHARGE]}),
            "/v3/exercises": FakeResponse(200, EXERCISES),
        })
        self.client = PolarClient("token", session=self.session)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_items_land_in_dated_files(self):
        summary = fetch_all(self.client, self.tmp, days=7, today=date(2026, 11, 10))

        self.assertTrue((self.tmp / "sleep" / "2026-11-10.json").exists())
        self.assertTrue((self.tmp / "nightly_recharge" / "2026-11-10.json").exists())
        self.assertEqual(sorted(p.name for p in (self.tmp / "exercise").iterdir()),
                         ["2026-11-09_abc1.json", "2026-11-09_abc2.json"])
        self.assertEqual(summary["activity"], (0, 0))      # 204 = no data, not an error

    def test_second_run_changes_nothing(self):
        fetch_all(self.client, self.tmp, today=date(2026, 11, 10))
        summary = fetch_all(self.client, self.tmp, today=date(2026, 11, 10))

        self.assertTrue(all(written == 0 for _, written in summary.values()))

    def test_range_is_capped_at_28_days(self):
        fetch_all(self.client, self.tmp, days=90, today=date(2026, 11, 10))

        params = dict((path, p) for path, p, _ in self.session.calls)["/v3/users/activities"]
        self.assertEqual((params["from"], params["to"]), ("2026-10-14", "2026-11-10"))
        self.assertEqual(params["steps"], "true")

    def test_fetched_files_are_recognised_by_the_importer(self):
        fetch_all(self.client, self.tmp / "raw", today=date(2026, 11, 10))
        db = Database(f"sqlite:///{self.tmp / 'health.db'}")
        db.migrate()

        import_raw_files(db, self.tmp / "raw")

        kinds = {r["kind"] for r in db.fetch_all("SELECT kind FROM facts")}
        db.close()
        self.assertEqual(kinds, {"sleep", "recharge", "session"})

    def test_every_call_has_a_timeout(self):
        fetch_all(self.client, self.tmp, today=date(2026, 11, 10))

        self.assertTrue(all(timeout for _, _, timeout in self.session.calls))


class ErrorHandlingTest(unittest.TestCase):
    def test_401_explains_what_to_do(self):
        client = PolarClient("token", session=FakeSession({"/v3/users/sleep": FakeResponse(401)}))

        with self.assertRaisesRegex(PolarApiError, "auth_script"):
            client.get("/v3/users/sleep")

    def test_429_reports_retry_after(self):
        client = PolarClient("token", session=FakeSession(
            {"/v3/users/sleep": FakeResponse(429, headers={"Retry-After": "60"})}))

        with self.assertRaisesRegex(PolarApiError, "60"):
            client.get("/v3/users/sleep")

    def test_missing_token(self):
        with self.assertRaises(PolarApiError):
            PolarClient("")


if __name__ == "__main__":
    unittest.main()
